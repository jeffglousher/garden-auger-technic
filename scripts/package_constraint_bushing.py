"""One solid PLA bushing on one plate; retain the saved PLA/printer profile."""
import copy
import json
import re
import tempfile
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
import numpy as np
from build_servo_rear_fit_test import digest
from check_housing_print import slice_native
from prepare_bambu_latest import CORE,PRODUCTION,UPRIGHT,project_parts,read_zip,transform_text

ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=ROOT/'garden-auger-bambu-latest.3mf'  # Profile source only; no historical housing exported.
TARGET=ROOT/'garden-auger-pla-constraint-fit-bushing-test.3mf'
BUILD=ROOT/'.build/clamshell-detail'
NAME='PLA - Constraint fit bushing'


def metadata(parent,key,value):
    n=parent.find(f"metadata[@key='{key}']")
    if n is None:n=ET.SubElement(parent,'metadata',key=key)
    n.set('value',str(value))


def main():
    template_hash=digest(TEMPLATE)
    review=json.loads((ROOT/'constraint-bushing-review.json').read_text())
    assert digest(ROOT/review['cad'])==review['cad_sha256']
    before=read_zip(TEMPLATE);entries=dict(before)
    model,config,parts=project_parts(entries);part=parts['PLA - Full wear sleeve']
    oid=part['object_id'];mesh_path=part['mesh_path']
    vertices=np.array(review['print_centered_vertices']);faces=np.array(review['print_faces'])
    rotation=UPRIGHT;posed=vertices@rotation.T
    translation=np.array([128,128,-posed[:,2].min()])
    bounds=np.array([(posed+translation).min(0),(posed+translation).max(0)])
    assert np.all(bounds[0]>=0) and np.all(bounds[1]<[256,256,261])
    resources=model.find('{*}resources')
    for n in list(resources):
        if n.tag.rsplit('}',1)[-1]=='object' and n.get('id')!=oid:resources.remove(n)
    build=model.find('{*}build');item=copy.deepcopy(next(n for n in build if n.get('objectid')==oid))
    build.clear();item.set('transform',transform_text(rotation,translation));build.append(item)
    identity=uuid.uuid5(uuid.NAMESPACE_URL,review['cad_sha256']+'/body/221')
    root_object=next(n for n in resources.findall('{*}object') if n.get('id')==oid)
    root_object.set(f'{{{PRODUCTION}}}UUID',str(identity))
    for n in root_object.findall('{*}components/{*}component'):
        n.set(f'{{{PRODUCTION}}}UUID',str(uuid.uuid5(identity,'mesh')))
    item.set(f'{{{PRODUCTION}}}UUID',str(uuid.uuid5(identity,'instance')))
    mm=ET.fromstring(entries[mesh_path]);node=mm.find('.//{*}mesh');node.clear()
    vs=ET.SubElement(node,f'{{{CORE}}}vertices');ts=ET.SubElement(node,f'{{{CORE}}}triangles')
    for v in vertices:ET.SubElement(vs,f'{{{CORE}}}vertex',dict(zip(['x','y','z'],map(lambda x:f'{x:.12g}',v))))
    for t in faces:ET.SubElement(ts,f'{{{CORE}}}triangle',dict(zip(['v1','v2','v3'],map(str,t))))
    ET.register_namespace('',CORE)
    entries[mesh_path]=ET.tostring(mm,encoding='utf-8',xml_declaration=True)
    entries['3D/3dmodel.model']=ET.tostring(model,encoding='utf-8',xml_declaration=True)
    for n in list(config):
        if n.tag=='object' and n.get('id')!=oid:config.remove(n)
    obj=next(n for n in config.findall('object') if n.get('id')==oid)
    metadata(obj,'name',NAME);metadata(obj,'extruder',4)
    for n in obj.iter():
        if 'face_count' in n.attrib:n.set('face_count',str(len(faces)))
        key=n.get('key','')
        if key=='name':n.set('value',NAME)
        elif key=='source_file':n.set('value',review['cad'])
        elif key=='source_object_id':n.set('value','221')
        elif key.startswith('source_offset_'):
            # Native meshing has a small bounding-box Z offset for odd polygons.
            raw=json.loads((BUILD/'constraint-bushing-scene.json').read_text())
            b=next(b for b in raw['bodies'] if b['id']==221)
            p=np.array(b['mesh']['positions']).reshape(-1,3)
            center=(p.min(0)+p.max(0))/2
            n.set('value',f'{center["xyz".index(key[-1])]:.12g}')
        if n.tag=='part':n.set('uuid',str(uuid.uuid5(uuid.NAMESPACE_URL,review['cad_sha256'])))
    # Four walls fill the thin annulus; require zero sparse toolpaths below.
    strength={'layer_height':'0.20','initial_layer_print_height':'0.20','wall_loops':'4',
        'sparse_infill_density':'15%','sparse_infill_pattern':'grid',
        'top_shell_layers':'4','bottom_shell_layers':'4','enable_support':'0','enable_prime_tower':'0',
        'print_settings_id':'0.20mm Four Wall PLA Bushing @BBL X2D'}
    for n in list(obj.findall('metadata')):
        if n.get('key') in strength:obj.remove(n)
    plate=copy.deepcopy(next(p for p in config.findall('plate') if any(
        n.get('key')=='object_id' and n.get('value')==oid for n in p.findall('model_instance/metadata'))))
    for n in list(config.findall('plate')):config.remove(n)
    metadata(plate,'plater_id',1);metadata(plate,'plater_name',NAME)
    for inst in list(plate.findall('model_instance')):
        if not any(n.get('key')=='object_id' and n.get('value')==oid for n in inst):plate.remove(inst)
    config.append(plate)
    entries['Metadata/model_settings.config']=ET.tostring(config,encoding='utf-8',xml_declaration=True)
    settings=json.loads(entries['Metadata/project_settings.config']);original_settings=copy.deepcopy(settings)
    settings.update(strength);settings['filament_colour'][3]='#37AAA1'
    entries['Metadata/project_settings.config']=json.dumps(settings).encode()
    entries={n:d for n,d in entries.items() if not n.endswith('.gcode')
        and not(n.startswith('Metadata/') and n.endswith('.png'))
        and not(n.startswith('3D/Objects/') and n!=mesh_path)}
    info=ET.fromstring(entries['Metadata/slice_info.config'])
    for n in list(info):
        if n.tag!='header':info.remove(n)
    entries['Metadata/slice_info.config']=ET.tostring(info,encoding='utf-8',xml_declaration=True)
    ET.register_namespace('','http://schemas.openxmlformats.org/package/2006/relationships')
    for name,data in list(entries.items()):
        if name.endswith('.rels'):
            rels=ET.fromstring(data)
            for rel in list(rels):
                if rel.get('Target','').lstrip('/') not in entries and rel.get('TargetMode')!='External':rels.remove(rel)
            entries[name]=ET.tostring(rels,encoding='utf-8',xml_declaration=True)
    entries['Metadata/constraint-bushing.txt']=b'One PLA bushing. Fixed housing/shaft; more axial room and two-ended lead-ins. No printer command. Physical fit and wear still need checking.'
    folder=Path(tempfile.mkdtemp(prefix='pla-bushing-slice-',dir=BUILD))
    exported,native=slice_native(entries,folder,filament_ids=('4',))
    roles=set(re.findall(rb'^; FEATURE: ([^\r\n]+)',exported['Metadata/plate_1.gcode'],re.MULTILINE))
    assert not any(b'Sparse' in role for role in roles),roles
    assert not any('Sparse' in name and time>0 for name,time in native['native_plate']['feature_type_times'].items())
    assert native['native_plate']['filament_change_times']==0
    assert len(native['native_plate']['objects'])==1
    assert settings['filament_type'][3]=='PLA'
    for key in ['filament_type','filament_settings_id','printer_settings_id','nozzle_temperature']:
        if key in settings:assert settings[key]==original_settings[key],key
    fresh={n:d for n,d in exported.items() if re.match(r'Metadata/(?:plate(?:_no_light)?_|top_|pick_)\d+(?:_small)?\.png$',n)}
    final={**entries,**fresh,'Metadata/slice_info.config':exported['Metadata/slice_info.config']}
    assert not any(n.endswith('.gcode') for n in final)
    with zipfile.ZipFile(TARGET,'w',zipfile.ZIP_DEFLATED) as z:
        for n,d in final.items():z.writestr(n,d)
    sm,sc,sp=project_parts(read_zip(TARGET))
    assert set(sp)=={NAME} and sp[NAME]['extruder']==4
    assert np.array_equal(sp[NAME]['faces'],faces)
    assert np.allclose(sp[NAME]['vertices'],vertices,rtol=0,atol=1e-8)
    result={'file':TARGET.name,'sha256':digest(TARGET),'cad_sha256':review['cad_sha256'],
        'template':TEMPLATE.name,'template_sha256':template_hash,'template_is_profile_source_only':True,
        'one_bushing_only':True,'native_mesh_matches_package':True,'bed_bounds_mm':bounds.tolist(),
        'process':strength,'material':'PLA','active_saved_filament_slot':4,'design_color':'#37AAA1',
        'native_slice':native,'filament_and_printer_profiles_preserved':True,
        'annulus_filled_by_walls_and_gap_fill':True,'sparse_toolpaths':False,
        'printer_command_sent':False,'embedded_gcode':False}
    (ROOT/'constraint-bushing-print-verification.json').write_text(json.dumps(result,indent=2)+'\n')
    assert digest(TEMPLATE)==template_hash,'Saved profile source was modified'
    print('One solid PLA bushing sliced:',native['native_plate']['total_predication']/60,'minutes',flush=True)


if __name__=='__main__':main()
