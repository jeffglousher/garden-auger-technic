"""Matching sparse detail halves: preserve saved PETG/global settings, slice locally."""
import base64
import json
import re
import tempfile
import uuid
import xml.etree.ElementTree as ET
import zipfile
import numpy as np
from pathlib import Path
from cad_client import CadClient
from build_servo_rear_fit_test import read_model,digest
from prepare_sparse_servo_upper_test import exported_mesh
from prepare_bambu_latest import CORE,UPPER,I,project_parts,read_zip,transform_text
from check_housing_print import slice_native
from print_packer import component_count

ROOT=Path(__file__).resolve().parents[1]
CAD=ROOT/'experiments/garden-auger-clamshell-detail-test.limo'
BUILD=ROOT/'.build/clamshell-detail'


def main():
    review=json.loads((ROOT/'clamshell-detail-review.json').read_text())
    assert digest(CAD)==review['cad_sha256']
    results=[]
    with CadClient() as c:
        c.call('cad_load_project_model',{'model_json':json.dumps(read_model(CAD))})
        for side,bid,oid,rotation,q in [('upper',26,6,UPPER,[0,1,0,0]),('lower',46,7,I,[0,0,0,1])]:
            name=f'PETG - Housing {side}'
            template=ROOT/f'garden-auger-{side}-servo-sparse-test.3mf'
            target=ROOT/f'garden-auger-{side}-clamshell-detail-sparse-test.3mf'
            before=read_zip(template);entries=dict(before)
            model,config,parts=project_parts(entries);part=parts[name]
            raw=base64.b64decode(c.call('solid_export_3mf',{'body_ids':[bid],'scope':'definition',
                'linear_deflection':.08,'angular_deflection':.2})['bytes_base64'])
            mesh=exported_mesh(raw)
            assert mesh.is_watertight and mesh.is_volume and component_count(mesh)==1
            center=mesh.bounds.mean(0);vertices=mesh.vertices-center
            rotated=vertices@rotation.T;translation=np.array([128,128,-rotated[:,2].min()])
            view=f'Print - clamshell detail {side}'
            c.call('upsert_named_view',{'name':view,'camera':{'position':[280,-180,330],
                'target':[128,128,10],'up':[0,0,1]},'visible_body_ids':[bid],
                'occurrence_offsets':[{'occurrence_id':oid,'translation':(translation-rotation@center).tolist(),'rotation':q}],
                'print_layout':True,'print_bed':{'name':'Bambu X2D main','size_mm':[256,256,261]}})
            preflight=c.call('solid_export_preflight',{'body_ids':[bid],'named_view':view})
            assert preflight['ok'] and not preflight['timeline_errors']
            assert not any(i['code'] in ['below_bed','outside_bed','possible_overlap'] for i in preflight['layout']['issues'])
            placed=exported_mesh(base64.b64decode(c.call('solid_export_3mf',{'body_ids':[bid],
                'scope':'assembly','named_view':view,'linear_deflection':.08,'angular_deflection':.2})['bytes_base64']),placed=True)
            assert np.allclose(placed.vertices,rotated+translation,rtol=0,atol=1e-6)
            mm=ET.fromstring(entries[part['mesh_path']]);node=mm.find('.//{*}mesh');node.clear()
            vs=ET.SubElement(node,f'{{{CORE}}}vertices');ts=ET.SubElement(node,f'{{{CORE}}}triangles')
            for v in vertices:ET.SubElement(vs,f'{{{CORE}}}vertex',dict(zip(['x','y','z'],[f'{x:.12g}' for x in v])))
            for t in mesh.faces:ET.SubElement(ts,f'{{{CORE}}}triangle',dict(zip(['v1','v2','v3'],map(str,t))))
            ET.register_namespace('',CORE)
            entries[part['mesh_path']]=ET.tostring(mm,encoding='utf-8',xml_declaration=True)
            model.find('{*}build/{*}item').set('transform',transform_text(rotation,translation))
            entries['3D/3dmodel.model']=ET.tostring(model,encoding='utf-8',xml_declaration=True)
            for n in config.iter():
                key=n.get('key','')
                if 'face_count' in n.attrib:n.set('face_count',str(len(mesh.faces)))
                if key=='source_file':n.set('value',str(CAD.relative_to(ROOT)).replace('\\','/'))
                if key.startswith('source_offset_'):n.set('value',f'{center["xyz".index(key[-1])]:.12g}')
                if key=='plater_name':n.set('value',f'Clamshell detail test - {side}')
                if n.tag=='assemble_item' and 'instance_id' in n.attrib:n.set('transform',transform_text(rotation,translation))
                if n.tag=='part':n.set('uuid',str(uuid.uuid5(uuid.NAMESPACE_URL,review['cad_sha256']+side)))
            entries['Metadata/model_settings.config']=ET.tostring(config,encoding='utf-8',xml_declaration=True)
            entries={n:d for n,d in entries.items() if not n.endswith('.gcode') and
                not(n.startswith('Metadata/') and n.endswith('.png')) and
                not(n.startswith('Metadata/servo-') and n.endswith('.txt'))}
            info=ET.fromstring(entries['Metadata/slice_info.config'])
            for n in list(info):
                if n.tag!='header':info.remove(n)
            entries['Metadata/slice_info.config']=ET.tostring(info,encoding='utf-8',xml_declaration=True)
            ET.register_namespace('','http://schemas.openxmlformats.org/package/2006/relationships')
            for n,d in list(entries.items()):
                if n.endswith('.rels'):entries[n]=ET.tostring(ET.fromstring(d),encoding='utf-8',xml_declaration=True)
            entries['Metadata/clamshell-detail-test.txt']=('New matching detail halves required. Four M3x18 housing screws; four RX-M3x5.7 inserts. '
                'Fitted component cavities retained. Provisional 0.30mm diametral locator clearance. '
                'Sparse dimensional test only; loaded strength and dirty protection unqualified. No printer command.').encode()
            folder=Path(tempfile.mkdtemp(prefix=f'{side}-slice-',dir=BUILD))
            print(f'Slicing new {side} detail half',flush=True)
            exported,native=slice_native(entries,folder)
            roles=set(re.findall(rb'^; FEATURE: ([^\r\n]+)',exported['Metadata/plate_1.gcode'],re.MULTILINE))
            assert not any(b'Support' in r or b'Prime' in r or b'Wipe' in r for r in roles)
            refreshed={n:d for n,d in exported.items() if re.match(r'Metadata/(?:plate(?:_no_light)?_|top_|pick_)\d+(?:_small)?\.png$',n)}
            final={**entries,**refreshed,'Metadata/slice_info.config':exported['Metadata/slice_info.config']}
            assert final['Metadata/project_settings.config']==before['Metadata/project_settings.config']
            with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
                for n,d in final.items():z.writestr(n,d)
            saved_model,saved_config,saved_parts=project_parts(read_zip(target))
            assert set(saved_parts)=={name} and saved_parts[name]['extruder']==1
            assert np.array_equal(saved_parts[name]['faces'],mesh.faces)
            assert np.allclose(saved_parts[name]['vertices'],vertices,rtol=0,atol=1e-8)
            actual=np.array([float(x) for x in saved_model.find('{*}build/{*}item').get('transform').split()])
            assert np.allclose(saved_parts[name]['vertices']@actual[:9].reshape(3,3)+actual[9:],
                               placed.vertices,rtol=0,atol=1e-6)
            assert native['native_plate']['filament_change_times']==0
            settings=json.loads((ROOT/'servo-sparse-print-verification.json').read_text())['test_settings']
            assert not any(n.get('key') in settings for n in saved_config.findall('object/metadata'))
            result={'file':target.name,'sha256':digest(target),'cad_sha256':digest(CAD),
                'one_closed_connected_half':True,'packaged_mesh_matches_native':True,
                'native_print_preflight':preflight,'native_placement_matches_package':True,
                'bed_bounds_mm':placed.bounds.tolist(),'global_config_preserved':True,
                'object_uses_global_strength_settings':True,'settings':settings,
                'slice':native,'gcode_roles':sorted(r.decode() for r in roles),
                'printer_command_sent':False,'final_project_gcode_embedded':False}
            results.append(result)
            print(side,native['native_plate']['total_predication']/60,'minutes',flush=True)
    (ROOT/'clamshell-detail-print-verification.json').write_text(json.dumps(results,indent=2)+'\n')


if __name__=='__main__':main()
