"""Remove object process overrides, use three global walls and verify native slicing.

Owned evidence: existing D project lane, 90 MiB ceiling; retain compressed slice
proof while this candidate is current. No CAD edits or printer commands.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'garden-auger-labeled-assembly.3mf'
TARGET = ROOT / 'garden-auger-three-wall-assembly.3mf'
REPORT = ROOT / 'three-wall-verification.json'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_zip(p):
    with zipfile.ZipFile(p) as z:
        return {n: z.read(n) for n in z.namelist()}


def write_zip(p, entries):
    with zipfile.ZipFile(p, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, data in entries.items():
            z.writestr(n, data)


def main():
    base = (ROOT / '.build/clamshell-detail/current-assembly/three-wall').resolve()
    base.mkdir(parents=True, exist_ok=True)
    lane = Path(tempfile.mkdtemp(prefix='slice-', dir=base))
    before = read_zip(SOURCE)
    source_hash = sha(SOURCE)
    entries = dict(before)
    settings = json.loads(entries['Metadata/project_settings.config'])
    settings['wall_loops'] = '3'
    settings['print_settings_id'] = 'Current assembly - global three walls @BBL X2D'
    config = ET.fromstring(entries['Metadata/model_settings.config'])
    removed = {}
    for obj in config.findall('object'):
        name = next(m.get('value') for m in obj.findall('metadata') if m.get('key') == 'name')
        removed[name] = {}
        for parent in [obj, *obj.findall('part')]:
            if parent.tag == 'part':
                assert parent.get('subtype') == 'normal_part', 'Unexpected modifier volume'
            for m in list(parent.findall('metadata')):
                key = m.get('key')
                if key in settings and key not in {'extruder', 'name'}:
                    removed[name][key] = m.get('value')
                    parent.remove(m)
        assert not obj.findall('layer_range')
    original_config = ET.fromstring(before['Metadata/model_settings.config'])
    for obj, original in zip(config.findall('object'), original_config.findall('object'), strict=True):
        metadata = lambda node: {m.get('key'): m.get('value') for m in node.findall('metadata') if m.get('key')}
        retained = metadata(obj)
        assert set(retained) == {'name', 'extruder'}, retained
        assert retained == {k: metadata(original)[k] for k in retained}
    assert [ET.tostring(p) for p in config.findall('plate')] == [ET.tostring(p) for p in original_config.findall('plate')]
    assert not any('layer_height_profile' in n or 'layer_config_ranges' in n for n in entries)
    entries['Metadata/project_settings.config'] = json.dumps(settings, indent=2).encode()
    entries['Metadata/model_settings.config'] = ET.tostring(config, encoding='utf-8', xml_declaration=True)
    # Invalidate cached slice evidence, preserving geometry, plate order and materials.
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
    print('Native slicing: ' + str(lane), flush=True)
    with (lane / 'native.log').open('w') as log:
        result = subprocess.run([r'C:/Program Files/Bambu Studio/bambu-studio.exe', '--slice', '0',
            '--export-3mf', 'sliced.3mf', '--outputdir', str(lane), str(staged)],
            stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW, timeout=600)
    native = json.loads((lane / 'result.json').read_text())
    assert result.returncode == 0 and native['return_code'] == 0, native
    plates = native['sliced_plates']
    assert len(plates) == 2 and [len(p['objects']) for p in plates] == [2, 3]
    assert not any(p['warning_message'] for p in plates)
    sliced = read_zip(lane / 'sliced.3mf')
    orders = []
    for i in [1, 2]:
        code = sliced[f'Metadata/plate_{i}.gcode'].decode()
        assert '; print_sequence = by object' in code
        assert '; wall_loops = 3' in code
        ids = re.findall(r'; start printing object, unique label id: (\d+)', code)
        runs = [x for j, x in enumerate(ids) if j == 0 or x != ids[j-1]]
        orders.append(runs)
        assert 'Prime tower' not in set(re.findall(r'^; FEATURE: ([^\r\n]+)', code, re.M))
        if i == 1:
            assert len(runs) == 2 and set(runs) == {'102', '104'}
        else:
            assert runs == ['106', '108', '110'], runs
            start = code.index('; start printing object, unique label id: 110')
            assert code.rindex('M190 S55') < start
            assert not re.search(r'^\s*M(?:140|190) S(?:[6-9][0-9]|[1-9][0-9]{2,})', code[start:], re.M)
    info = ET.fromstring(sliced['Metadata/slice_info.config'])
    assert all(next(m.get('value') for m in p.findall('metadata') if m.get('key') == 'outside') == 'false' for p in info.findall('plate'))
    entries.update({n: d for n, d in sliced.items() if preview(n) and n.endswith('.png')})
    entries['Metadata/slice_info.config'] = sliced['Metadata/slice_info.config']
    assert all(entries[n] == data for n, data in before.items() if n.startswith('3D/'))
    write_zip(TARGET, entries)
    report = {'project': TARGET.name, 'project_sha256': sha(TARGET), 'source': SOURCE.name,
        'source_sha256': source_hash, 'removed_object_overrides': removed,
        'global_process': {k: settings[k] for k in ['layer_height', 'wall_loops', 'sparse_infill_density',
            'sparse_infill_pattern', 'top_shell_layers', 'top_shell_thickness', 'bottom_shell_layers', 'enable_support', 'print_sequence']},
        'geometry_entries_byte_identical': True, 'material_assignments_and_layout_unchanged': True,
        'object_process_overrides_remaining': 0, 'native_slice': native, 'actual_orders': orders,
        'PLA_55C_bed_wait_verified': True, 'prime_tower_generated': False,
        'time_seconds': sum(p['total_predication'] for p in plates),
        'filament_g': sum(f['total_used_g'] for p in plates for f in p['filaments']),
        'sliced_archive_sha256': sha(lane / 'sliced.3mf'), 'evidence_directory': str(lane),
        'printer_command_sent': False, 'embedded_gcode': False,
        'scope': 'Native slice estimate; physical strength and print quality remain untested.'}
    assert sha(SOURCE) == source_hash
    REPORT.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ['time_seconds', 'filament_g', 'actual_orders', 'evidence_directory']}, indent=2), flush=True)


if __name__ == '__main__':
    main()
