import sys,json,math,itertools,zipfile,re,subprocess
from pathlib import Path
import numpy as np
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parent))
from cad_client import CadClient
from build_servo_rear_fit_test import read_model,digest,native_plane
from review_snug_servo_nest import native_cylinder,set_pose
import prepare_bambu_latest as b
root=Path(__file__).resolve().parents[1]; lane=(root/'.build/clamshell-detail/current-assembly/plate-recheck').resolve();lane.mkdir(parents=True,exist_ok=True)
cad=root/'experiments/garden-auger-labeled.limo'; src=root/'garden-auger-three-wall-assembly.3mf'
r={'cad_sha256':digest(cad),'print_sha256':digest(src),'scope':'Fresh exact nominal/closure/rotation checks and native feature dimensions. Physical fit/strength not certified.'}
with CadClient() as c:
 r['engine_sha256']=digest(c.executable)
 c.call('cad_load_project_model',{'model_json':json.dumps(read_model(cad))})
 scene=c.call('solid_scene');assert not scene['errors']; bodies={q['id']:q for q in scene['bodies']}
 check=lambda ids:c.call('assembly_interference_check',{'occurrence_ids':ids,'clearance_threshold_mm':2})
 r['nominal']=check([3,6,7,8,14,16]);assert r['nominal']['exact'] and not any(p['interfering'] for p in r['nominal']['pairs'])
 r['closure']=[]
 for lift in [10,2,.5,.1,0]:
  set_pose(c,6,(0,0,lift));t=check([3,6,7,8,14,16]);assert not any(p['interfering'] for p in t['pairs']);r['closure'].append({'lift_mm':lift,'clear':True})
 r['motion']=[]
 for angle in range(0,360,30):
  for y in [-.29,.29]:
   set_pose(c,8,(0,y,0),axis=1,degrees=angle);t=check([6,7,8,16]);assert t['exact'] and not any(p['interfering'] for p in t['pairs']);r['motion'].append({'angle_degrees':angle,'axial_shift_mm':y,'clear':True})
 set_pose(c,8)
 for bid in [26,46]:
  for axis,value in [(1,162.65),(1,165.65),(0,-38.2),(0,18.2),(1,194),(2,20.6 if bid==26 else -20.6)]:native_plane(bodies[bid],axis,value)
  native_cylinder(bodies[bid],17.8)
 for bid,rad in [(15,14),(221,14.3),(221,17)]:native_cylinder(bodies[bid],rad)
 for bid,axis,value in [(221,1,120.85),(221,1,130.65),(216,0,-7),(216,0,7),(15,0,-7.2),(15,0,7.2)]:native_plane(bodies[bid],axis,value)
 for x,y in [(-27,118.5),(27,118.5),(-36,196.8),(16,196.8)]:
  for bid,rad,zs in [(26,3.1,[14,20.6]),(46,2,[-6.7,0])]:
   w=native_cylinder(bodies[bid],rad,axis=2,location={'x':x,'y':y});levels=sorted({e['circle']['center']['z'] for e in w['native_boundary_circles']});assert np.allclose(levels,zs,atol=1e-7)
 for x,y in [(-21,132),(21,132),(-36,183),(16,175)]:
  for bid in [26,46]:native_cylinder(bodies[bid],2.5,axis=2,location={'x':x,'y':y})
 r['verified_dimensions_mm']={'ear_slot':3.,'outer_ear_span':56.4,'locator_pin_and_socket_diameter':5.,'journal_diameter':28.,'bushing_ID':28.6,'bushing_OD':34.,'bushing_length':9.8,'housing_bushing_bore':35.6,'adapter_square':14.,'auger_socket_square':14.4,'insert_pilot_diameter':4.,'insert_pilot_depth':6.7,'screw_head_pocket_diameter':6.2}
 print('PASS native dimensions, nominal assembly, five closure positions, 24 rotation/endfloat samples',flush=True)
entries=b.read_zip(src);old=b.read_zip(root/'garden-auger-labeled-assembly.3mf');assert all(old[n]==v for n,v in entries.items() if n.startswith('3D/'));r['print_geometry_unchanged']=True
for i in [1,2]:
 (lane/f'plate_{i}.png').write_bytes(entries[f'Metadata/plate_{i}.png'])
model,config,parts=b.project_parts(entries); build=model.find('{*}build');items={i.get('objectid'):i for i in build}
# A dense footprint layout, keeping existing orientations and all five materials.
layouts=[('PETG - Housing lower',b.I,(8,8)),('PETG - Housing upper',b.UPPER,(8,147)),('PETG - One-piece auger',np.array([[0.,-1.,0.],[1.,0.,0.],[0.,0.,1.]]),(110,181)),('PETG - Square adapter',b.UPRIGHT,(218,18)),('PLA - Constraint-fit bushing',b.UPRIGHT,(212,88))]
for p in config.findall('plate'):config.remove(p)
plate=ET.SubElement(config,'plate')
for k,v in {'plater_id':1,'plater_name':'Single-plate clearance experiment','locked':'false','print_sequence':'by object','filament_map_mode':'Auto For Flush','filament_maps':'1 1 1 1','filament_volume_maps':'0 0 0 0'}.items():b.add_metadata(plate,k,v)
r['one_plate_bounds']=[]
for name,rot,xy in layouts:
 part=parts[name];posed=part['vertices']@rot.T;shift=np.array([*xy,0])-posed.min(0);bounds=np.array([posed.min(0),posed.max(0)])+shift
 assert np.all(bounds[0]>=-1e-6) and np.all(bounds[1]<=[256,256,261]),(name,bounds)
 items[part['object_id']].set('transform',b.transform_text(rot,shift)); instance=ET.SubElement(plate,'model_instance')
 for k,v in {'object_id':part['object_id'],'instance_id':0,'identify_id':100+int(part['object_id'])}.items():b.add_metadata(instance,k,v)
 r['one_plate_bounds'].append({'name':name,'bounds_mm':bounds.tolist()})
entries['3D/3dmodel.model']=ET.tostring(model,encoding='utf-8',xml_declaration=True);entries['Metadata/model_settings.config']=ET.tostring(config,encoding='utf-8',xml_declaration=True)
s=json.loads(entries['Metadata/project_settings.config']);s['printing_by_object_gcode']=s['printing_by_object_gcode'].replace('current_object_idx == 2','current_object_idx == 4');entries['Metadata/project_settings.config']=json.dumps(s).encode()
entries={n:d for n,d in entries.items() if not re.match(r'Metadata/(?:plate(?:_no_light)?_|top_|pick_)\d+',n)}
ET.register_namespace('','http://schemas.openxmlformats.org/package/2006/relationships')
for n,d in list(entries.items()):
 if n.endswith('.rels'):
  rels=ET.fromstring(d)
  for rel in list(rels):
   if rel.get('Target','').lstrip('/') not in entries and rel.get('TargetMode')!='External':rels.remove(rel)
  entries[n]=ET.tostring(rels,encoding='utf-8',xml_declaration=True)
with zipfile.ZipFile(lane/'one-plate-input.3mf','w',zipfile.ZIP_DEFLATED) as z:
 for n,d in entries.items():z.writestr(n,d)
with (lane/'native.log').open('w') as log:
 p=subprocess.run([r'C:/Program Files/Bambu Studio/bambu-studio.exe','--slice','0','--export-3mf','one-plate-sliced.3mf','--outputdir',str(lane),str(lane/'one-plate-input.3mf')],stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW,timeout=600)
r['one_plate_native_exit']=p.returncode;r['one_plate_native']=json.loads((lane/'result.json').read_text());r['single_plate_scope']='One dense layout evaluated, not exhaustive packing proof. Current two-plate print file unchanged.'
(root/'assembly-plate-recheck.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r['one_plate_native']),flush=True)

