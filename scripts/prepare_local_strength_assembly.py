"""Add approved local strength modifiers; preserve five print meshes and fits.

Owned evidence: existing D project lane, 90 MiB ceiling, retained while current
or needed to reproduce. No printer command is sent.
"""
import copy
import json
from pathlib import Path
import re
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET

import numpy as np
import trimesh

from cad_client import CadClient
from build_servo_rear_fit_test import read_model
from review_snug_servo_nest import native_cylinder
from prepare_three_wall_assembly import read_zip, write_zip, sha
import prepare_bambu_latest as b

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'garden-auger-three-wall-assembly.3mf'
TARGET = ROOT / 'garden-auger-local-strength-assembly.3mf'
REPORT = ROOT / 'local-strength-verification.json'
CAD = ROOT / 'experiments/garden-auger-labeled.limo'
CORE, PRODUCTION = b.CORE, b.PRODUCTION
LOCAL = {'wall_loops': '5', 'sparse_infill_density': '100%', 'sparse_infill_pattern': 'zig-zag'}
INSERTS = [(-27, 118.5), (27, 118.5), (-36, 196.8), (16, 196.8)]
LOCATORS = [(-21, 132), (21, 132), (-36, 183), (16, 175)]


def section_spans(body, z, y):
    """Cross native tessellation at Z, then intersect its boundary with Y."""
    vertices = np.array(body['mesh']['positions']).reshape(-1, 3)
    triangles = vertices[np.array(body['mesh']['indices']).reshape(-1, 3)]
    xs = []
    for tri in triangles:
        if tri[:, 2].min() >= z or tri[:, 2].max() <= z:
            continue
        points = []
        for p, q in zip(tri, np.roll(tri, -1, axis=0)):
            if min(p[2], q[2]) <= z < max(p[2], q[2]):
                points.append(p + (q-p)*(z-p[2])/(q[2]-p[2]))
        if len(points) == 2:
            p, q = points
            if min(p[1], q[1]) <= y < max(p[1], q[1]):
                xs.append(float(p[0]+(q[0]-p[0])*(y-p[1])/(q[1]-p[1])))
    xs = sorted(set(round(x, 6) for x in xs))
    assert len(xs) % 2 == 0, xs
    return list(zip(xs[::2], xs[1::2]))


def locator_review():
    records = []
    with CadClient() as c:
        c.call('cad_load_project_model', {'model_json': json.dumps(read_model(CAD))})
        scene = c.call('solid_scene')
        assert not scene['errors']
        bodies = {v['id']: v for v in scene['bodies']}
        for x, y in LOCATORS:
            for body in [26, 46]:
                native_cylinder(bodies[body], 2.5, axis=2, location={'x': x, 'y': y})
            spans = section_spans(bodies[26], 1., y)
            left = next(b-a for a, b in spans if abs(b-(x-2.5)) < .02)
            right = next(b-a for a, b in spans if abs(a-(x+2.5)) < .02)
            assert min(left, right) >= 2.58
            records.append({'center_xy_mm': [x, y], 'pin_diameter_mm': 5., 'socket_diameter_mm': 5.,
                            'pin_projection_mm': 2.8, 'section_z_mm': 1., 'socket_left_stock_mm': left, 'socket_right_stock_mm': right})
        engine = sha(c.executable)
    return {'cad_sha256': sha(CAD), 'engine_sha256': engine, 'records': records,
            'fit': 'Matched zero nominal diametral clearance retained; no relieved/slotted locator changes.',
            'scope': 'Exact native cylindrical faces plus selected tessellated socket-wall sections; dimensions unchanged.',
            'section_limitation': 'Exact labeled-body XY section exceeds native plane-common budget; native mesh sections used for stock measurements, 0.02 mm comparison allowance.'}


def add_modifiers(entries):
    model, config, parts = b.project_parts(entries)
    original_config = copy.deepcopy(config)
    resources = model.find('{*}resources')
    mesh_model = ET.Element(f'{{{CORE}}}model', {'unit': 'millimeter'})
    mesh_resources = ET.SubElement(mesh_model, f'{{{CORE}}}resources')
    path = '3D/Objects/local_reinforcement.model'
    zones, definitions = [], []
    for x, y in INSERTS:
        definitions += [('PETG - Housing lower', f'Insert anchor {x},{y}', (x, y, -4.45), 6., 9.1, 'z'),
                        ('PETG - Housing upper', f'Screw load path {x},{y}', (x, y, 8.4), 6., 17.2, 'z')]
    definitions += [('PETG - Square adapter', 'Adapter hub and screw seat', (0, 145.5, 0), 14.1, 14., 'y')]
    for number, (name, label, center, radius, length, axis) in enumerate(definitions, 101):
        part = parts[name]
        obj_config = next(o for o in config.findall('object') if o.get('id') == part['object_id'])
        source_part = obj_config.find('part')
        offset = np.array([float(b.metadata(source_part)[f'source_offset_{a}']) for a in 'xyz'])
        mesh = trimesh.creation.cylinder(radius=radius, height=length, sections=48)
        if axis == 'y':
            mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [1, 0, 0]))
        mesh.apply_translation(np.array(center)-offset)
        assert mesh.is_watertight and mesh.is_volume
        obj = ET.SubElement(mesh_resources, f'{{{CORE}}}object', {'id': str(number), 'type': 'model'})
        node = ET.SubElement(obj, f'{{{CORE}}}mesh')
        verts, faces = ET.SubElement(node, f'{{{CORE}}}vertices'), ET.SubElement(node, f'{{{CORE}}}triangles')
        for v in mesh.vertices:
            ET.SubElement(verts, f'{{{CORE}}}vertex', dict(zip('xyz', [f'{q:.10g}' for q in v])))
        for f in mesh.faces:
            ET.SubElement(faces, f'{{{CORE}}}triangle', dict(zip(('v1', 'v2', 'v3'), [str(int(q)) for q in f])))
        wrapper = next(o for o in resources.findall('{*}object') if o.get('id') == part['object_id'])
        ET.SubElement(wrapper.find('{*}components'), f'{{{CORE}}}component', {
            f'{{{PRODUCTION}}}path': '/'+path, 'objectid': str(number), f'{{{PRODUCTION}}}UUID': str(uuid.uuid4()),
            'transform': '1 0 0 0 1 0 0 0 1 0 0 0'})
        modifier = ET.SubElement(obj_config, 'part', {'id': str(number), 'subtype': 'modifier_part'})
        for k, v in {'name': label, **LOCAL}.items():
            b.add_metadata(modifier, k, v)
        ET.SubElement(modifier, 'mesh_stat', {'face_count': str(len(mesh.faces)), 'edges_fixed': '0',
            'degenerate_facets': '0', 'facets_removed': '0', 'facets_reversed': '0', 'backwards_edges': '0'})
        zones.append({'part': name, 'name': label, 'mesh_id': number, 'center_cad_mm': center,
                      'radius_mm': radius, 'length_mm': length, 'axis': axis, 'process': LOCAL})
    for a, old in zip(config.findall('object'), original_config.findall('object'), strict=True):
        assert ET.tostring(a.find('part')) == ET.tostring(old.find('part'))
        assert b.metadata(a) == b.metadata(old)
    assert [ET.tostring(p) for p in config.findall('plate')] == [ET.tostring(p) for p in original_config.findall('plate')]
    entries[path] = ET.tostring(mesh_model, encoding='utf-8', xml_declaration=True)
    entries['3D/3dmodel.model'] = ET.tostring(model, encoding='utf-8', xml_declaration=True)
    entries['Metadata/model_settings.config'] = ET.tostring(config, encoding='utf-8', xml_declaration=True)
    rel_path = '3D/_rels/3dmodel.model.rels'
    rels = ET.fromstring(entries[rel_path])
    rel_ns = 'http://schemas.openxmlformats.org/package/2006/relationships'
    ET.SubElement(rels, f'{{{rel_ns}}}Relationship', {'Target': '/'+path, 'Id': 'local_strength',
        'Type': 'http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel'})
    ET.register_namespace('', rel_ns)
    entries[rel_path] = ET.tostring(rels, encoding='utf-8', xml_declaration=True)
    return zones


def verify_local_paths(original, zones, sliced):
    """Measure emitted extrusion inside each requested zone against baseline."""
    model, config, parts = b.project_parts(original)
    items = {q.get('objectid'): q for q in model.find('{*}build')}
    plate_of = {b.metadata(i)['object_id']: int(b.metadata(p)['plater_id'])
                for p in config.findall('plate') for i in p.findall('model_instance')}
    placed = []
    for zone in zones:
        part = parts[zone['part']]
        obj = next(q for q in config.findall('object') if q.get('id') == part['object_id'])
        offset = np.array([float(b.metadata(obj.find('part'))[f'source_offset_{a}']) for a in 'xyz'])
        transform = np.array([float(v) for v in items[part['object_id']].get('transform').split()])
        plate = plate_of[part['object_id']]
        center = (np.array(zone['center_cad_mm'])-offset) @ transform[:9].reshape(3, 3) + transform[9:]
        center[0] -= (plate-1)*307.2
        placed.append({**zone, 'plate': plate, 'label': str(100+int(part['object_id'])), 'print_center': center})

    def measure(archive):
        values = [{'filament_mm': 0., 'moves': 0, 'roles': {}} for _ in placed]
        for plate in [1, 2]:
            x = y = z = e_position = 0.
            relative = True
            active, role = None, None
            for line in archive[f'Metadata/plate_{plate}.gcode'].decode().splitlines():
                if line.startswith('; FEATURE: '):
                    role = line.removeprefix('; FEATURE: ').strip()
                if '; start printing object, unique label id:' in line:
                    active = line.rsplit(':', 1)[1].strip()
                if line.startswith('M83'):
                    relative = True
                elif line.startswith('M82'):
                    relative = False
                command = line.split(';', 1)[0].strip()
                if not command.startswith(('G0 ', 'G1 ', 'G92 ')):
                    continue
                fields = {k: float(v) for k, v in re.findall(r'([XYZE])(-?(?:\d+(?:\.\d*)?|\.\d+))', command)}
                if command.startswith('G92 '):
                    e_position = fields.get('E', e_position)
                    continue
                nx, ny, nz = fields.get('X', x), fields.get('Y', y), fields.get('Z', z)
                amount = fields.get('E', 0.) if relative else fields.get('E', e_position)-e_position
                e_position = fields.get('E', e_position)
                if amount > 0 and (nx != x or ny != y) and active:
                    mx, my = (x+nx)/2, (y+ny)/2
                    for index, zone in enumerate(placed):
                        cx, cy, cz = zone['print_center']
                        if (plate == zone['plate'] and active == zone['label'] and
                            abs(nz-cz) < zone['length_mm']/2-.2 and
                            (mx-cx)**2+(my-cy)**2 < (zone['radius_mm']-.15)**2):
                            value = values[index]
                            value['filament_mm'] += amount
                            value['moves'] += 1
                            value['roles'][role] = value['roles'].get(role, 0.)+amount
                x, y, z = nx, ny, nz
        return values

    prior = json.loads((ROOT/'three-wall-verification.json').read_text())
    baseline = read_zip(Path(prior['evidence_directory'])/'sliced.3mf')
    assert sha(Path(prior['evidence_directory'])/'sliced.3mf') == prior['sliced_archive_sha256']
    old, new = measure(baseline), measure(sliced)
    assert all(q['filament_mm'] > 0 for q in new), new
    assert sum(q['filament_mm'] for q in new) > sum(q['filament_mm'] for q in old)
    return [{'name': zone['name'], 'part': zone['part'], 'baseline': a, 'reinforced': d}
            for zone, a, d in zip(zones, old, new, strict=True)]


def main():
    base = (ROOT / '.build/clamshell-detail/current-assembly/local-strength').resolve()
    base.mkdir(parents=True, exist_ok=True)
    lane = Path(tempfile.mkdtemp(prefix='slice-', dir=base))
    locators = locator_review()
    print('Matched chunky locators: native diameter and socket walls pass', flush=True)
    original = read_zip(SOURCE)
    entries = dict(original)
    zones = add_modifiers(entries)
    assert all(entries[n] == data for n, data in original.items() if n.startswith('3D/Objects/'))
    assert entries['Metadata/project_settings.config'] == original['Metadata/project_settings.config']
    preview = lambda n: bool(re.match(r'Metadata/(?:plate(?:_no_light)?_|top_|pick_)\d+', n))
    entries = {n: d for n, d in entries.items() if not preview(n) and not n.endswith('.gcode')}
    old = ET.fromstring(entries['Metadata/slice_info.config'])
    for node in list(old):
        if node.tag != 'header':
            old.remove(node)
    entries['Metadata/slice_info.config'] = ET.tostring(old, encoding='utf-8', xml_declaration=True)
    ET.register_namespace('', 'http://schemas.openxmlformats.org/package/2006/relationships')
    for n, data in list(entries.items()):
        if n.endswith('.rels'):
            rels = ET.fromstring(data)
            for rel in list(rels):
                if rel.get('Target', '').lstrip('/') not in entries and rel.get('TargetMode') != 'External':
                    rels.remove(rel)
            entries[n] = ET.tostring(rels, encoding='utf-8', xml_declaration=True)
    staged = lane / 'input.3mf'
    write_zip(staged, entries)
    print('Native slicing '+str(lane), flush=True)
    with (lane / 'native.log').open('w') as log:
        process = subprocess.run([r'C:/Program Files/Bambu Studio/bambu-studio.exe', '--slice', '0', '--export-3mf',
            'sliced.3mf', '--outputdir', str(lane), str(staged)], stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=600)
    native = json.loads((lane / 'result.json').read_text())
    assert process.returncode == 0 and native['return_code'] == 0, native
    assert len(native['sliced_plates']) == 2
    assert [len(p['objects']) for p in native['sliced_plates']] == [2, 3]
    assert not any(p['warning_message'] for p in native['sliced_plates'])
    sliced = read_zip(lane / 'sliced.3mf')
    roundtrip = ET.fromstring(sliced['Metadata/model_settings.config'])
    mods = roundtrip.findall("object/part[@subtype='modifier_part']")
    assert len(mods) == 9
    assert {b.metadata(v)['name'] for v in mods} == {z['name'] for z in zones}
    assert all(all(b.metadata(m)[k] == v for k, v in LOCAL.items()) for m in mods)
    orders = []
    for i in [1, 2]:
        code = sliced[f'Metadata/plate_{i}.gcode'].decode()
        assert '; print_sequence = by object' in code and '; wall_loops = 3' in code
        ids = re.findall(r'; start printing object, unique label id: (\d+)', code)
        orders.append([x for j, x in enumerate(ids) if j == 0 or x != ids[j-1]])
        assert '; FEATURE: Prime tower' not in code
        if i == 2:
            assert orders[-1] == ['106', '108', '110']
            start = code.index('; start printing object, unique label id: 110')
            assert code.rindex('M190 S55') < start
            assert not re.search(r'^\s*M(?:140|190) S(?:[6-9][0-9]|[1-9][0-9]{2,})', code[start:], re.M)
    assert orders[0] == ['102', '104']
    path_checks = verify_local_paths(original, zones, sliced)
    entries.update({n: d for n, d in sliced.items() if preview(n) and n.endswith('.png')})
    entries['Metadata/slice_info.config'] = sliced['Metadata/slice_info.config']
    write_zip(TARGET, entries)
    report = {'project': TARGET.name, 'project_sha256': sha(TARGET), 'source': SOURCE.name, 'source_sha256': sha(SOURCE),
        'normal_print_meshes_byte_identical': True, 'global_process_byte_identical': True,
        'no_object_wide_strength_overrides': True, 'modifiers': zones, 'native_modifiers_roundtrip_verified': True,
        'native_slice': native, 'actual_orders': orders, 'locator_review': locators,
        'emitted_local_path_comparison': path_checks,
        'owner_confirmed_drive_connection': {'date': '2026-11-05', 'status': 'complete',
            'source': 'Owner: "3 this is proven, mark this as complete"',
            'scope': 'Servo-to-adapter connection accepted as proven by the owner; no new numerical torque rating inferred.'},
        'prior_interference_evidence': {'path': 'assembly-plate-recheck.json', 'sha256': sha(ROOT/'assembly-plate-recheck.json'),
            'scope': 'Same CAD and normal print meshes; modifiers alter toolpaths only.'},
        'time_seconds': sum(p['total_predication'] for p in native['sliced_plates']),
        'filament_g': sum(f['total_used_g'] for p in native['sliced_plates'] for f in p['filaments']),
        'evidence_directory': str(lane), 'sliced_archive_sha256': sha(lane/'sliced.3mf'),
        'printer_command_sent': False, 'embedded_gcode': False,
        'scope': 'Local reinforcement sliced and located; mechanical strength not numerically rated.'}
    REPORT.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in ['time_seconds', 'filament_g', 'evidence_directory']}, indent=2), flush=True)


if __name__ == '__main__':
    main()
