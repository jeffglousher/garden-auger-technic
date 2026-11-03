import json,sys,copy,math
from pathlib import Path
sys.path.insert(0,'scripts')
from cad_client import CadClient
from cad_build import profile,save_project
from build_servo_rear_fit_test import read_model,digest
from revise_clamshell import export_mesh
from print_packer import component_count
root=Path(__file__).resolve().parents[1]; build=root/'.build/clamshell-detail/current-assembly/locator-fit';build.mkdir(parents=True,exist_ok=True)
src=root/'experiments/garden-auger-simple-print.limo';dst=root/'experiments/garden-auger-locator-fit.limo'
m=read_model(src);n=copy.deepcopy(m);centers=[(-21,132),(21,132),(-36,183),(16,175)]
for i,(x,y) in enumerate(centers):
 for fid,pts in [(371+4*i,[(0,-.4),(2.5,-.4),(2.5,2.2),(1.9,2.8),(0,2.8)]),(373+4*i,[(0,-.2),(2.8,-.2),(2.6,.2),(2.6,3.2),(0,3.2)])]:
  s=next(v for v in n['sketches'] if v['feature_id']==fid);s['basis']['origin'][1]=y;profile(s,[(x+r,z) for r,z in pts]);next(v for v in n['revolves'] if v['feature_id']==fid+1)['axis_origin']['x']=x
with CadClient() as c:
 c.call('cad_load_project_model',{'model_json':json.dumps(m)});old=c.call('solid_scene')
 c.call('cad_load_project_model',{'model_json':json.dumps(n)});scene=c.call('solid_scene');assert not scene['errors'],scene['errors']
 for bid in [1,15,90,216,221]:assert next(b for b in scene['bodies'] if b['id']==bid)['mesh']==next(b for b in old['bodies'] if b['id']==bid)['mesh']
 for bid in [26,46]:
  mesh,_=export_mesh(c,bid);assert mesh.is_watertight and mesh.is_volume and component_count(mesh)==1
 check=c.call('assembly_interference_check',{'occurrence_ids':[3,6,7,8,14,16],'clearance_threshold_mm':2});assert not any(p['interfering'] for p in check['pairs'])
 save_project(c,dst);(build/'scene.json').write_text(json.dumps(scene))
 report=json.loads((root/'simple-print-geometry-review.json').read_text());report.update(source=str(src.relative_to(root)),source_sha256=digest(src),cad=str(dst.relative_to(root)),cad_sha256=digest(dst),engine_sha256=digest(c.executable))
 report['locators'].update(pin_centers_xy_mm=centers,pin_diameter_mm=5.,socket_diameter_mm=5.2)
 report['nominal_assembly']=check
 # Original report fields about the flange are context, not newly evaluated changes.
 for k in ['changed_parts','active_feature_count','mixed_version_blocked_control','isolated_shield_samples','suppressed_redundant_ring_features']:report.pop(k,None)
 report['unchanged_mesh_body_ids']=[1,15,90,216,221]
 report['locator_revision']={'previous_pin_mm':4,'previous_socket_mm':4.3,'new_diametral_clearance_mm':.2,'pin_section_area_increase_percent':56.25,'nearest_insert_center_mm':min(math.dist(a,b) for a in centers for b in [(-27,118.5),(27,118.5),(-36,196.8),(16,196.8)])}
 (root/'locator-fit-geometry-review.json').write_text(json.dumps(report,indent=2)+'\n')
 print('PASS candidate',report['locator_revision'])
