"""Print-oriented housing cavities: two functional seats and one cable path."""
import copy
import json

from cad_build import profile
from model_cleanup import prune
from housing_simplification import housing_counts
from design_parameters import REAR_ADAPTER_CHAMBER_END_Y
from servo_dimensions import (
    CASE_LEFT_X,CASE_RIGHT_X,CASE_WIDTH,CASE_CLEARANCE,
    CASE_POCKET_FRONT_Y,CASE_POCKET_REAR_Y,EAR_POCKET_FRONT_Y,EAR_POCKET_REAR_Y,
    EAR_THICKNESS,EAR_UNDERSIDE_TO_REAR,set_plane_origin,
)

FRONT_THROAT_DIAMETER = 31.2
FRONT_ENTRY_DIAMETER = 33.2
REAR_COLLAR_THROAT_DIAMETER = 31.0
CABLE_CHANNEL_HEIGHT = 8.0
SERVO_EAR_POCKET_REAR_Y = EAR_POCKET_REAR_Y
SERVO_EAR_POCKET_DEPTH = EAR_POCKET_REAR_Y-EAR_POCKET_FRONT_Y


def nesting_profile():
    # Keep the two collar stop planes and their original opening diameters.
    # One entrance taper clears the last flight at the permitted shaft offset.
    # Keep the smaller collar-stop opening: enlarging the entire throat would
    # reduce the thrust collar's retaining overlap. No extra profile step.
    return [(107.8, 0), (107.8, FRONT_ENTRY_DIAMETER / 2),
        (113.7, FRONT_THROAT_DIAMETER / 2), (113.7, 17.8),
        (117.3, 17.8), (117.3, REAR_COLLAR_THROAT_DIAMETER / 2),
        (120.3, REAR_COLLAR_THROAT_DIAMETER / 2), (120.3, 17.8),
        (131.2, 17.8), (131.2, 14.8),
        (REAR_ADAPTER_CHAMBER_END_Y, 14.8), (REAR_ADAPTER_CHAMBER_END_Y, 0)]


def nest_housing(original):
    model = copy.deepcopy(original)
    features = {f['id']: f for f in model['document']['history']['features']}
    extrudes = {e['feature_id']: e for e in model['extrudes']}
    sketches = {s['name']: s for s in model['sketches']}
    bore = sketches['Chassis integral thrust stops and journal seat']
    before_vertices = sum(e['type'] == 'point' for _, e in bore['snapshot']['entities'])
    profile(bore, nesting_profile())
    name = 'Nested collar and sleeve seats - one revolve cut'
    features[301]['name'] = name
    next(r for r in model['revolves'] if r['feature_id'] == 301)['name'] = name

    # The drawing says 40 mm; its catalog row gives a larger 40.5 mm length.
    # Clear the larger length with 0.4 mm per-side allowance, holding the
    # stated output-axis-to-right-edge datum at 10 mm.
    case = sketches['Sketch45']
    left=CASE_LEFT_X-CASE_CLEARANCE;right=CASE_RIGHT_X+CASE_CLEARANCE
    half=CASE_WIDTH/2+CASE_CLEARANCE
    profile(case, [(left,-half),(right,-half),(right,half),(left,half)])
    set_plane_origin(model,['Sketch45'],1,CASE_POCKET_REAR_Y)
    extrudes[131]['extent']['distance']=CASE_POCKET_REAR_Y-CASE_POCKET_FRONT_Y
    features[131]['name'] = extrudes[131]['name'] = 'Servo case pocket - 41.3 by 20.8; 40.0 axial span'
    ears = sketches['Sketch62']
    # Retain the two native rectangular loops and their profile order.
    ears['basis']['origin'][1] = SERVO_EAR_POCKET_REAR_Y
    plane = next(p for p in model['datum_planes'] if p['datum_id'] == ears['plane']['datum_id'])
    plane['basis']['origin'][1] = SERVO_EAR_POCKET_REAR_Y
    plane['source']['distance'] = -SERVO_EAR_POCKET_REAR_Y
    extrudes[183]['extent']['distance'] = SERVO_EAR_POCKET_DEPTH
    features[183]['name'] = extrudes[183]['name'] = 'Servo ears - final cut after housing extensions'
    # An extension previously filled the outer 0.5 mm of the right ear pocket.
    # Reorder the existing cut after those joins instead of adding another cut.
    history = model['document']['history']['features']
    ear_cut = next(f for f in history if f['id'] == 183)
    history.remove(ear_cut)
    history.insert(next(i for i, f in enumerate(history) if f['id'] == 277) + 1, ear_cut)

    # The connector stays outside. Lay the cable into the open clamshell seam.
    # Keep a short bay at the photographed case-side cable boot, then turn
    # toward the existing outlet. No tall connector parking pocket is needed.
    cable = sketches['Sketch95']
    cable_name = 'Cable boot and seam exit - one open channel'
    cable['name'] = cable_name
    profile(cable, [(10.4, 180.6), (50, 180.6), (50, 185.8),
                    (16, 185.8), (16, 191.2), (10.4, 191.2)])
    features[cable['feature_id']]['name'] = cable_name
    features[278]['name'] = cable_name
    extrudes[278].update(name=cable_name, sketch_name=cable_name,
        extent={'type': 'two_sides', 'distance': CABLE_CHANNEL_HEIGHT / 2,
                'second_distance': CABLE_CHANNEL_HEIGHT / 2}, flip=False)
    if 229 in features:
        features[229]['suppressed'] = True
    model, pruning = prune(model)
    return model, {'finished_housing_geometry_changed': True,
        'housing_before': housing_counts(original), 'housing_after': housing_counts(model),
        'removed_history_entries': pruning['removed_inactive_features'],
        'axial_profile_vertices_before': before_vertices,
        'axial_profile_vertices_after': len(nesting_profile()),
        'removed_geometry': ['Separate diameter 33 front-entry counterbore',
            'Two housing tapers around the collar roots (one flight-clearance entrance taper retained)',
            '20.8 mm tall internal connector parking pocket'],
        'retained_geometry': ['Both integral collar thrust-stop planes and opening diameters',
            'Loose PLA sleeve seat and both sleeve stop planes',
            '29.6 mm rear journal/adapter chamber', 'Servo case and ear pockets',
            'Clamshell locating pins/sockets', 'M3 screw seats and ruthex insert pilots'],
        'flight_entry': {'entry_diameter_mm': FRONT_ENTRY_DIAMETER,
            'collar_stop_opening_diameter_mm': FRONT_THROAT_DIAMETER,
            'taper_length_mm': 5.9, 'additional_profile_vertices': 0,
            'reason': 'Clear the complete last flight, including permitted radial offset and axial travel.'},
        'servo_pockets': {'case_length_mm': right-left, 'case_width_mm':2*half,
            'case_axial_span_mm':CASE_POCKET_REAR_Y-CASE_POCKET_FRONT_Y,
            'case_pocket_y_mm':[CASE_POCKET_FRONT_Y,CASE_POCKET_REAR_Y],
            'ear_pocket_y_mm':[EAR_POCKET_FRONT_Y,EAR_POCKET_REAR_Y],
            'ear_capture_span_mm': SERVO_EAR_POCKET_DEPTH,
            'ear_thickness_reference_mm': EAR_THICKNESS, 'ear_axial_float_nominal_mm': .4,
            'ear_underside_to_rear_reference_mm':EAR_UNDERSIDE_TO_REAR,
            'ear_datum_correction_mm':-2.7,
            'ear_cut_moved_after_extensions': True,
            'dimension_authority': 'User supplied drawing: 41.5 tip-to-rear, 37.5 case height, 24.7 underside-of-ear-to-rear, 2.7 ear thickness. Design clears the larger 40.5 mm case length in its catalog row.',
            'drawing_dimensions_user_confirmed': True,
            'printed_assembly_fit_verified': False},
        'wire_channel': {'height_mm': CABLE_CHANNEL_HEIGHT,
            'outlet_width_mm': 5.2, 'case_side_boot_bay_y_mm': [180.6, 191.2],
            'assembly': 'Lay cable in split seam; keep JR connector outside housing',
            'physical_boot_fit_verified': False,
            'reference_photo_url': 'https://www.injora.com/cdn/shop/files/1_5_af7067ed-c672-4de7-882a-37d01068c61d.jpg?v=1787641003&width=720',
            'scope': 'Boot allowance is a design envelope; supplier does not dimension the boot.'}}


def verify_nesting(client, before, after):
    client.call('cad_load_project_model', {'model_json': json.dumps(before)})
    old_scene = client.call('solid_scene')
    client.call('cad_load_project_model', {'model_json': json.dumps(after)})
    new_scene = client.call('solid_scene')
    assert not old_scene['errors'] and not new_scene['errors']
    old_bodies = {b['id']: b for b in old_scene['bodies']}
    new_bodies = {b['id']: b for b in new_scene['bodies']}
    assert old_bodies.keys() == new_bodies.keys()
    for body in old_bodies.keys() - {26, 46}:
        for key in ('positions', 'indices'):
            assert old_bodies[body]['mesh'][key] == new_bodies[body]['mesh'][key], body
    assert before['body_appearances'] == after['body_appearances']
    assert before['assembly'] == after['assembly']
    # Inspect actual native profile coordinates, not just parameter constants.
    sketch = next(s for s in after['sketches'] if s['name'] == 'Chassis integral thrust stops and journal seat')
    points = [(e['position']['x'], e['position']['y'])
              for _, e in sketch['snapshot']['entities'] if e['type'] == 'point']
    assert points == nesting_profile()
    sleeve_occurrence = next(o['id'] for o in after['assembly']['component_structure']['occurrences']
                             if o['component_id'] == 16)
    checks = []
    try:
        for shift, blocked in [(-.29, False), (.19, False), (-.31, True), (.21, True)]:
            client.call('assembly_set_occurrence_pose', {'occurrence_id': sleeve_occurrence,
                'local_pose': {'translation': [0, shift, 0], 'rotation': [0, 0, 0, 1]}})
            result = client.call('assembly_interference_check', {'clearance_threshold_mm': .01})
            pairs = [p for p in result['pairs'] if 221 in {p['body_a'], p['body_b']}
                     and bool({26, 46} & {p['body_a'], p['body_b']})]
            assert result['exact'] and len(pairs) == 2
            assert any(p['interfering'] for p in pairs) == blocked, (shift, pairs)
            checks.append({'sleeve_translation_mm': shift, 'exact': True,
                           'chassis_blocks_overtravel': blocked})
        client.call('cad_load_project_model', {'model_json': json.dumps(after)})
        auger = next(o['id'] for o in after['assembly']['component_structure']['occurrences']
                     if o['component_id'] == 8)
        for dx, dz in [(.5, 0), (-.5, 0), (0, .5), (0, -.5)]:
            client.call('assembly_set_occurrence_pose', {'occurrence_id': auger,
                'local_pose': {'translation': [dx, 0, dz], 'rotation': [0, 0, 0, 1]}})
            result = client.call('assembly_interference_check', {'clearance_threshold_mm': .01})
            pairs = [p for p in result['pairs'] if bool({15, 90} & {p['body_a'], p['body_b']})
                     and bool({26, 46} & {p['body_a'], p['body_b']})]
            assert result['exact'] and len(pairs) == 4
            assert not any(p['interfering'] for p in pairs), (dx, dz, pairs)
            checks.append({'auger_axis_offset_xz_mm': [dx, dz], 'exact': True,
                           'auger_housing_overlap_mm3': 0})
    finally:
        client.call('cad_load_project_model', {'model_json': json.dumps(after)})
    return {'finished_housing_geometry_identical_to_previous': False,
        'other_body_mesh_arrays_identical': True, 'unchanged_body_ids': [1, 15, 90, 216, 221],
        'materials_and_assembly_placements_preserved': True,
        'collar_stop_y_mm': [113.7, 117.3], 'collar_opening_diameters_mm': [31.2, 31.0],
        'collar_end_float_nominal_mm': .6, 'sleeve_stop_y_mm': [120.3, 131.2],
        'sleeve_end_float_nominal_mm': .5,
        'native_faces': {str(body): {'before': len(old_bodies[body]['faces']),
            'after': len(new_bodies[body]['faces'])} for body in (26, 46)},
        'sleeve_capture_and_journal_offset_checks': checks}
