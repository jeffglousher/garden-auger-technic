"""Native Bambu proof for the single-half release and automatic-support probe.

Reads actual slicer roles/times; no inferred CAD overhang or bridge certificate.
Runs locally and sends no printer commands.
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
SLICER = Path(r'C:/Program Files/Bambu Studio/bambu-studio.exe')


def read_zip(path):
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        return {n:z.read(n) for n in z.namelist()}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def slice_native(entries, output, filament_ids=('1',)):
    staged = output/'input.3mf'
    with zipfile.ZipFile(staged,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in entries.items():
            if not(name.startswith('Metadata/') and name.endswith('.png')):
                z.writestr(name,data)
    with (output/'native.log').open('w') as log:
        process = subprocess.run([str(SLICER),'--slice','0','--export-3mf','sliced.3mf',
            '--outputdir',str(output),str(staged)],stdout=log,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,timeout=300)
    result = json.loads((output/'result.json').read_text())
    assert process.returncode == 0 and result['return_code'] == 0,result
    exported = read_zip(output/'sliced.3mf')
    gcode = exported['Metadata/plate_1.gcode']
    markers = re.findall(rb'^; FEATURE: Support[^\r\n]*',gcode,re.MULTILINE)
    native = result['sliced_plates'][0]
    support_time = sum(v for k,v in native['feature_type_times'].items() if 'Support' in k)
    assert support_time == 0 and not markers,native
    assert {str(f['id']) for f in native['filaments']} == set(map(str,filament_ids)),native
    return exported,{'native_exit_code':process.returncode,'native_plate':native,
        'support_time_seconds':support_time,'support_gcode_feature_markers':len(markers),
        'gcode_sha256':hashlib.sha256(gcode).hexdigest(),
        'sliced_archive_sha256':digest(output/'sliced.3mf')}


def main():
    folder = ROOT/'.build/support-free/qualification'
    folder.mkdir(parents=True,exist_ok=True)
    source = ROOT/'garden-auger-lower-fit-test.3mf'
    entries = read_zip(source)
    config = ET.fromstring(entries['Metadata/model_settings.config'])
    objects = config.findall('object')
    assert len(objects)==1
    metadata = {m.get('key'):m.get('value') for m in objects[0].findall('metadata')}
    assert metadata['name']=='PETG - Housing lower'
    assert metadata['enable_support']=='0'
    output=Path(tempfile.mkdtemp(prefix='release-',dir=folder))
    exported,release = slice_native(entries,output)
    refreshed={n:d for n,d in exported.items() if
        re.match(r'Metadata/(?:plate(?:_no_light)?_|top_|pick_)\d+(?:_small)?\.png$',n)}
    refreshed['Metadata/slice_info.config']=exported['Metadata/slice_info.config']
    final={**entries,**refreshed}
    assert not any(n.endswith('.gcode') for n in final)
    with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED) as z:
        for n,d in final.items():z.writestr(n,d)
    # Independent probe: permit native automatic supports on this SAME mesh.
    # This distinguishes geometry improvement from hiding supports in settings.
    automatic=dict(entries)
    objects[0].find("metadata[@key='enable_support']").set('value','1')
    automatic['Metadata/model_settings.config']=ET.tostring(config,encoding='utf-8',xml_declaration=True)
    settings=json.loads(automatic['Metadata/project_settings.config'])
    assert settings['enable_support']=='1'
    assert all(automatic[n]==entries[n] for n in entries if n.startswith('3D/'))
    auto_output=Path(tempfile.mkdtemp(prefix='automatic-',dir=folder))
    _,probe=slice_native(automatic,auto_output)
    proof={'source_project':'garden-auger-direct-drive.nbcad',
        'source_project_sha256':digest(ROOT/'garden-auger-direct-drive.nbcad'),
        'test_project':source.name,'test_project_sha256':digest(source),
        'full_project':'garden-auger-bambu-latest.3mf',
        'full_project_sha256':digest(ROOT/'garden-auger-bambu-latest.3mf'),
        'single_half_release':release,'automatic_support_lower_probe':probe,
        'probe_meshes_byte_identical_to_release':True,
        'saved_global_printer_material_process_and_purge_settings_identical':True,
        'method':'Bambu Studio native CLI, actual feature times/materials and emitted G-code roles.',
        'limits':['The upper screw-recess roofs remain short unsupported bridges; verify printed quality physically.',
            'No automatic global CAD wall-thickness, GD&T, bridge-quality or loaded-strength certification.',
            'Native support_used metadata can reflect enabled global settings despite zero support extrusion.']}
    (ROOT/'housing-print-verification.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps({'lower_seconds':release['native_plate']['total_predication'],
        'lower_filament_g':release['native_plate']['filaments'][0]['total_used_g'],
        'automatic_lower_support_seconds':probe['support_time_seconds']},indent=2),flush=True)


if __name__=='__main__':main()
