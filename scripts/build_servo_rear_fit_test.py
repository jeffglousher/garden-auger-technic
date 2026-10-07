"""Build a separate rear-clearance test from the owner's 27/38 mm readings.

Native CAD checks a conservative clearance envelope, not a measured complete
servo. Keep the existing ear/shaft/adapter datums; measurement 4 is unavailable.
Never overwrite the production model or the owner's saved Bambu test project.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
import trimesh

from cad_build import Builder, save_project
from cad_client import CadClient
from prepare_bambu_latest import CORE, project_parts, read_zip
from print_packer import component_count, mesh_from_object

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'garden-auger-direct-drive.nbcad'
TEMPLATE = ROOT / 'garden-auger-lower-fit-test.3mf'
CAD = ROOT / 'experiments/garden-auger-servo-27mm-test.limo'
PRINT = ROOT / 'garden-auger-lower-servo-27mm-test.3mf'
REPORT = ROOT / 'servo-27mm-test-verification.json'
BUILD = ROOT / '.build/servo-27mm-test'
REAR_EXTENSION = 27.0 - 24.7


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_model(path):
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read('model.json'))


def native_plane(body, axis, target):
    candidates = [f for f in body['faces'] if f.get('plane') and
                  abs(abs(f['plane']['normal'][axis])-1) < 1e-8 and
                  abs(f['plane']['origin'][axis]-target) < 1e-7]
    assert candidates, (body['id'], axis, target)
    face = candidates[0]
    return {'body_id': body['id'], 'face_key': face['key'],
            'coordinate_mm': face['plane']['origin'][axis], 'axis': 'XYZ'[axis]}


def probe(client):
    before = {b['id'] for b in client.call('solid_scene')['bodies']}
    # Literal input: 27 mm from rear ear face Y165.5 gives rear case Y192.5.
    # Front face and plan length are conservative old envelopes, not readings.
    builder = Builder(client)
    builder.box('Temporary 27 mm rear-clearance probe',
                (-30.5, 152.7, 10, 192.5, -10, 10), 'new_body', [])
    body = next(iter({b['id'] for b in client.call('solid_scene')['bodies']}-before))
    builder.box('Temporary left ear', (-38, 162.8, -30.5, 165.5, -10, 10), 'join', [body])
    builder.box('Temporary right ear', (10, 162.8, 18, 165.5, -10, 10), 'join', [body])
    result = client.call('assembly_create_component', {
        'name': 'Temporary conservative fit probe', 'body_ids': [body],
        'absorb_promoted_bodies': True})
    model = client.call('cad_project_model')
    model = json.loads(model) if isinstance(model, str) else model
    occurrence = next(o['id'] for o in model['assembly']['component_structure']['occurrences']
                      if o['name'] == 'Temporary conservative fit probe')
    return body, occurrence


def probe_results(client, expected_interference):
    body, occurrence = probe(client)
    checks = []
    for axial in [-.19, 0, .19]:
        client.call('assembly_set_occurrence_pose', {'occurrence_id': occurrence,
            'local_pose': {'translation': [0, axial, 0], 'rotation': [0, 0, 0, 1]}})
        result = client.call('assembly_interference_check', {'clearance_threshold_mm': 2})
        pairs = [{k: p[k] for k in ('body_a', 'body_b', 'interfering',
                 'minimum_clearance_mm', 'overlap_volume_mm3')}
                 for p in result['pairs'] if body in {p['body_a'], p['body_b']}
                 and bool({26, 46} & {p['body_a'], p['body_b']})]
        assert result['exact'] and len(pairs) == 2, result
        if not all(p['interfering'] == expected_interference for p in pairs):
            value = client.call('cad_project_model')
            value = json.loads(value) if isinstance(value, str) else value
            (BUILD/'failed-probe-model.json').write_text(json.dumps(value), encoding='utf-8')
            (BUILD/'failed-probe-scene.json').write_text(json.dumps(client.call('solid_scene')), encoding='utf-8')
            (BUILD/'failed-probe-result.json').write_text(json.dumps(result), encoding='utf-8')
            raise AssertionError(pairs)
        checks.append({'axial_translation_mm': axial, 'exact': True, 'pairs': pairs})
    return checks


def package_test(raw_export, template=TEMPLATE, output=PRINT, note=None):
    with zipfile.ZipFile(io.BytesIO(raw_export)) as archive:
        xml = ET.fromstring(archive.read('3D/3dmodel.model'))
    obj = next(o for o in xml.findall('{*}resources/{*}object') if o.find('{*}mesh') is not None)
    mesh = mesh_from_object(obj)
    assert component_count(mesh) == 1
    center = (mesh.bounds[0] + mesh.bounds[1]) / 2
    vertices = mesh.vertices-center
    entries = read_zip(template)
    _, config, parts = project_parts(entries)
    assert set(parts) == {'PETG - Housing lower'}, 'Template must contain one lower half'
    part = parts['PETG - Housing lower']
    previous = ET.fromstring(entries[part['mesh_path']])
    node = previous.find('.//{*}mesh')
    node.clear()
    vs = ET.SubElement(node, f'{{{CORE}}}vertices')
    ts = ET.SubElement(node, f'{{{CORE}}}triangles')
    for v in vertices:
        ET.SubElement(vs, f'{{{CORE}}}vertex', dict(zip(('x','y','z'), (f'{x:.12g}' for x in v))))
    for t in mesh.faces:
        ET.SubElement(ts, f'{{{CORE}}}triangle', dict(zip(('v1','v2','v3'), (str(int(x)) for x in t))))
    entries[part['mesh_path']] = ET.tostring(previous, encoding='utf-8', xml_declaration=True)
    settings = next(o for o in config.findall('object') if o.get('id') == part['object_id'])
    for node in settings.iter():
        if 'face_count' in node.attrib:
            node.set('face_count', str(len(mesh.faces)))
        if node.tag == 'metadata' and node.get('key', '').startswith('source_offset_'):
            axis = 'xyz'.index(node.get('key')[-1])
            node.set('value', f'{center[axis]:.12g}')
    entries['Metadata/model_settings.config'] = ET.tostring(config, encoding='utf-8', xml_declaration=True)
    # Geometry invalidates slice caches; preserve the actual printer/process
    # and object settings rather than resetting strength defaults.
    entries = {n: b for n, b in entries.items() if not n.endswith('.gcode') and
               not re.match(r'Metadata/(?:plate(?:_no_light)?_|top_|pick_)\d+', n)}
    if 'Metadata/slice_info.config' in entries:
        info = ET.fromstring(entries['Metadata/slice_info.config'])
        for child in list(info):
            if child.tag != 'header':
                info.remove(child)
        entries['Metadata/slice_info.config'] = ET.tostring(info, encoding='utf-8', xml_declaration=True)
    for name in list(entries):
        if not name.endswith('.rels'):
            continue
        rels = ET.fromstring(entries[name])
        for rel in list(rels):
            target = rel.get('Target', '').lstrip('/')
            if target not in entries and not rel.get('TargetMode') == 'External':
                rels.remove(rel)
        entries[name] = ET.tostring(rels, encoding='utf-8', xml_declaration=True)
    entries['Metadata/servo-rear-fit-test.txt'] = (note or
        '27 mm ear-underside-to-rear fit test; rear bay extended 2.30 mm. '
        'Ear seats and adapter/auger/sleeve datums retained. '
        'This is a test article; complete physical fit and shaft-to-ear position remain unverified. '
        'Slice again; saved printer/process and object overrides are retained.').encode()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    result = read_zip(output)
    original = read_zip(template)
    assert result['Metadata/project_settings.config'] == original['Metadata/project_settings.config']
    _, actual_config, actual_parts = project_parts(result)
    assert set(actual_parts) == set(parts)
    assert np.allclose(actual_parts['PETG - Housing lower']['vertices'], vertices, atol=1e-8)
    before_values = [(n.get('key'), n.get('value')) for n in
                     ET.fromstring(original['Metadata/model_settings.config']).findall('object/metadata')]
    after_values = [(n.get('key'), n.get('value')) for n in actual_config.findall('object/metadata')]
    assert before_values == after_values, 'Object-level user settings changed'
    return {'one_closed_connected_lower_half': True,
            'native_export_mesh_matches_packaged_test': True,
            'printer_and_process_config_byte_identical': True,
            'object_settings_preserved': True, 'fresh_slice_required': True,
            'template_sha256': digest(template), 'test_sha256': digest(output)}


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    original_hashes = {p.name: digest(p) for p in [SOURCE, TEMPLATE]}
    original = read_model(SOURCE)
    candidate = copy.deepcopy(original)
    sketches = {s['name']: s for s in candidate['sketches']}
    case = sketches['Sketch45']
    assert abs(case['basis']['origin'][1]-191.7) < 1e-7, 'This test applies only to the original rear bay'
    assert abs(sketches['Sketch62']['basis']['origin'][1]-165.7) < 1e-7
    readings = json.loads((ROOT/'source/references/servo-caliper-readings.json').read_text())
    assert readings['readings']['1']['value'] == 27 and readings['readings']['5']['value'] == 38
    case['basis']['origin'][1] += REAR_EXTENSION
    datum = next(p for p in candidate['datum_planes'] if p['datum_id'] == case['plane']['datum_id'])
    datum['basis']['origin'][1] += REAR_EXTENSION
    datum['source']['distance'] -= REAR_EXTENSION
    cut = next(e for e in candidate['extrudes'] if e['feature_id'] == 131)
    cut['extent']['distance'] += REAR_EXTENSION
    # Rear fastener-pad joins originally followed this pocket cut. At the
    # extended rear datum they refill a small left corner of the servo bay.
    # Reuse the same cut after both joins and before cable/fastener cuts.
    history = candidate['document']['history']['features']
    pocket_feature = next(f for f in history if f['id'] == 131)
    history.remove(pocket_feature)
    history.insert(next(i for i, f in enumerate(history) if f['id'] == 312)+1, pocket_feature)
    # The displayed purchased-part body is explicitly a conservative envelope:
    # grow the rear only, without inferring a new shaft-to-ear dimension.
    case_ref = sketches['Sketch1']
    case_ref['basis']['origin'][2] -= REAR_EXTENSION
    ref_datum = next(p for p in candidate['datum_planes'] if p['datum_id'] == case_ref['plane']['datum_id'])
    ref_datum['basis']['origin'][2] -= REAR_EXTENSION
    ref_datum['source']['distance'] -= REAR_EXTENSION
    next(e for e in candidate['extrudes'] if e['feature_id'] == 3)['extent']['distance'] += REAR_EXTENSION
    for group in ['definitions', 'occurrences']:
        for item in candidate['assembly']['component_structure'][group]:
            if item.get('component_id', item['id']) == 3:
                item['name'] = '27 mm rear-clearance envelope - shaft and front datums provisional'
    candidate['document']['name'] = 'Garden auger - 27 mm servo rear fit test'
    with CadClient() as client:
        native_engine = client.executable
        client.call('cad_load_project_model', {'model_json': json.dumps(original)})
        old_scene = client.call('solid_scene')
        failure = probe_results(client, True)
        client.call('cad_load_project_model', {'model_json': json.dumps(candidate)})
        new_scene = client.call('solid_scene')
        assert not new_scene['errors'], new_scene['errors']
        unchanged = [15, 90, 216, 221]
        for bid in unchanged:
            a = next(b for b in old_scene['bodies'] if b['id'] == bid)
            b = next(b for b in new_scene['bodies'] if b['id'] == bid)
            assert a['mesh'] == b['mesh'], bid
        assert candidate['body_appearances'] == original['body_appearances']
        assert candidate['assembly']['component_structure']['occurrences'][1:] == original['assembly']['component_structure']['occurrences'][1:]
        planes = {}
        for bid in [26, 46]:
            body = next(b for b in new_scene['bodies'] if b['id'] == bid)
            rear = native_plane(body, 1, 194.0)
            seat = native_plane(body, 1, 165.7)
            front_seat = native_plane(body, 1, 162.6)
            planes[str(bid)] = {'rear': rear, 'seat': seat, 'front_seat': front_seat,
                'rear_seat_to_wall_mm': rear['coordinate_mm']-seat['coordinate_mm'],
                'ear_slot_width_mm': seat['coordinate_mm']-front_seat['coordinate_mm']}
        fit = probe_results(client, False)
        client.call('cad_load_project_model', {'model_json': json.dumps(candidate)})
        nominal = client.call('assembly_interference_check', {'clearance_threshold_mm': 2})
        assert nominal['exact'] and not any(p['interfering'] for p in nominal['pairs'])
        preflight = client.call('solid_export_preflight', {'body_ids': [26, 46]})
        assert preflight['ok'] and not preflight['timeline_errors'], preflight
        save_project(client, CAD)
        export = client.call('solid_export_3mf', {'body_ids': [46], 'scope': 'definition',
            'linear_deflection': .08, 'angular_deflection': .2, 'slicer_target': 'standard'})
        raw = base64.b64decode(export['bytes_base64'])
        (BUILD/'lower-native.3mf').write_bytes(raw)
        packaging = package_test(raw)
    assert all(digest(ROOT/n) == h for n, h in original_hashes.items())
    report = {'status': 'Separate rear-clearance test article; physical fit not yet qualified',
        'user_readings_mm': {'1_ear_underside_to_rear': 27, '4_tip_to_rear': None, '5_case_plan_length': 38},
        'measurement_uncertainty_supplied': False,
        'deviation_from_drawing_mm': {'ear_to_rear': 2.3, 'case_plan_vs_40mm_drawing': -2},
        'prior_housing_shortage_at_rear_stop_mm': 1.0,
        'revision': {'rear_wall_y_before': 191.7, 'rear_wall_y_after': 194.0,
                     'rear_extension_mm': REAR_EXTENSION, 'ear_seats_y_preserved': [162.6,165.7],
                     'rear_seat_to_wall_after_mm': 28.3, 'rear_margin_for_27mm_at_rear_stop_mm': 1.3,
                     'plan_pocket_length_preserved_mm': 41.3,
                     'existing_case_cut_reordered_after_rear_pad_joins': True,
                     'additional_geometry_features': 0,
                     'failed_unreordered_cut_native_overlap_each_half_mm3': 0.0035595160669871758,
                     'failed_unreordered_cut_native_overlap_bounds_lower_mm':
                         [[-30.5,192.46987915039062,-10],[-30.47641372680664,192.5,0]]},
        'native_engine_sha256': digest(native_engine),
        'native_old_housing_failure': failure, 'native_revised_housing_fit': fit,
        'native_retained_planes': planes, 'native_nominal_assembly': nominal,
        'native_preflight': preflight, 'unchanged_print_body_meshes': unchanged,
        'materials_preserved': True, 'mechanical_poses_preserved': True,
        'saved_production_and_user_test_preserved': original_hashes,
        'test_cad': str(CAD.relative_to(ROOT)), 'test_cad_sha256': digest(CAD),
        'test_print': PRINT.name, 'test_print_checks': packaging,
        'probe_saved_or_exported': False,
        'scope': ['27 mm rear length is user measured; no new reading for shaft tip-to-rear.',
                  'The 38 mm case plan length is recorded; retain the conservative larger plan pocket because case-to-shaft offset was not measured.',
                  'Ear position relative to the shaft and stationary front face remain source-derived. The displayed reference is a clearance envelope, not a fully measured servo.',
                  'Screw clearance and rear outer stock are retained; physical cable-boot position and total assembly seating still need a test.',
                  'Native checks establish geometric fit of the stated envelope, not manufactured fit or strength.',
                  'No production file was overwritten; the owner-modified Bambu template and its object settings are preserved.']}
    REPORT.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'test_cad': report['test_cad'], 'test_print': PRINT.name,
        'native_old_failure_reproduced': True, 'native_fit_checks': len(fit),
        'rear_stop_to_wall_mm': 28.3, 'source_and_user_project_unchanged': True}), flush=True)


if __name__ == '__main__':
    main()
