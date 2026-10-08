"""Export the matching reviewed upper half and natively slice its sparse copy.

Run with uv run --no-project --python 3.14 --with numpy --with trimesh
--with manifold3d python scripts/prepare_sparse_servo_upper_test.py.
Uses the explicitly reviewed CAD and lower sparse template, never historical
production geometry. Preserves existing files; sends no printer commands.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import re
import tempfile
import uuid
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

from build_servo_rear_fit_test import digest, native_plane, read_model
from cad_client import CadClient
from check_housing_print import slice_native
from prepare_bambu_latest import CORE, PRODUCTION, UPPER, project_parts, read_zip, transform_text
from print_packer import component_count, mesh_from_object

ROOT = Path(__file__).resolve().parents[1]
CAD = ROOT / 'experiments/garden-auger-servo-snug-test.limo'
TEMPLATE = ROOT / 'garden-auger-lower-servo-sparse-test.3mf'
TARGET = ROOT / 'garden-auger-upper-servo-sparse-test.3mf'
REPORT = ROOT / 'servo-upper-sparse-print-verification.json'
NAME = 'PETG - Housing upper'


def exported_mesh(raw, placed=False):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        model = ET.fromstring(archive.read('3D/3dmodel.model'))
    objects = [o for o in model.findall('{*}resources/{*}object')
               if o.find('{*}mesh') is not None]
    assert len(objects) == 1
    mesh = mesh_from_object(objects[0])
    if placed:
        items = model.findall('{*}build/{*}item')
        assert len(items) == 1
        owner = next(o for o in model.findall('{*}resources/{*}object')
                     if o.get('id') == items[0].get('objectid'))
        components = owner.findall('{*}components/{*}component')
        assert len(components) == 1 and components[0].get('objectid') == objects[0].get('id')
        for node in (components[0], items[0]):
            transform = np.array([float(x) for x in node.get('transform', '1 0 0 0 1 0 0 0 1 0 0 0').split()])
            mesh.vertices = mesh.vertices @ transform[:9].reshape(3, 3) + transform[9:]
    return mesh


def main():
    review = json.loads((ROOT / 'servo-snug-review.json').read_text())
    lower = json.loads((ROOT / 'servo-sparse-print-verification.json').read_text())
    assert digest(CAD) == review['cad_sha256'], 'CAD differs from reviewed snug nest'
    assert digest(TEMPLATE) == lower['test_sha256'], 'Template differs from verified sparse lower half'
    preserved = {p: digest(ROOT / p) for p in [
        str(CAD.relative_to(ROOT)), TEMPLATE.name,
        'garden-auger-lower-servo-snug-test.3mf', 'garden-auger-lower-fit-test.3mf',
        'garden-auger-bambu-latest.3mf', 'garden-auger-direct-drive.nbcad']}
    build = ROOT / '.build/servo-upper-sparse-test'
    build.mkdir(parents=True, exist_ok=True)
    with CadClient(stderr_path=build / 'engine-stderr.log') as c:
        engine = {'path': str(c.executable), 'sha256': digest(c.executable)}
        source_model = read_model(CAD)
        component = next(d for d in source_model['assembly']['component_structure']['definitions']
                         if d['id'] == 6)
        assert component['name'] == 'Housing upper' and component['body_ids'] == [26]
        c.call('cad_load_project_model', {'model_json': json.dumps(source_model)})
        scene = c.call('solid_scene')
        assert not scene['errors'], scene['errors']
        body = next(b for b in scene['bodies'] if b['id'] == 26)
        native_faces = {key: native_plane(body, 'XYZ'.index(value['axis']), value['coordinate_mm'])
                        for key, value in review['native_nest_faces']['26'].items()}
        # An installed engine update must still reproduce the previously printed
        # lower mesh and the recorded mating datums before handing off its upper.
        lower_export = c.call('solid_export_3mf', {'body_ids': [46], 'scope': 'definition',
            'linear_deflection': .08, 'angular_deflection': .2, 'slicer_target': 'standard'})
        lower_mesh = exported_mesh(base64.b64decode(lower_export['bytes_base64']))
        _, _, lower_parts = project_parts(read_zip(TEMPLATE))
        lower_part = lower_parts['PETG - Housing lower']
        assert np.array_equal(lower_mesh.faces, lower_part['faces'])
        assert np.allclose(lower_mesh.vertices - lower_mesh.bounds.mean(0),
                           lower_part['vertices'], rtol=0, atol=1e-8)
        mating = c.call('assembly_interference_check', {'occurrence_ids': [6, 7],
            'clearance_threshold_mm': 1})
        assert mating['exact'] and mating['pairs'] and not any(p['interfering'] for p in mating['pairs'])
        export = c.call('solid_export_3mf', {'body_ids': [26], 'scope': 'definition',
            'linear_deflection': .08, 'angular_deflection': .2, 'slicer_target': 'standard'})
        raw = base64.b64decode(export['bytes_base64'])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            native_model = ET.fromstring(archive.read('3D/3dmodel.model'))
        materials = [n.attrib for n in native_model.findall('.//{*}base')]
        assert materials == [{'name': 'PETG, Chassis yellow', 'displaycolor': '#E5AE3C'}], materials
        mesh = exported_mesh(raw)
        assert mesh.is_watertight and mesh.is_volume and component_count(mesh) == 1
        center = mesh.bounds.mean(axis=0)
        vertices = mesh.vertices - center
        rotated = vertices @ UPPER.T
        translation = np.array([128., 128., -rotated[:, 2].min()])
        world_translation = translation - UPPER @ center
        c.call('upsert_named_view', {'name': 'Print - matching sparse upper fit test',
            'camera': {'position': [280, -180, 330], 'target': [128, 128, 10.3], 'up': [0, 0, 1]},
            'visible_body_ids': [26], 'occurrence_offsets': [{'occurrence_id': 6,
                'translation': world_translation.tolist(), 'rotation': [0, 1, 0, 0]}],
            'print_layout': True, 'print_bed': {'name': 'Bambu X2D main', 'size_mm': [256, 256, 261]}})
        preflight = c.call('solid_export_preflight', {'body_ids': [26],
            'named_view': 'Print - matching sparse upper fit test'})
        assert preflight['ok'] and not preflight['timeline_errors'], preflight
        assert not any(i['code'] in ('below_bed', 'outside_bed', 'possible_overlap')
                       for i in preflight['layout']['issues']), preflight
        placed = c.call('solid_export_3mf', {'body_ids': [26], 'scope': 'assembly',
            'named_view': 'Print - matching sparse upper fit test',
            'linear_deflection': .08, 'angular_deflection': .2, 'slicer_target': 'standard'})
        placed_raw = base64.b64decode(placed['bytes_base64'])
        (build / 'upper-native-placement.3mf').write_bytes(placed_raw)
        placed_mesh = exported_mesh(placed_raw, placed=True)
        assert np.array_equal(placed_mesh.faces, mesh.faces)
        assert np.allclose(placed_mesh.vertices, rotated + translation, rtol=0, atol=1e-6), {
            'native_bounds': placed_mesh.bounds.tolist(),
            'expected_bounds': [(rotated + translation).min(0).tolist(), (rotated + translation).max(0).tolist()],
            'maximum_delta': float(np.abs(placed_mesh.vertices - rotated - translation).max()),
            'first_deltas': (placed_mesh.vertices[:3] - rotated[:3] - translation).tolist()}
        (build / 'upper-native-export.3mf').write_bytes(raw)

    before = read_zip(TEMPLATE)
    entries = dict(before)
    model, config, parts = project_parts(entries)
    assert set(parts) == {'PETG - Housing lower'}
    part = parts['PETG - Housing lower']
    mesh_model = ET.fromstring(entries[part['mesh_path']])
    node = mesh_model.find('.//{*}mesh')
    node.clear()
    vs = ET.SubElement(node, f'{{{CORE}}}vertices')
    ts = ET.SubElement(node, f'{{{CORE}}}triangles')
    for v in vertices:
        ET.SubElement(vs, f'{{{CORE}}}vertex', dict(zip(('x', 'y', 'z'), (f'{x:.12g}' for x in v))))
    for t in mesh.faces:
        ET.SubElement(ts, f'{{{CORE}}}triangle', dict(zip(('v1', 'v2', 'v3'), (str(int(x)) for x in t))))
    ET.register_namespace('', CORE)
    entries[part['mesh_path']] = ET.tostring(mesh_model, encoding='utf-8', xml_declaration=True)
    item = model.find('{*}build/{*}item')
    assert len(model.findall('{*}build/{*}item')) == 1
    item.set('transform', transform_text(UPPER, translation))
    # Give this distinct upper part its own stable identity in the copied package.
    identity = uuid.uuid5(uuid.NAMESPACE_URL, review['cad_sha256'] + '/body/26')
    for obj in model.findall('{*}resources/{*}object'):
        obj.set(f'{{{PRODUCTION}}}UUID', str(identity))
        for component in obj.findall('{*}components/{*}component'):
            component.set(f'{{{PRODUCTION}}}UUID', str(uuid.uuid5(identity, 'mesh')))
    item.set(f'{{{PRODUCTION}}}UUID', str(uuid.uuid5(identity, 'instance')))
    entries['3D/3dmodel.model'] = ET.tostring(model, encoding='utf-8', xml_declaration=True)
    for node in config.iter():
        key = node.get('key', '')
        if 'face_count' in node.attrib:
            node.set('face_count', str(len(mesh.faces)))
        if key == 'name':
            node.set('value', NAME)
        elif key == 'source_file':
            node.set('value', str(CAD.relative_to(ROOT)).replace('\\', '/'))
        elif key == 'source_object_id':
            node.set('value', '26')
        elif key.startswith('source_offset_'):
            node.set('value', f'{center["xyz".index(key[-1])]:.12g}')
        elif key == 'plater_name':
            node.set('value', 'PETG - Snug servo fit - SPARSE upper half')
        if node.tag == 'part':
            node.set('uuid', str(uuid.uuid5(identity, 'part')))
        if node.tag == 'assemble_item' and 'instance_id' in node.attrib:
            node.set('transform', transform_text(UPPER, translation))
    entries['Metadata/model_settings.config'] = ET.tostring(config, encoding='utf-8', xml_declaration=True)
    entries = {n: d for n, d in entries.items() if not n.endswith('.gcode')
        and not (n.startswith('Metadata/') and n.endswith('.png'))
        and not (n.startswith('Metadata/servo-') and n.endswith('.txt'))}
    info = ET.fromstring(entries['Metadata/slice_info.config'])
    for node in list(info):
        if node.tag != 'header':
            info.remove(node)
    entries['Metadata/slice_info.config'] = ET.tostring(info, encoding='utf-8', xml_declaration=True)
    ET.register_namespace('', 'http://schemas.openxmlformats.org/package/2006/relationships')
    for n, data in list(entries.items()):
        if n.endswith('.rels'):
            entries[n] = ET.tostring(ET.fromstring(data), encoding='utf-8', xml_declaration=True)
    entries['Metadata/servo-upper-sparse-fit-test.txt'] = (
        'ONE MATCHING UPPER HALF - DIMENSIONAL FIT TEST. Reviewed snug-nest body 26; '
        'ear slots 3.00, outer-ear capture 56.40, capture width 20.40 mm. '
        'Same sparse process/printer/PETG settings as the lower fit test. '
        'Continuous outer face on bed; pocket upward. No supports or prime tower. '
        'Check screw-recess bridges and matching-half closure physically. '
        'Owner reports lower half seems OK; full assembly and loaded strength remain unqualified. '
        'No printer command sent.').encode()
    output = Path(tempfile.mkdtemp(prefix='slice-', dir=build))
    print('Reviewed upper exported; native placement/mesh checks passed. Slicing in Bambu.', flush=True)
    exported, native = slice_native(entries, output)
    gcode = exported['Metadata/plate_1.gcode']
    roles = re.findall(rb'^; FEATURE: ([^\r\n]+)', gcode, re.MULTILINE)
    assert not any(b'Prime' in r or b'Wipe' in r for r in roles), set(roles)
    refreshed = {n: d for n, d in exported.items() if
        re.match(r'Metadata/(?:plate(?:_no_light)?_|top_|pick_)\d+(?:_small)?\.png$', n)}
    refreshed['Metadata/slice_info.config'] = exported['Metadata/slice_info.config']
    final = {**entries, **refreshed}
    assert final['Metadata/project_settings.config'] == before['Metadata/project_settings.config']
    assert not any(n.endswith('.gcode') for n in final)
    with zipfile.ZipFile(TARGET, 'w', zipfile.ZIP_DEFLATED) as archive:
        for n, data in final.items():
            archive.writestr(n, data)
    saved = read_zip(TARGET)
    saved_model, saved_config, saved_parts = project_parts(saved)
    assert set(saved_parts) == {NAME} and saved_parts[NAME]['extruder'] == 1
    assert np.array_equal(saved_parts[NAME]['faces'], mesh.faces)
    assert np.allclose(saved_parts[NAME]['vertices'], vertices, rtol=0, atol=1e-8)
    assert not any(m.get('key') in lower['test_settings'] for m in saved_config.findall('object/metadata'))
    transform = np.array([float(x) for x in saved_model.find('{*}build/{*}item').get('transform').split()])
    bed_vertices = saved_parts[NAME]['vertices'] @ transform[:9].reshape(3, 3) + transform[9:]
    assert np.allclose(bed_vertices, placed_mesh.vertices, rtol=0, atol=1e-6)
    assert all(digest(ROOT / p) == h for p, h in preserved.items())
    plate = native['native_plate']
    report = {'status': 'Matching upper sparse fit test; full physical assembly pending',
        'cad': str(CAD.relative_to(ROOT)).replace('\\', '/'), 'cad_sha256': review['cad_sha256'],
        'body_id': 26, 'body_name': NAME, 'native_engine': engine,
        'original_review_engine_sha256': review['native_engine']['sha256'],
        'current_engine_matches_original_review': engine['sha256'] == review['native_engine']['sha256'],
        'current_engine_lower_mesh_matches_verified_sparse_lower': True,
        'native_upper_locating_faces_match_review': native_faces,
        'native_matching_halves_nominal_interference': mating,
        'native_export_materials': materials,
        'physical_feedback_source': 'source/references/servo-lower-fit-feedback-20261007.json',
        'template': TEMPLATE.name, 'template_sha256': lower['test_sha256'],
        'test': TARGET.name, 'test_sha256': digest(TARGET),
        'native_export_mesh_matches_packaged_test': True, 'one_closed_connected_upper_half': True,
        'native_print_placement_matches_packaged_test': True, 'native_preflight': preflight,
        'bed_bounds_mm': [bed_vertices.min(axis=0).tolist(), bed_vertices.max(axis=0).tolist()],
        'bed_transform': transform.tolist(), 'global_settings_byte_identical_to_sparse_lower': True,
        'test_settings': lower['test_settings'], 'object_uses_global_strength_settings': True,
        'native_slice': native, 'gcode_feature_roles': sorted({r.decode() for r in roles}),
        'time_seconds': plate['total_predication'],
        'filament_weight_g': sum(f['total_used_g'] for f in plate['filaments']),
        'native_run_directory': str(output.relative_to(ROOT)),
        'preserved_files_sha256': preserved, 'reviewed_CAD_modified': False,
        'preview_and_slice_statistics_refreshed': True, 'final_project_gcode_embedded': False,
        'printer_command_sent': False, 'project_loaded_in_ui_confirmed': False,
        'limitations': ['Native slice and sampled CAD checks do not certify manufactured fit or strength.',
            'Check unsupported upper screw-recess roofs for bridge quality.',
            'Lower half alone seems OK per owner; matching-half closure, alignment, rotation and cable routing are pending.',
            'Shaft engagement and usable screw thread depth remain unconfirmed.',
            'Limo typed Bambu inspector rejects rectilinear; native Bambu slicing is the process evidence.']}
    REPORT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'test': TARGET.name, 'minutes': report['time_seconds'] / 60,
        'filament_g': report['filament_weight_g'], 'bed_bounds_mm': report['bed_bounds_mm']}, indent=2), flush=True)


if __name__ == '__main__':
    main()
