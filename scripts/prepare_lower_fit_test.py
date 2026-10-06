"""Extract the current pocket-up lower half without changing saved profiles."""
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile
import numpy as np
import prepare_bambu_latest as b

ROOT=Path(__file__).resolve().parents[1]


def main():
    entries=b.read_zip(b.TARGET)
    model,config,parts=b.project_parts(entries)
    b.geometry_checks(parts)
    part=parts['PETG - Housing lower'];oid=part['object_id']
    resources=model.find('{*}resources')
    for obj in list(resources):
        if obj.tag.endswith('object') and obj.get('id')!=oid:resources.remove(obj)
    build=model.find('{*}build');item=next(i for i in build if i.get('objectid')==oid)
    build.clear();build.append(item);item.set('printable','1')
    mesh=part['vertices'];bounds=np.array([mesh.min(0),mesh.max(0)])
    translation=np.array([128.,128.,0.])-np.array([*((bounds[0,:2]+bounds[1,:2])/2),bounds[0,2]])
    item.set('transform',b.transform_text(np.eye(3),translation))
    for child in list(config):
        if child.tag=='object' and child.get('id')!=oid or child.tag in ('plate','assemble'):config.remove(child)
    plate=ET.SubElement(config,'plate')
    for key,value in {'plater_id':1,'plater_name':'PETG - Lower clamshell rear-cable fit test',
        'locked':'false','filament_map_mode':'Auto For Flush','filament_maps':'1 1 1 2',
        'filament_volume_maps':'0 0 0 0'}.items():b.add_metadata(plate,key,value)
    instance=ET.SubElement(plate,'model_instance')
    for key,value in {'object_id':oid,'instance_id':0,'identify_id':104}.items():b.add_metadata(instance,key,value)
    entries={name:data for name,data in entries.items() if
        (not name.startswith('3D/Objects/') or name==part['mesh_path'])
        and not re.match(r'Metadata/(?:plate(?:_no_light)?_|top_|pick_)\d+',name)
        and not name.endswith('.gcode')}
    entries['3D/3dmodel.model']=ET.tostring(model,encoding='utf-8',xml_declaration=True)
    entries['Metadata/model_settings.config']=ET.tostring(config,encoding='utf-8',xml_declaration=True)
    entries['Metadata/filament_sequence.json']=json.dumps({'plate_1':{'nozzle_sequence':[],
        'optimal_assignment':[],'sequence':[]}}).encode()
    info=ET.fromstring(entries['Metadata/slice_info.config'])
    for child in list(info):
        if child.tag!='header':info.remove(child)
    entries['Metadata/slice_info.config']=ET.tostring(info,encoding='utf-8',xml_declaration=True)
    ET.register_namespace('','http://schemas.openxmlformats.org/package/2006/relationships')
    for key in ('3D/_rels/3dmodel.model.rels','_rels/.rels'):
        rels=ET.fromstring(entries[key])
        for rel in list(rels):
            target=rel.get('Target','').lstrip('/')
            if target not in entries or key.startswith('3D/') and target!=part['mesh_path']:rels.remove(rel)
        entries[key]=ET.tostring(rels,encoding='utf-8',xml_declaration=True)
    target=ROOT/'garden-auger-lower-fit-test.3mf'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in entries.items():z.writestr(name,data)
    check=b.read_zip(target);_,_,actual=b.project_parts(check)
    assert set(actual)=={'PETG - Housing lower'}
    assert np.array_equal(actual['PETG - Housing lower']['faces'],part['faces'])
    assert np.array_equal(actual['PETG - Housing lower']['vertices'],mesh)
    assert check['Metadata/project_settings.config']==entries['Metadata/project_settings.config']
    print('Current lower mesh centered pocket-up; saved global profiles preserved',flush=True)


if __name__=='__main__':main()
