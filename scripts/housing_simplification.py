"""Consolidate the legacy clamshell history; verify native solid equality."""
import base64
import copy
import hashlib
import json

from cad_build import profile
from model_cleanup import prune


def housing_counts(model):
    bodies = {26, 46, 201, 204}
    operations = []
    for key in ('extrudes', 'revolves', 'body_features'):
        for record in model[key]:
            referenced = set(record.get('body_ids', [])) | set(record.get('target_body_ids', []))
            referenced |= set(record.get('tool_body_ids', []))
            # Cut/join records retain unused new-body allocations. Those IDs
            # do not identify the solids the feature actually modifies.
            if record.get('operation') == 'new_body':
                referenced |= set(record.get('new_body_ids', []))
            referenced |= {record.get('body_id'), record.get('target_body_id')}
            if referenced & bodies:
                operations.append(record)
    names = {r['sketch_name'] for r in operations if 'sketch_name' in r}
    sketches = [s for s in model['sketches'] if s['name'] in names]
    datums = {s['plane']['datum_id'] for s in sketches if s['plane']['type'] == 'datum_plane'}
    return {'solid_operations': len(operations), 'sketches': len(sketches),
            'datum_planes': len(datums), 'history_entries': len(operations) + len(sketches) + len(datums)}


def simplify_housing(original):
    model = copy.deepcopy(original)
    history = model['document']['history']['features']
    features = {f['id']: f for f in history}
    extrudes = {e['feature_id']: e for e in model['extrudes']}
    sketches = {s['name']: s for s in model['sketches']}
    if 44 not in extrudes:
        return model, {'already_simplified': True}
    retired = {44, 47, 52, 89, 200, 202, 232, 234, 242, 244, 266, 270, 273, 274, 279}
    assert all(i in features for i in retired)

    # Union of three overlapping rectangular blocks, drawn once in XY.
    blank = sketches['Sketch15']
    blank['name'] = 'Chassis stepped outer blank'
    blank['plane'] = {'type': 'origin_plane', 'plane': 'xy'}
    blank['basis'] = copy.deepcopy(sketches['Sketch96']['basis'])
    profile(blank, [(-34, 107.9), (34, 107.9), (34, 131), (24, 131),
                    (24, 206.5), (-44, 206.5), (-44, 130.5), (-34, 130.5)])
    extrudes[41].update(name=blank['name'], sketch_name=blank['name'],
        extent={'type': 'two_sides', 'distance': 24., 'second_distance': 24.}, flip=False)
    features[40]['name'] = features[41]['name'] = blank['name']

    # One axial profile cuts front opening, collar, sleeve, journal and adapter
    # chamber in both halves. Sketch X is axial Y; sketch Y is radius.
    bore = sketches['Chassis integral thrust stops and journal seat']
    points = [(e['position']['x'], e['position']['y'])
              for _, e in bore['snapshot']['entities'] if e['type'] == 'point']
    assert points[:2] == [(110.9, 0.), (110.9, 14.8)]
    profile(bore, [(107.8, 0.), (107.8, 16.5), (110.9, 16.5), *points[1:]])
    name = 'Shared stepped bearing and adapter chamber - revolve cut'
    features[301]['name'] = name
    next(r for r in model['revolves'] if r['feature_id'] == 301)['name'] = name

    # Each mirrored extension is trimmed once instead of once per side of XY.
    extrudes[265].update(extent={'type': 'two_sides', 'distance': 50., 'second_distance': 8.}, flip=False)
    extrudes[269].update(extent={'type': 'two_sides', 'distance': 6., 'second_distance': 50.}, flip=False)

    # One symmetric cut replaces repeated half-specific wire exits.
    extrudes[278].update(name='Shared wire exit relief', target_body_ids=[26, 46],
        extent={'type': 'two_sides', 'distance': 1.4, 'second_distance': 1.4}, flip=False)
    features[278]['name'] = 'Shared wire exit relief'
    # Preserve counterbore selection: kernel profile order differs from sketch
    # entity order. The final four-hole operation includes both rear seats.
    features[226]['name'] = extrudes[226]['name'] = 'Front M3 head seats'

    # Plane33 and Plane47 define the same Z24 reference.
    for sketch in model['sketches']:
        if sketch['plane'] == {'type': 'datum_plane', 'datum_id': 47}:
            sketch['plane']['datum_id'] = 33
    # Symmetric connector pocket needs no dedicated offset plane.
    wire = sketches['Sketch80']
    wire['plane'] = {'type': 'origin_plane', 'plane': 'xy'}
    wire['basis'] = copy.deepcopy(sketches['Sketch96']['basis'])
    extrudes[229].update(extent={'type': 'two_sides', 'distance': 10.4, 'second_distance': 10.4}, flip=False)
    for feature_id in retired:
        features[feature_id]['suppressed'] = True
    model, pruning = prune(model)
    return model, {'features_before': len(history),
        'features_after': len(model['document']['history']['features']),
        'housing_before': housing_counts(original), 'housing_after': housing_counts(model),
        'retired_solid_operations': sorted(retired),
        'removed_features_including_sketches_and_planes': pruning['removed_inactive_features'],
        'suppressed_features_remaining': 0}


def verify_housing(client, before_model, after_model):
    """Compare analytic solids in both directions; restore editable model.

    Temporary STEP references/copies are verification only, never saved.
    """
    client.call('cad_load_project_model', {'model_json': json.dumps(before_model)})
    before_scene = client.call('solid_scene')
    assert not before_scene['errors'], before_scene['errors']
    references = {body: client.call('solid_export_step', {'body_ids': [body]})['bytes_base64']
                  for body in (26, 46)}
    client.call('cad_load_project_model', {'model_json': json.dumps(after_model)})
    after_scene = client.call('solid_scene')
    assert not after_scene['errors'], after_scene['errors']
    before_bodies = {b['id']: b for b in before_scene['bodies']}
    after_bodies = {b['id']: b for b in after_scene['bodies']}
    assert before_bodies.keys() == after_bodies.keys()
    unaffected = sorted(before_bodies.keys() - {26, 46})
    for body in unaffected:
        for key in ('positions', 'indices'):
            assert before_bodies[body]['mesh'][key] == after_bodies[body]['mesh'][key], body
    assert before_model['body_appearances'] == after_model['body_appearances']
    assert before_model['assembly'] == after_model['assembly']
    checks = []
    try:
        for body in (26, 46):
            prior_ids = {b['id'] for b in client.call('solid_scene')['bodies']}
            client.call('solid_import_step', {'file_name': f'prior-housing-{body}.STEP',
                                             'data_base64': references[body]})
            reference = next(iter({b['id'] for b in client.call('solid_scene')['bodies']} - prior_ids))
            prior_ids = {b['id'] for b in client.call('solid_scene')['bodies']}
            client.call('solid_move_copy', {'body_ids': [body],
                'translation': {'x': 0, 'y': 0, 'z': 0}, 'pivot': {'x': 0, 'y': 0, 'z': 0}, 'copy': True})
            duplicate = next(iter({b['id'] for b in client.call('solid_scene')['bodies']} - prior_ids))
            differences = {}
            for target, tool, label in ((body, reference, 'new_minus_old'),
                                       (reference, duplicate, 'old_minus_new')):
                client.call('solid_combine', {'target_body_id': target, 'tool_body_ids': [tool],
                                             'operation': 'cut', 'keep_tools': True})
                scene = client.call('solid_scene')
                assert not scene['errors'], scene['errors']
                mesh = next(b['mesh'] for b in scene['bodies'] if b['id'] == target)
                assert not mesh['positions'] and not mesh['indices'], (body, label)
                differences[label] = {'native_boolean_residual_empty': True}
            checks.append({'body_id': body,
                'reference_step_sha256': hashlib.sha256(base64.b64decode(references[body])).hexdigest(),
                **differences, 'native_faces_before': len(before_bodies[body]['faces']),
                'native_faces_after': len(after_bodies[body]['faces'])})
    finally:
        client.call('cad_load_project_model', {'model_json': json.dumps(after_model)})
    return {'method': 'Native analytic STEP/BREP boolean subtraction in both directions',
        'scope': 'Finished housing geometry, at CAD kernel precision',
        'housing_checks': checks, 'unchanged_other_body_ids': unaffected,
        'other_body_mesh_arrays_identical': True, 'material_appearances_and_assembly_identical': True,
        'temporary_comparison_bodies_saved': False}
