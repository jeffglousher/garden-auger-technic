"""Slice all four plates locally and refresh native project previews.

Uses saved profiles. Sends no printer commands. Final project keeps geometry,
settings and native previews, without embedding generated G-code.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def read_zip(path):
    with zipfile.ZipFile(path) as z:return {name:z.read(name) for name in z.namelist()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--slicer',type=Path,default=Path(r'C:/Program Files/Bambu Studio/bambu-studio.exe'))
    parser.add_argument('--outputdir',type=Path,default=ROOT/'.build/servo-fit-review/bambu-native')
    args=parser.parse_args()
    source=ROOT/'garden-auger-bambu-latest.3mf'
    output_base=args.outputdir.resolve();output_base.mkdir(parents=True,exist_ok=True)
    # A fresh directory also avoids native Windows overwrite prompts blocking
    # a repeated local slice at the G-code rename step.
    output=Path(tempfile.mkdtemp(prefix='run-',dir=output_base))
    sliced=output/'all-plates-sliced.3mf'
    before=read_zip(source)
    input_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    # Strip cached previews in a temporary input only. The native CLI regenerates
    # missing previews; there is no public regenerate-thumbnails option.
    staged=output/'current-geometry.3mf'
    with zipfile.ZipFile(staged,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in before.items():
            if not (name.startswith('Metadata/') and name.endswith('.png')):
                archive.writestr(name,data)
    # Bambu joins --outputdir to --export-3mf internally, including on Windows.
    # An absolute export argument therefore produces an invalid doubled path.
    command=[str(args.slicer),'--slice','0','--outputdir',str(output),
             '--export-3mf',sliced.name,str(staged)]
    with (output/'native-slicer.log').open('w',encoding='utf-8') as log:
        result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,
                              creationflags=subprocess.CREATE_NO_WINDOW,timeout=300)
    assert (output/'result.json').is_file(), {'native_exit_code':result.returncode,'log':str(output/'native-slicer.log')}
    native_result=json.loads((output/'result.json').read_text())
    assert result.returncode==0 and native_result['return_code']==0, native_result
    export=read_zip(sliced)
    info=ET.fromstring(export['Metadata/slice_info.config'])
    settings=ET.fromstring(before['Metadata/model_settings.config'])
    expected_ids={}
    for plate in settings.findall('plate'):
        metadata={m.get('key'):m.get('value') for m in plate.findall('metadata')}
        expected_ids[int(metadata['plater_id'])]={
            next(m.get('value') for m in instance.findall('metadata') if m.get('key')=='identify_id')
            for instance in plate.findall('model_instance')}
    plates=[]
    for plate in info.findall('plate'):
        meta={m.get('key'):m.get('value') for m in plate.findall('metadata')}
        index=int(meta['index'])
        assert {o.get('identify_id') for o in plate.findall('object')}==expected_ids[index]
        gcode=export[f'Metadata/plate_{index}.gcode']
        assert b'HEADER_BLOCK_END' in gcode[:6000]
        assert meta['outside']=='false',meta
        header=gcode[:gcode.index(b'; HEADER_BLOCK_END')+len(b'; HEADER_BLOCK_END')].decode('utf-8')
        assert f'Metadata/plate_{index}.png' in export
        plates.append({'plate':index,'objects':[o.get('name') for o in plate.findall('object')],
            'time_seconds':int(meta['prediction']),'filament_weight_g':float(meta['weight']),
            'outside_printable_area':False,'support_used':meta['support_used']=='true',
            'filaments':[f.attrib for f in plate.findall('filament')],'gcode_header':header})
    assert sorted(p['plate'] for p in plates)==[1,2,3,4]
    # Refresh display/slice statistics only. Preserve every original mesh,
    # transform, object override and printer/filament/process setting bytewise.
    refreshed={name:data for name,data in export.items() if
        re.match(r'Metadata/(?:plate(?:_no_light)?_|top_|pick_)\d+(?:_small)?\.png$',name)}
    refreshed['Metadata/slice_info.config']=export['Metadata/slice_info.config']
    final={**before,**refreshed}
    assert not any(name.endswith('.gcode') for name in final)
    with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in final.items():archive.writestr(name,data)
    after=read_zip(source)
    assert all(after[name]==data for name,data in before.items() if name not in refreshed)
    version=re.search(r'; (BambuStudio[^\r\n]+)',plates[0]['gcode_header'])
    report={'source_project':source.name,'source_project_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'sliced_input_sha256':input_hash,'native_slicer':version.group(1) if version else str(args.slicer),
        'command_scope':'Local --slice 0; no printer commands sent','native_exit_code':result.returncode,
        'all_four_plates_have_gcode':True,'plates':plates,
        'sliced_export_sha256':hashlib.sha256(sliced.read_bytes()).hexdigest(),
        'final_project_gcode_embedded':False,
        'native_preview_and_slice_statistics_refreshed':True,
        'all_geometry_and_printer_filament_process_settings_byte_identical_to_sliced_input':True}
    (ROOT/'bambu-slice-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'native_slicer':report['native_slicer'],'all_plates_sliced':True,
                     'housing_time_seconds':plates[0]['time_seconds'],
                     'housing_weight_g':plates[0]['filament_weight_g'],
                     'source_project_sha256':report['source_project_sha256']},indent=2),flush=True)


if __name__=='__main__':main()
