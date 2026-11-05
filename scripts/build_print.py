"""Apply the public reinforcement example to the saved Bambu project.

Python standard library only. Optional local slicing never contacts a printer.
The .limo model owns geometry; reinforcement.json owns these external zones.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CORE = 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
PRODUCTION = 'http://schemas.microsoft.com/3dmanufacturing/production/2015/06'
OPC = 'http://schemas.openxmlformats.org/package/2006/relationships'


def read_zip(path):
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        return {n: z.read(n) for n in z.namelist()}


def write_zip(path, entries):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, data in entries.items():
            z.writestr(n, data)


def metadata(node):
    return {q.get('key'): q.get('value') for q in node.findall('metadata') if q.get('key')}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def cylinder(zone, offset):
    count = 48
    r, h = zone['radius_mm'], zone['height_mm']
    assert r > 0 and h > 0 and zone['axis'] in ['z', 'y']
    points = [(r*math.cos(i*2*math.pi/count), r*math.sin(i*2*math.pi/count), z)
              for z in [-h/2, h/2] for i in range(count)] + [(0, 0, -h/2), (0, 0, h/2)]
    result = []
    for x, y, z in points:
        if zone['axis'] == 'y':
            x, y, z = x, -z, y
        result.append([v+c-o for v, c, o in zip((x, y, z), zone['center_mm'], offset)])
    faces = []
    for i in range(count):
        j = (i+1) % count
        faces += [(i, j, count+j), (i, count+j, count+i), (2*count, j, i), (2*count+1, count+i, count+j)]
    return result, faces


def build(source, spec):
    entries = read_zip(source)
    original = dict(entries)
    model = ET.fromstring(entries['3D/3dmodel.model'])
    config = ET.fromstring(entries['Metadata/model_settings.config'])
    resources = {q.get('id'): q for q in model.find('{*}resources')}
    normals = {}
    for obj in config.findall('object'):
        modifiers = obj.findall("part[@subtype='modifier_part']")
        old_ids = {q.get('id') for q in modifiers}
        components = resources[obj.get('id')].find('{*}components')
        for q in list(components):
            if q.get('objectid') in old_ids:
                components.remove(q)
        for q in modifiers:
            obj.remove(q)
        normal = obj.find("part[@subtype='normal_part']")
        assert normal is not None and len(list(components)) == 1
        normal.find("metadata[@key='source_file']").set('value', 'garden-auger.limo')
        normals[metadata(obj)['name']] = (obj, normal, components)
    assert len(normals) == 5
    path = '3D/Objects/local_reinforcement.model'
    mod_model = ET.Element(f'{{{CORE}}}model', {'unit': 'millimeter'})
    mod_resources = ET.SubElement(mod_model, f'{{{CORE}}}resources')
    for number, zone in enumerate(spec['zones'], 101):
        obj, normal, components = normals[zone['part']]
        offset = [float(metadata(normal)[f'source_offset_{a}']) for a in 'xyz']
        points, triangles = cylinder(zone, offset)
        record = ET.SubElement(mod_resources, f'{{{CORE}}}object', {'id': str(number), 'type': 'model'})
        mesh = ET.SubElement(record, f'{{{CORE}}}mesh')
        vertices, faces = ET.SubElement(mesh, f'{{{CORE}}}vertices'), ET.SubElement(mesh, f'{{{CORE}}}triangles')
        for point in points:
            ET.SubElement(vertices, f'{{{CORE}}}vertex', dict(zip('xyz', [f'{v:.10g}' for v in point])))
        for face in triangles:
            ET.SubElement(faces, f'{{{CORE}}}triangle', dict(zip(('v1', 'v2', 'v3'), map(str, face))))
        ident = str(uuid.uuid5(uuid.NAMESPACE_URL, 'garden-auger/'+zone['name']))
        ET.SubElement(components, f'{{{CORE}}}component', {f'{{{PRODUCTION}}}path': '/'+path,
            'objectid': str(number), f'{{{PRODUCTION}}}UUID': ident, 'transform': '1 0 0 0 1 0 0 0 1 0 0 0'})
        part = ET.SubElement(obj, 'part', {'id': str(number), 'subtype': 'modifier_part'})
        for key, value in {'name': zone['name'], **spec['local']}.items():
            ET.SubElement(part, 'metadata', {'key': key, 'value': value})
        ET.SubElement(part, 'mesh_stat', {'face_count': str(len(triangles)), 'edges_fixed': '0',
            'degenerate_facets': '0', 'facets_removed': '0', 'facets_reversed': '0', 'backwards_edges': '0'})
    ET.register_namespace('', CORE)
    ET.register_namespace('p', PRODUCTION)
    entries[path] = ET.tostring(mod_model, encoding='utf-8', xml_declaration=True)
    entries['3D/3dmodel.model'] = ET.tostring(model, encoding='utf-8', xml_declaration=True)
    entries['Metadata/model_settings.config'] = ET.tostring(config, encoding='utf-8', xml_declaration=True)
    settings = json.loads(entries['Metadata/project_settings.config'])
    settings.update(spec['global'])
    entries['Metadata/project_settings.config'] = json.dumps(settings, indent=2).encode()
    assert all(entries[n] == data for n, data in original.items()
               if n.startswith('3D/Objects/') and n != path)
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'print/garden-auger.3mf')
    parser.add_argument('--output', type=Path, default=ROOT/'print/garden-auger.3mf')
    parser.add_argument('--slicer', type=Path, help='Optional installed Bambu Studio executable; slices both plates locally.')
    parser.add_argument('--evidence', type=Path, default=ROOT/'.build/print')
    args = parser.parse_args()
    spec = json.loads((ROOT/'print/reinforcement.json').read_text())
    entries = build(args.source, spec)
    preview = lambda n: bool(re.match(r'Metadata/(?:plate(?:_no_light)?_|top_|pick_)\d+', n))
    entries = {n: d for n, d in entries.items() if not preview(n) and not n.endswith('.gcode')}
    info = ET.fromstring(entries['Metadata/slice_info.config'])
    for node in list(info):
        if node.tag != 'header':
            info.remove(node)
    entries['Metadata/slice_info.config'] = ET.tostring(info, encoding='utf-8', xml_declaration=True)
    ET.register_namespace('', OPC)
    for name, data in list(entries.items()):
        if name.endswith('.rels'):
            rels = ET.fromstring(data)
            for rel in list(rels):
                if rel.get('Target', '').lstrip('/') not in entries and rel.get('TargetMode') != 'External':
                    rels.remove(rel)
            entries[name] = ET.tostring(rels, encoding='utf-8', xml_declaration=True)
    if args.slicer:
        args.evidence.mkdir(parents=True, exist_ok=True)
        lane = Path(tempfile.mkdtemp(prefix='slice-', dir=args.evidence.resolve()))
        write_zip(lane/'input.3mf', entries)
        with (lane/'native.log').open('w') as log:
            result = subprocess.run([str(args.slicer.resolve()), '--slice', '0', '--export-3mf', 'sliced.3mf',
                '--outputdir', str(lane), str(lane/'input.3mf')], stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=600)
        native = json.loads((lane/'result.json').read_text())
        assert result.returncode == 0 and native['return_code'] == 0, native
        assert [len(p['objects']) for p in native['sliced_plates']] == [2, 3]
        assert not any(p['warning_message'] for p in native['sliced_plates'])
        sliced = read_zip(lane/'sliced.3mf')
        mods = ET.fromstring(sliced['Metadata/model_settings.config']).findall("object/part[@subtype='modifier_part']")
        assert {metadata(p)['name'] for p in mods} == {z['name'] for z in spec['zones']}
        assert all(all(metadata(p)[k] == v for k, v in spec['local'].items()) for p in mods)
        for i, expected in [(1, ['102', '104']), (2, ['106', '108', '110'])]:
            code = sliced[f'Metadata/plate_{i}.gcode'].decode()
            ids = re.findall(r'; start printing object, unique label id: (\d+)', code)
            assert [v for j, v in enumerate(ids) if j == 0 or v != ids[j-1]] == expected
            assert '; print_sequence = by object' in code and '; wall_loops = 3' in code
            assert '; FEATURE: Prime tower' not in code
            if i == 2:
                assert code.rindex('M190 S55') < code.index('; start printing object, unique label id: 110')
        entries.update({n: d for n, d in sliced.items() if preview(n) and n.endswith('.png')})
        entries['Metadata/slice_info.config'] = sliced['Metadata/slice_info.config']
        summary = {'seconds': sum(p['total_predication'] for p in native['sliced_plates']),
                   'grams': sum(f['total_used_g'] for p in native['sliced_plates'] for f in p['filaments']),
                   'modifiers': len(mods), 'printer_command_sent': False}
        (lane/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
        print(json.dumps(summary))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_zip(args.output, entries)
    print(str(args.output))


if __name__ == '__main__':
    main()
