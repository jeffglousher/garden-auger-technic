"""Review the saved clamshell, complete auger, fasteners and assembly path.

Use native B-rep intersections for movement; use mesh sections for independent
hole/wall measurements. This does not qualify purchased hardware or torque.
"""
import base64
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
import trimesh

from audit_dimensions import section_segments, segment_distance, vertical_hits
from cad_client import CadClient
from print_packer import mesh_from_object

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = '940e024634e4a6526b57c2783ebf87731270294d'


def read_model(data):
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return json.loads(archive.read('model.json'))


def pair_summary(result, moving, fixed):
    assert result['exact'], result
    return [{k: p[k] for k in ('body_a', 'body_b', 'interfering',
            'minimum_clearance_mm', 'overlap_volume_mm3')}
            for p in result['pairs'] if bool(moving & {p['body_a'], p['body_b']})
            and bool(fixed & {p['body_a'], p['body_b']})]


def pose(client, occurrence, translation, angle=0):
    client.call('assembly_set_occurrence_pose', {'occurrence_id': occurrence,
        'local_pose': {'translation': translation,
                       'rotation': [0, math.sin(math.radians(angle)/2), 0,
                                    math.cos(math.radians(angle)/2)]}})


def flight_entry_bound(flight):
    """Clip flight triangles to the entrance and bound all radial directions."""
    def clip(polygon, y, keep_high):
        output = []
        if not polygon:
            return output
        for a, b in zip(polygon, polygon[1:] + polygon[:1]):
            inside_a = a[1] >= y if keep_high else a[1] <= y
            inside_b = b[1] >= y if keep_high else b[1] <= y
            if inside_a:
                output.append(a)
            if inside_a != inside_b:
                output.append(a + (b-a) * ((y-a[1])/(b[1]-a[1])))
        return output
    points = []
    for triangle in flight.triangles:
        if triangle[:, 1].max() < 107.6 or triangle[:, 1].min() > 113.4:
            continue
        polygon = clip(list(triangle), 107.6, True)
        points.extend(clip(polygon, 113.4, False))
    points = np.array(points)
    assert len(points), 'No flight geometry at the entrance'
    throat_radius = 16.6 - (points[:, 1] + .3 - 107.8) / 5.9
    return float(np.min(throat_radius - np.hypot(points[:, 0], points[:, 2]) - .5))


def native_flight_entry_bound(client):
    export = client.call('solid_export_3mf', {'body_ids': [90], 'scope': 'definition',
        'linear_deflection': .02, 'angular_deflection': .1, 'slicer_target': 'bambu_studio'})
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(export['bytes_base64']))) as archive:
        xml = ET.fromstring(archive.read('3D/3dmodel.model'))
    objects = xml.findall('{*}resources/{*}object')
    assert len(objects) == 1, 'Unexpected extra flight export body'
    return flight_entry_bound(mesh_from_object(objects[0]))


def main():
    source = ROOT / 'garden-auger-direct-drive.nbcad'
    current = source.read_bytes()
    model = read_model(current)
    prior = subprocess.check_output(['git', 'show', f'{REFERENCE}:{source.name}'], cwd=ROOT)
    reference = read_model(prior)
    regression = []
    movement = []
    with CadClient() as client:
        client.call('cad_load_project_model', {'model_json': json.dumps(reference)})
        for shift in [0, .3]:
            pose(client, 8, [.5, shift, 0])
            result = client.call('assembly_interference_check', {'clearance_threshold_mm': .01})
            pairs = pair_summary(result, {90}, {26, 46})
            assert any(p['interfering'] for p in pairs), 'Regression was not reproduced'
            regression.append({'auger_translation_mm': [.5, shift, 0], 'pairs': pairs})
        client.call('cad_load_project_model', {'model_json': json.dumps(model)})
        scene = client.call('solid_scene')
        assert not scene['errors'], scene['errors']
        preflight = client.call('solid_export_preflight')
        assert preflight['ok'] and not preflight['timeline_errors'], preflight
        bound = native_flight_entry_bound(client)
        assert bound - .02 - .08 - .2 > .2, bound
        nominal = client.call('assembly_interference_check', {'clearance_threshold_mm': 2})
        assert not any(p['interfering'] for p in nominal['pairs']
                       if {p['body_a'], p['body_b']} != {15, 90}), nominal
        servo_pairs = pair_summary(nominal, {1}, {26, 46})
        assert len(servo_pairs) == 2
        assert all(p['minimum_clearance_mm'] >= .199 for p in servo_pairs), servo_pairs
        # Include both source bodies of the one-piece auger. The earlier
        # radial-offset checks covered body15 and missed the flight body90.
        for shift in [-.3, 0, .3]:
            for dx, dz in [(0, 0), (.5, 0), (-.5, 0), (0, .5), (0, -.5)]:
                for angle in [0, 45, 90]:
                    pose(client, 8, [dx, shift, dz], angle)
                    pose(client, 14, [dx, 0, dz], angle)
                    result = client.call('assembly_interference_check', {'clearance_threshold_mm': .01})
                    pairs = pair_summary(result, {15, 90, 216}, {26, 46})
                    assert len(pairs) == 6, pairs
                    assert not any(p['interfering'] for p in pairs), (shift, dx, dz, angle, pairs)
                    movement.append({'translation_mm': [dx, shift, dz],
                        'common_rotation_deg': angle, 'pairs': pairs})
            print(f'Complete native auger travel checks at {shift:+.2f} mm: {len(movement)} poses', flush=True)
        client.call('cad_load_project_model', {'model_json': json.dumps(model)})
        closure = []
        for height in [12, 6, 3.5, .5, 0]:
            pose(client, 6, [0, 0, height])
            result = client.call('assembly_interference_check', {'clearance_threshold_mm': .01})
            pairs = pair_summary(result, {26}, {46, 1, 15, 90, 216, 221})
            assert not any(p['interfering'] for p in pairs), (height, pairs)
            closure.append({'upper_lift_mm': height, 'no_interference': True, 'exact': True})

    bodies = {b['id']: b for b in scene['bodies']}
    def mesh(body):
        data = bodies[body]['mesh']
        return trimesh.Trimesh(np.array(data['positions']).reshape(-1, 3),
                               np.array(data['indices']).reshape(-1, 3), process=False)
    lower, upper = mesh(46), mesh(26)
    pilots = next(s for s in model['sketches'] if s['name'] == 'Sketch56')
    centers = [(e['center']['x'], e['center']['y']) for _, e in pilots['snapshot']['entities']
               if e['type'] == 'circle']
    inserts = []
    for center in centers:
        walls = []
        for z in np.linspace(-.05, -5.65, 57):
            distance = segment_distance(np.array(center), section_segments(lower, z))
            walls.append(float(distance[distance > 2.15].min()) - 2.3)
        wall = min(walls)
        assert wall - .225 > 1.6, (center, wall)
        assert not vertical_hits(upper, center), ('Blocked screw hole', center)
        hits = vertical_hits(lower, center)
        assert len(hits) == 2 and hits[0] <= -8 and abs(hits[1] + 6.7) < .001, hits
        seat = vertical_hits(upper, (center[0] + 2.5, center[1]))[-1]
        expected = 8 if center[1] < 150 else 12.7
        assert abs(seat - expected) < .001, (center, seat)
        length = 12 if center[1] < 150 else 18
        insertion = length - seat
        assert 3 <= insertion <= 5.7
        inserts.append({'center_xy_mm': center, 'pilot_diameter_mm': 4,
            'pilot_depth_mm': 6.7, 'radial_wall_sample_min_mm': wall,
            'wall_min_with_dimensional_allowance_mm': wall - .225,
            'wall_section_samples': 57, 'screw_passage_open': True,
            'head_seat_height_mm': seat, 'screw_length_mm': length,
            'nominal_insert_engagement_mm': insertion,
            'nominal_pilot_bottom_room_mm': 6.7 - insertion})
    # Retain exactly the auger, sleeve and adapter that are already in use.
    retained = {}
    for path in sorted((ROOT / 'print-parts/direct-drive').glob('*.stl')):
        if path.name.startswith('petg-housing'):
            continue
        relative = path.relative_to(ROOT).as_posix()
        old = subprocess.check_output(['git', 'show', f'{REFERENCE}:{relative}'], cwd=ROOT)
        assert old == path.read_bytes(), relative
        retained[relative] = hashlib.sha256(old).hexdigest()
    flight_gaps = [p['minimum_clearance_mm'] for test in movement for p in test['pairs']
                   if 90 in (p['body_a'], p['body_b'])]
    assert min(flight_gaps) > .3, min(flight_gaps)
    # For the axisymmetric entrance, bound the entire triangular flight
    # surface across EVERY rotation and offset direction. Radius is convex;
    # throat radius is linear in Y, so the minimum gap over each clipped
    # triangle occurs at a vertex. Rearward travel is the tightest taper case.
    # Budget both the 0.02 mm verification and 0.08 mm manufacturing export
    # deviations, plus 0.10 mm per printed mating surface. This bound was
    # measured on an explicitly exported native mesh, not a default preview.
    report = {'source_project': source.name,
        'source_project_sha256': hashlib.sha256(current).hexdigest(),
        'reference_commit': REFERENCE, 'reference_sha256': hashlib.sha256(prior).hexdigest(),
        'confirmed_prior_flight_interference': regression,
        'revised_motion_checks': movement, 'motion_check_count': len(movement),
        'motion_check_scope': '45 exact B-rep poses: 0/45/90 degree rotations, 0/0.5 mm cardinal offsets and +/-0.30 mm axial travel. Additional continuous-rotation entrance check uses the conservative flight surface bound below.',
        'minimum_sampled_flight_to_housing_clearance_mm': min(flight_gaps),
        'continuous_rotation_flight_entry_bound': {'method': 'Minimum vertex gap on clipped triangular flight surface against the linear axisymmetric entrance; radial offset applied in every direction by the triangle inequality.',
            'rearward_travel_mm': .3, 'radial_offset_mm': .5,
            'minimum_surface_bound_mm': bound, 'native_verification_deflection_mm': .02,
            'manufacturing_export_deflection_mm': .08,
            'printed_surface_allowance_each_mm': .1,
            'conditional_minimum_gap_mm': bound - .02 - .08 - .2,
            'scope': 'Complete final flight at the housing entrance; not a load or wear qualification.'},
        'nominal_servo_case_and_ear_clearance': servo_pairs,
        'clamshell_closure_path': closure, 'heat_set_inserts_and_screws': inserts,
        'native_preflight': preflight, 'retained_non_housing_stls': retained,
        'unchanged_feature_count': len(model['document']['history']['features']) == len(reference['document']['history']['features']),
        'current_feature_count': len(model['document']['history']['features']),
        'hardware_dimension_authority': 'User-confirmed accurate servo diagram: 40 by 20 mm case, 2.7 mm ears and shown shaft/case stack.',
        'unresolved_physical_checks': ['Cable boot envelope is not dimensioned in the servo diagram',
            'Usable shaft thread depth and physically selected press-fit pilot',
            'Installed adapter position and alignment, printed running fits, loaded torque and wear'],
        'readiness': 'Corrected housing geometry; final hardware fit and load acceptance remain physical checks.'}
    (ROOT / 'preprint-review.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'motion_checks': len(movement), 'flight_min_clearance_mm': min(flight_gaps),
                     'insert_min_wall_mm': min(i['wall_min_with_dimensional_allowance_mm'] for i in inserts),
                     'feature_count': report['current_feature_count'], 'unchanged_non_housing_stls': len(retained)}, indent=2))


if __name__ == '__main__':
    main()
