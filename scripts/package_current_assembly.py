"""Recheck current native CAD and package all five parts on four Bambu plates.

Uses the historical Bambu file for saved profiles only. Never refreshes or
overwrites it. Evidence reuses .build/clamshell-detail (150 MiB additional
budget, garden-auger owner; retain until physical review/recovery settles).
No printer commands are sent.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import trimesh
from cad_client import CadClient
from build_servo_rear_fit_test import read_model
import prepare_bambu_latest as bambu
from print_packer import pack
from render_clamshell_detail import main as render

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / '.build/clamshell-detail/current-assembly'
CAD = ROOT / 'experiments/garden-auger-constraint-bushing-test.limo'
TEMPLATE = ROOT / 'garden-auger-bambu-latest.3mf'
TARGET = ROOT / 'garden-auger-current-assembly.3mf'
REPORT = ROOT / 'current-assembly-verification.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_zip(path, entries):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def put(node, key, value):
    found = node.find(f"metadata[@key='{key}']")
    if found is None:
        bambu.add_metadata(node, key, value)
    else:
        found.set('value', str(value))


def verify_stls(canonical):
    objects = ET.fromstring(bambu.read_zip(canonical)['3D/3dmodel.model']).findall('{*}resources/{*}object')
    rotations = [bambu.UPPER,bambu.I,bambu.I,bambu.UPRIGHT,bambu.UPRIGHT]
    checks = []
    for obj, rotation in zip([o for o in objects if o.find('{*}mesh') is not None],rotations):
        vertices, faces = bambu.mesh_arrays(obj)
        posed = vertices @ rotation.T
        posed -= posed.min(0)
        name = obj.get('name')
        path = ROOT/'print-parts/current-assembly'/(name.lower().replace(' - ','-').replace(' ','-')+'.stl')
        mesh = trimesh.load_mesh(path,process=False)
        expected = posed[faces]
        assert expected.shape == mesh.triangles.shape
        delta = float(np.abs(expected-mesh.triangles).max())
        assert delta < .00002, (name,delta)
        checks.append({'file':str(path.relative_to(ROOT)),'maximum_triangle_coordinate_difference_mm':delta,
            'native_mesh_and_print_orientation_match':True})
    assert len(checks)==5
    return checks


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    preserved = {str(p.relative_to(ROOT)): digest(p) for p in [TEMPLATE, CAD,
        ROOT/'garden-auger-upper-servo-sparse-test.3mf',
        ROOT/'garden-auger-lower-fit-test.3mf']}
    fit = json.loads((ROOT/'constraint-bushing-review.json').read_text())
    assert digest(CAD) == fit['cad_sha256'], 'Fit evidence is for a different CAD'
    result = {'cad': str(CAD.relative_to(ROOT)), 'cad_sha256': digest(CAD),
        'prior_fit_review': 'constraint-bushing-review.json',
        'prior_fit_review_sha256': digest(ROOT/'constraint-bushing-review.json'),
        'preserved_files': preserved, 'template_is_profiles_only': True,
        'printer_command_sent': False}
    with CadClient(stderr_path=BUILD/'native-engine.log') as client:
        client.call('cad_load_project_model', {'model_json': json.dumps(read_model(CAD))})
        scene = client.call('solid_scene')
        assert not scene['errors'], scene['errors']
        result['native_engine_sha256'] = digest(client.executable)
        check = client.call('assembly_interference_check', {
            'occurrence_ids': [3,6,7,8,14,16], 'clearance_threshold_mm': 2})
        assert check['exact'] and not any(p['interfering'] for p in check['pairs'])
        result['fresh_nominal_assembly'] = check
        preflight = client.call('solid_export_preflight', {'body_ids': [26,46,15,90,216,221]})
        assert preflight['ok'] and not preflight['timeline_errors']
        result['native_geometry_preflight'] = preflight
        raw = client.call('solid_export_3mf', {'body_ids': [26,46,15,90,216,221],
            'scope': 'definition', 'linear_deflection': .08,
            'angular_deflection': .2, 'slicer_target': 'standard'})
        native = BUILD/'native.3mf'
        native.write_bytes(base64.b64decode(raw['bytes_base64']))
        (BUILD/'scene.json').write_text(json.dumps(scene))
    canonical = BUILD/'five-current-parts.3mf'
    result['parts'] = pack(native, canonical,
        print_notes='Current rounded housing + constraint-fit bushing. Four PETG parts, one PLA bushing. All parts are from the current native CAD; purchased servo excluded.',
        individual_dir='print-parts/current-assembly')
    # Explicit current naming avoids confusing the replacement with the old
    # longer sleeve kept in the historical export directory.
    old_name, new_name = 'PLA - Full wear sleeve', 'PLA - Constraint-fit bushing'
    portable = bambu.read_zip(canonical)
    portable_model = ET.fromstring(portable['3D/3dmodel.model'])
    next(o for o in portable_model.findall('{*}resources/{*}object') if o.get('name')==old_name).set('name',new_name)
    portable['3D/3dmodel.model'] = ET.tostring(portable_model,encoding='utf-8',xml_declaration=True)
    write_zip(canonical,portable)
    old_stl = ROOT/'print-parts/current-assembly/pla-full-wear-sleeve.stl'
    old_stl.replace(old_stl.with_name('pla-constraint-fit-bushing.stl'))
    result['parts'][-1]['name'] = new_name
    # Reuse the saved profile/layout writer against the freshly exported CAD.
    # Its historical canonical export is never consulted here.
    shutil.copyfile(TEMPLATE, TARGET)
    # Adapt only this new package's labels before using the shared writer.
    template_entries = bambu.read_zip(TARGET)
    template_config = ET.fromstring(template_entries['Metadata/model_settings.config'])
    for node in template_config.iter('metadata'):
        if node.get('key')=='name' and node.get('value')==old_name: node.set('value',new_name)
    template_entries['Metadata/model_settings.config'] = ET.tostring(template_config,encoding='utf-8',xml_declaration=True)
    write_zip(TARGET,template_entries)
    bambu.EXPECTED_FILAMENT[new_name] = bambu.EXPECTED_FILAMENT.pop(old_name)
    bambu.PLATES[3] = ('PLA - Constraint-fit bushing',[(new_name,bambu.UPRIGHT,(110.,110.))])
    bambu.TARGET, bambu.CANONICAL = TARGET, canonical
    # The projecting dirt deflector lengthens each current half. Increase
    # spacing relative to the historical housing plate, retaining brim room.
    bambu.PLATES[0][1][1] = ('PETG - Housing lower', bambu.I, (28.,138.))
    bambu.build()
    entries = bambu.read_zip(TARGET)
    model, config, parts = bambu.project_parts(entries)
    result['mesh_identity_checks'] = bambu.geometry_checks(parts)
    settings = json.loads(entries['Metadata/project_settings.config'])
    original_settings = json.loads(bambu.read_zip(TEMPLATE)['Metadata/project_settings.config'])
    settings['filament_colour'] = ['#E5AE3C','#D57E37','#BEC3CA','#37AAA1']
    settings['print_settings_id'] = 'Current assembly - strong PETG and PLA bushing @BBL X2D'
    # Same four-wall bushing process as the separately validated replacement.
    for obj in config.findall('object'):
        info = bambu.metadata(obj)
        if info['name'].startswith('PETG - Housing'):
            # A native automatic-support comparison removes the cantilever
            # warning for the rounded housing. Sparse test files stay intact.
            put(obj, 'enable_support', 1)
        if info['name'] == new_name:
            for key, value in {'layer_height': '.20', 'wall_loops': 4,
                'sparse_infill_density': '15%', 'sparse_infill_pattern': 'grid',
                'top_shell_layers': 4, 'bottom_shell_layers': 4,
                'enable_support': 0}.items():
                put(obj, key, value)
        for sub in obj.iter('metadata'):
            if sub.get('key') == 'source_file':
                sub.set('value', str(CAD.relative_to(ROOT)))
    entries['Metadata/model_settings.config'] = ET.tostring(config, encoding='utf-8', xml_declaration=True)
    entries['Metadata/project_settings.config'] = json.dumps(settings, indent=2).encode()
    # Bambu's OPC loader requires the default relationship namespace.
    ET.register_namespace('', 'http://schemas.openxmlformats.org/package/2006/relationships')
    for name, data in list(entries.items()):
        if name.endswith('.rels'):
            rels = ET.fromstring(data)
            for rel in list(rels):
                if rel.get('Target','').lstrip('/') not in entries and rel.get('TargetMode') != 'External':
                    rels.remove(rel)
            entries[name] = ET.tostring(rels, encoding='utf-8', xml_declaration=True)
    items = {n.get('objectid'): n for n in model.findall('{*}build/{*}item')}
    by_id = {p['object_id']: (name,p) for name,p in parts.items()}
    result['plates'] = []
    assigned = []
    for index, plate in enumerate(config.findall('plate')):
        origin = np.array([(index%2)*307.2, -(index//2)*307.2, 0.])
        boxes = []
        names = []
        for instance in plate.findall('model_instance'):
            oid = bambu.metadata(instance)['object_id']
            name, part = by_id[oid]
            t = np.array(list(map(float, items[oid].get('transform').split())))
            assert np.allclose(t[:9].reshape(3,3) @ t[:9].reshape(3,3).T,np.eye(3))
            assert np.linalg.det(t[:9].reshape(3,3)) > .999999
            vertices = part['vertices'] @ t[:9].reshape(3,3) + t[9:] - origin
            box = np.array([vertices.min(0), vertices.max(0)])
            assert np.all(box[0] >= [-.001,-.001,-.001]) and np.all(box[1] <= [256,256,261])
            assert abs(box[0,2]) < .001
            boxes.append(box); names.append(name); assigned.append(oid)
        for a in range(len(boxes)):
            for b in range(a+1, len(boxes)):
                assert np.any((boxes[a][1,:2]+10 <= boxes[b][0,:2]) | (boxes[b][1,:2]+10 <= boxes[a][0,:2]))
        result['plates'].append({'plate': index+1, 'parts': names, 'bed_bounds_mm': [b.tolist() for b in boxes]})
    assert len(assigned) == len(set(assigned)) == 5
    for key in ['printer_settings_id','filament_type','filament_settings_id','nozzle_temperature']:
        assert settings[key] == original_settings[key], key
    result['printer_and_filament_profiles_preserved'] = True
    result['object_process_settings'] = [bambu.metadata(o) for o in config.findall('object')]
    result['global_layer_height_mm'] = settings['layer_height']
    result['support_settings'] = {k: settings[k] for k in ['enable_support','support_type','support_interface_filament','enable_prime_tower']}
    write_zip(TARGET, entries)
    print('Five current parts verified; native slicing all four plates...', flush=True)
    with (BUILD/'native-slice.log').open('w') as log:
        process = subprocess.run([r'C:/Program Files/Bambu Studio/bambu-studio.exe',
            '--slice','0','--export-3mf','sliced.3mf','--outputdir',str(BUILD),str(TARGET)],
            stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW, timeout=600)
    native_result = json.loads((BUILD/'result.json').read_text())
    assert process.returncode == native_result['return_code'] == 0, native_result
    assert len(native_result['sliced_plates']) == 4, native_result
    assert [p['id'] for p in native_result['sliced_plates']] == [1,2,3,4]
    sliced = bambu.read_zip(BUILD/'sliced.3mf')
    expected_filaments = [{1,4},{2,4},{3,4},{4}]
    expected_objects = [2,1,1,1]
    for plate, filaments, count in zip(native_result['sliced_plates'],expected_filaments,expected_objects):
        assert not plate['warning_message'], plate
        assert {f['id'] for f in plate['filaments']} == filaments
        assert len(plate['objects']) == count
        assert {o['name'] for o in plate['objects']} == set(result['plates'][plate['id']-1]['parts'])
        gcode = sliced[f"Metadata/plate_{plate['id']}.gcode"]
        roles = {s.decode() for s in re.findall(rb'^; FEATURE: ([^\r\n]+)',gcode,re.MULTILINE)}
        if plate['id']==4:
            assert not any('Sparse' in r or 'Support' in r or 'Prime tower' in r for r in roles)
        else:
            assert 'Support interface' in roles and 'Prime tower' in roles
        print('Native plate',plate['id'],round(plate['total_predication']/60,1),'minutes, no warnings',flush=True)
    baseline = BUILD/'support-free-housing-probe.json'
    if baseline.exists():
        result['support_comparison'] = json.loads(baseline.read_text())
    result['native_slice'] = native_result
    result['native_slice_archive_sha256'] = digest(BUILD/'sliced.3mf')
    # Deliver editable geometry/profile 3MF with fresh previews, no embedded
    # machine program. Native sliced evidence stays in the bounded build lane.
    entries.update({n:d for n,d in sliced.items() if re.match(r'Metadata/(?:plate(?:_no_light)?_|top_|pick_)\d+(?:_small)?\.png$',n)})
    entries['Metadata/slice_info.config'] = sliced['Metadata/slice_info.config']
    assert not any(n.endswith('.gcode') for n in entries)
    write_zip(TARGET, entries)
    result['project'] = TARGET.name
    result['project_sha256'] = digest(TARGET)
    result['embedded_gcode'] = False
    result['stl_geometry_checks'] = verify_stls(canonical)
    result['stls'] = {str(p.relative_to(ROOT)):digest(p) for p in sorted((ROOT/'print-parts/current-assembly').glob('*.stl'))}
    REPORT.write_text(json.dumps(result, indent=2)+'\n')
    assert all(digest(ROOT/p)==h for p,h in preserved.items())
    render(BUILD/'scene.json', ROOT/'renders/current-assembly', 'Current assembly | rounded housing and fitted bushing',
        'Curved side relief and grip rounds retain the fitted internal cavities and continuous bed floors')


if __name__ == '__main__':
    main()
