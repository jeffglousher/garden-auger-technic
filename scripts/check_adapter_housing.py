"""Verify the saved adapter against both housing halves without rebuilding CAD."""
import hashlib
import json
from pathlib import Path
import zipfile

from cad_client import CadClient
from design_parameters import MAX_DRIVE_AXIS_OFFSET, PRINT_SIZE_TOLERANCE

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / 'garden-auger-direct-drive.nbcad'
    with zipfile.ZipFile(source) as archive:
        model = json.loads(archive.read('model.json'))
    audit = json.loads((ROOT / 'direct-drive-verification.json').read_text())
    sketch = next(s for s in model['sketches'] if s['name'] == 'Chassis integral thrust stops and journal seat')
    points = [e['position'] for _, e in sketch['snapshot']['entities'] if e['type'] == 'point']
    # The last axial segment is the cylindrical adapter chamber.
    # This revolve sketch uses X for the axial coordinate and Y for radius.
    rear_y = max(p['x'] for p in points)
    chamber_radius = max(p['y'] for p in points if abs(p['x'] - rear_y) < 1e-8)
    dimensions = audit['adapter_dimensions_mm']
    occurrence = next(o for o in model['assembly']['component_structure']['occurrences'] if o['component_id'] == 14)
    installed_axial = (audit['square_fit_stack']['required_flange_face_y'][1] -
                       audit['square_fit_stack']['required_flange_face_y'][0]) / 2
    checks = []
    with CadClient() as client:
        client.call('cad_load_project_model', {'model_json': json.dumps(model)})
        scene = client.call('solid_scene')
        adapter = next(b for b in scene['bodies'] if b['id'] == 216)
        adapter_rear_y = max(f['plane']['origin'][1] for f in adapter['faces'] if f['plane'])
        poses = [[0, 0, 0]] + [[x, y, z] for y in [-installed_axial, installed_axial]
            for x, z in [(MAX_DRIVE_AXIS_OFFSET, 0), (-MAX_DRIVE_AXIS_OFFSET, 0),
                         (0, MAX_DRIVE_AXIS_OFFSET), (0, -MAX_DRIVE_AXIS_OFFSET)]]
        for translation in poses:
            client.call('assembly_set_occurrence_pose', {'occurrence_id': occurrence['id'],
                'local_pose': {'translation': translation, 'rotation': [0, 0, 0, 1]}})
            result = client.call('assembly_interference_check', {'clearance_threshold_mm': 5})
            pairs = [p for p in result['pairs'] if 216 in {p['body_a'], p['body_b']} and
                     bool({26, 46} & {p['body_a'], p['body_b']})]
            assert result['exact'] and len(pairs) == 2
            assert all(not p['interfering'] and p['overlap_volume_mm3'] == 0 for p in pairs), pairs
            checks.append({'adapter_translation_mm': translation, 'exact': True,
                           'housing_pairs': [{k: p[k] for k in ('body_a', 'body_b',
                               'minimum_clearance_mm', 'overlap_volume_mm3')} for p in pairs]})
    diameter = 2 * chamber_radius
    boss_gap = (diameter - dimensions['spline_boss_diameter']) / 2
    flange_gap = (diameter - dimensions['flange_diameter']) / 2
    axial_gap = rear_y - adapter_rear_y
    boss_min = boss_gap - PRINT_SIZE_TOLERANCE - MAX_DRIVE_AXIS_OFFSET
    flange_min = flange_gap - PRINT_SIZE_TOLERANCE - MAX_DRIVE_AXIS_OFFSET
    axial_min = axial_gap - 2 * PRINT_SIZE_TOLERANCE - installed_axial
    assert boss_min > 0 and flange_min > 0 and axial_min > 0
    report = {'source_project': source.name,
        'source_project_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'housing_change_required_for_this_adapter_revision': False,
        'print_progress_known': False,
        'nominal_mm': {'housing_chamber_diameter': diameter, 'boss_radial_clearance': boss_gap,
                       'flange_radial_clearance': flange_gap, 'adapter_rear_y': adapter_rear_y,
                       'housing_chamber_end_y': rear_y, 'adapter_rear_to_housing_wall_gap': axial_gap},
        'conditional_minimum_mm': {'boss_radial_clearance': boss_min, 'flange_radial_clearance': flange_min,
                                    'adapter_rear_to_housing_wall_gap': axial_min},
        'acceptance_limits': {'printed_diameters_and_axial_extrema_plus_minus_mm': PRINT_SIZE_TOLERANCE,
                              'installed_adapter_axial_plus_minus_mm': installed_axial,
                              'drive_axis_radial_offset_max_mm': MAX_DRIVE_AXIS_OFFSET},
        'native_ideal_geometry_checks': checks,
        'scope': 'Adapter against both printed housing halves. Minimum gaps require the stated printed and installed acceptance limits. Actual purchased servo shaft/nose clearance remains unverified.',
        'unchanged_print_parts': audit['unchanged_print_parts']}
    (ROOT / 'adapter-housing-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'nominal_mm': report['nominal_mm'],
                      'conditional_minimum_mm': report['conditional_minimum_mm'],
                      'exact_native_housing_checks': len(checks),
                      'housing_change_required': False}, indent=2))


if __name__ == '__main__':
    main()
