"""Make and natively slice one low-material copy of the reviewed lower half.

Global draft settings replace the strength defaults. Remove conflicting
object overrides so Bambu's Global controls work on this single-part test.
Geometry, bed placement, printer and filament profiles remain unchanged.
"""
import hashlib
import json
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from cad_client import CadClient
from check_housing_print import slice_native

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'garden-auger-lower-servo-snug-test.3mf'
TARGET = ROOT/'garden-auger-lower-servo-sparse-test.3mf'
REPORT = ROOT/'servo-sparse-print-verification.json'
SETTINGS = {
    'layer_height':'0.28', 'line_width':'0.50',
    'initial_layer_line_width':'0.50', 'outer_wall_line_width':'0.50',
    'inner_wall_line_width':'0.50', 'sparse_infill_line_width':'0.50',
    'internal_solid_infill_line_width':'0.50', 'top_surface_line_width':'0.50',
    'wall_loops':'2', 'sparse_infill_density':'5%',
    'sparse_infill_pattern':'rectilinear', 'top_shell_layers':'3',
    'bottom_shell_layers':'3', 'top_shell_thickness':'0', 'bottom_shell_thickness':'0',
    'enable_support':'0', 'support_filament':'0', 'support_interface_filament':'0',
    'enable_prime_tower':'0',
    'print_settings_id':'0.28mm Sparse Servo Fit Test @BBL X2D',
}


def read_zip(path):
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        return {n:z.read(n) for n in z.namelist()}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_zip(path, entries):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for n,data in entries.items():
            z.writestr(n,data)


def main():
    reviewed=json.loads((ROOT/'servo-snug-review.json').read_text())
    source_hash=digest(SOURCE)
    assert source_hash==reviewed['print_checks']['test_sha256'], 'Not the reviewed geometry'
    before=read_zip(SOURCE)
    entries=dict(before)
    settings=json.loads(entries['Metadata/project_settings.config'])
    old_settings={k:settings.get(k) for k in SETTINGS}
    settings.update(SETTINGS)
    entries['Metadata/project_settings.config']=json.dumps(settings,indent=2).encode()
    config=ET.fromstring(entries['Metadata/model_settings.config'])
    objects=config.findall('object')
    assert len(objects)==1
    removed={}
    for m in list(objects[0].findall('metadata')):
        if m.get('key') in SETTINGS:
            removed[m.get('key')]=m.get('value')
            objects[0].remove(m)
    for m in config.findall("plate/metadata[@key='plater_name']"):
        m.set('value','PETG - Snug servo fit - SPARSE lower half')
    entries['Metadata/model_settings.config']=ET.tostring(config,encoding='utf-8',xml_declaration=True)
    # Observed Bambu loader compatibility: use unprefixed OPC relationships.
    # Normalize their spelling; targets and geometry remain unchanged.
    ET.register_namespace('', 'http://schemas.openxmlformats.org/package/2006/relationships')
    for n,data in list(entries.items()):
        if n.endswith('.rels'):
            entries[n]=ET.tostring(ET.fromstring(data),encoding='utf-8',xml_declaration=True)
    # Cached slices and pictures belonged to the strong test profile.
    entries={n:d for n,d in entries.items() if not n.endswith('.gcode')
        and not (n.startswith('Metadata/') and n.endswith('.png'))}
    entries['Metadata/servo-sparse-fit-test.txt']=(
        'ONE LOWER HALF - DIMENSIONAL FIT TEST. Same reviewed snug-nest mesh. '
        '0.28 mm layers (0.20 first layer), 0.50 mm lines, 2 walls, '
        '5% rectilinear infill, 3 top/bottom layers. Supports and prime tower off. '
        'Strength overrides removed so Global edits apply. PETG/profile and bed placement retained. '
        'Native slice checked locally; no printer command sent. This is a fit test, not a load-qualified part.').encode()
    base=ROOT/'.build/sparse-servo-test'
    base.mkdir(parents=True,exist_ok=True)
    output=Path(tempfile.mkdtemp(prefix='slice-',dir=base))
    exported,native=slice_native(entries,output)
    gcode=exported['Metadata/plate_1.gcode']
    roles=re.findall(rb'^; FEATURE: ([^\r\n]+)',gcode,re.MULTILINE)
    assert not any(b'Prime' in role or b'Wipe' in role for role in roles), set(roles)
    refreshed={n:d for n,d in exported.items() if
        re.match(r'Metadata/(?:plate(?:_no_light)?_|top_|pick_)\d+(?:_small)?\.png$',n)}
    refreshed['Metadata/slice_info.config']=exported['Metadata/slice_info.config']
    final={**entries,**refreshed}
    write_zip(TARGET,final)
    after=read_zip(TARGET)
    assert all(after[n]==d for n,d in before.items() if n.startswith('3D/') and n.endswith('.model'))
    assert all(after[n]==d for n,d in entries.items() if n not in refreshed)
    assert not any(n.endswith('.gcode') for n in after)
    assert digest(SOURCE)==source_hash
    # Use the application's native project inspector as well as its slicer.
    import base64
    with CadClient() as c:
        try:
            inspection=c.call('bambu_template_inspect', {
                'template_base64':base64.b64encode(TARGET.read_bytes()).decode()})
        except RuntimeError as error:
            if 'Selected template process pattern is outside the initial typed print-intent capability' not in str(error):
                raise
            inspection={'status':'unsupported_by_Limo_typed_print_intent',
                'tool_error':str(error),'native_Bambu_slice_succeeded':True}
    saved=json.loads(after['Metadata/project_settings.config'])
    assert all(saved[k]==v for k,v in SETTINGS.items())
    saved_config=ET.fromstring(after['Metadata/model_settings.config'])
    assert len(saved_config.findall('object'))==1
    assert not any(m.get('key') in SETTINGS for m in saved_config.findall('object/metadata'))
    plate=native['native_plate']
    report={'source':SOURCE.name,'source_sha256':source_hash,'test':TARGET.name,
        'test_sha256':digest(TARGET),'geometry_and_bed_transforms_byte_identical':True,
        'test_settings':SETTINGS,'previous_global_values':old_settings,
        'removed_object_overrides':removed,'object_uses_global_strength_settings':True,
        'opc_relationships_normalized_for_bambu':True,
        'native_bambu_inspection':inspection,'native_slice':native,
        'gcode_feature_roles':sorted({r.decode() for r in roles}),
        'time_seconds':plate['total_predication'],
        'filament_weight_g':sum(f['total_used_g'] for f in plate['filaments']),
        'native_run_directory':str(output.relative_to(ROOT)),
        'preview_and_slice_statistics_refreshed':True,'final_project_gcode_embedded':False,
        'printer_command_sent':False,'ui_control':'Windows Computer Use native pipe unavailable',
        'scope':'Low-material dimensional fit test. Native slicing does not certify manufactured dimensions, sparse-skin bridging or loaded strength.'}
    REPORT.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['test','time_seconds','filament_weight_g',
        'geometry_and_bed_transforms_byte_identical','object_uses_global_strength_settings']},indent=2),flush=True)


if __name__=='__main__':
    main()
