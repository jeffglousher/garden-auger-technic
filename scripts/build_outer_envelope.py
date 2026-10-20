"""Slim and round both outer face pairs, blending the plan-view cheek steps.

Only the installed isolated native engine is used. The existing 90 MiB owned
output sublane retains successful native evidence and small rejected trials.
"""
import copy,json
from pathlib import Path
import numpy as np

from cad_client import CadClient
from cad_build import Builder,save_project
from slim_housing import rounded_profile
from revise_clamshell import export_mesh,model as live_model
from build_servo_rear_fit_test import read_model,digest,native_plane
from print_packer import component_count

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'experiments/garden-auger-solid-frame.limo'
CAD=ROOT/'experiments/garden-auger-rounded-envelope.limo'
BUILD=ROOT/'.build/clamshell-detail/current-assembly/outer-envelope'
REPORT=ROOT/'outer-envelope-geometry-review.json'
OUTLINE=[(-33.,107.9),(33.,107.9),(33.,124.),(21.3,140.),(21.3,176.),
         (34.,191.),(34.,206.5),(-41.3,206.5),(-41.3,158.),(-33.,140.)]
RADII={0:6.,1:6.,2:12.,3:12.,4:12.,5:6.,6:6.,7:6.,8:8.,9:8.}


def outer_face_edges(body,z):
    edges=[]
    for e in body['edges']:
        ps=e['points'];circle=e.get('circle')
        if len(ps)<2 or not all(abs(p['z']-z)<1e-7 for p in ps):continue
        if circle and circle['closed']:continue # Fastener bores remain sharp datums.
        if not all(-44<p['x']<36 for p in ps):continue # Preserve the complete D grips.
        if max(p['y'] for p in ps)<113:continue # The jacket below also protects tangent propagation at the nose.
        if min(p['y'] for p in ps)<108:continue
        edges.append(e['id'])
    return edges


def main():
    BUILD.mkdir(parents=True,exist_ok=True)
    original=read_model(SOURCE);candidate=copy.deepcopy(original)
    candidate['document']['name']='Garden auger - slim rounded outer envelope'
    rounded_profile(next(s for s in candidate['sketches'] if s['feature_id']==40),OUTLINE,RADII)
    # The new complete outline supplies the rear cable roof and screw stock;
    # the previous pad/cheek additions would protrude through its thinner sides.
    suppress={311,312,*range(362,369),387,388}
    for f in candidate['document']['history']['features']:
        if f['id'] in suppress:f['suppressed']=True
    report={'source':str(SOURCE.relative_to(ROOT)),'source_sha256':digest(SOURCE),
        'outline_vertices_xy_mm':OUTLINE,'plan_corner_radii_mm':RADII,
        'suppressed_stock_features':sorted(suppress),'grip_geometry':'Existing complete D grips and their datum retained.',
        'profile':json.loads((ROOT/'d-grip-geometry-review.json').read_text())['profile'],
        'locators':json.loads((ROOT/'d-grip-geometry-review.json').read_text())['locators'],
        'bearing_roof_protection':{'outer_radius_mm':20.6,'axial_y_mm':[107.9,113.9],
            'minimum_sampled_cover_target_mm':2.8,
            'reason':'Protect the entry roof from outer-face fillet propagation; original functional cuts run afterward.'},
        'printer_command_sent':False}
    with CadClient() as c:
        report['engine_sha256']=digest(c.executable)
        c.call('cad_load_project_model',{'model_json':json.dumps(original)})
        old_scene=c.call('solid_scene');assert not old_scene['errors']
        old={bid:export_mesh(c,bid)[0] for bid in [26,46]}
        # Round the simple blank before holes, grip joins and component cuts.
        # Later cuts retain their exact functional dimensions, and cannot
        # confuse the outer edge selection with counterbore/cable edges.
        history=candidate['document']['history']['features']
        split_index=next(i for i,f in enumerate(history) if f['id']==41)+1
        partial=copy.deepcopy(candidate)
        for f in partial['document']['history']['features'][split_index:]:f['suppressed']=True
        partial['document']['history']['rollback_index']=len(history)
        c.call('cad_load_project_model',{'model_json':json.dumps(partial)})
        assert not c.call('solid_scene')['errors'],c.call('solid_scene')['errors']
        (BUILD/'unrounded-plan-model.json').write_text(json.dumps(live_model(c)))
        report['face_round_trials']=[]
        for bid,z in [(26,20.6),(26,-20.6)]:
            before=live_model(c);body=next(b for b in c.call('solid_scene')['bodies'] if b['id']==bid)
            edges=outer_face_edges(body,z);assert edges
            success=False
            for radius in [5.,4.,3.,2.]:
                try:
                    c.call('solid_fillet',{'body_id':bid,'edge_ids':edges,'radius':radius,'tangent_chain':False})
                    errors=c.call('solid_scene')['errors'];assert not errors,errors
                    mesh,_=export_mesh(c,bid)
                    assert mesh.is_watertight and mesh.is_volume and component_count(mesh)==1,{'watertight':mesh.is_watertight,'volume':mesh.is_volume,'components':component_count(mesh)}
                    report['face_round_trials'].append({'body':bid,'outer_z_mm':z,'radius_mm':radius,'edge_count':len(edges),'passed':True})
                    print(f'Outer face round blank Z{z:g} R{radius:g} passes native closed export',flush=True)
                    success=True;break
                except (RuntimeError,AssertionError) as error:
                    report['face_round_trials'].append({'body':bid,'radius_mm':radius,'passed':False,'error':str(error)})
                    print('Rejected face round',bid,radius,str(error),flush=True)
                    c.call('cad_load_project_model',{'model_json':json.dumps(before)})
            if not success:
                (BUILD/'rejected-rounds.json').write_text(json.dumps(report,indent=2)+'\n')
                raise AssertionError(report['face_round_trials'])
        # A circular bearing jacket retains the front roof where a global
        # face round would otherwise consume the existing 2.8 mm cover.
        # It is added before the original journal/thrust/entry cuts run.
        Builder(c).revolve('Rounded bearing nose jacket - retained 2.8mm cover',
            [(107.9,0),(107.9,20.6),(113.9,20.6),(113.9,0)],'join',[26])
        rounded=live_model(c)
        added=[f for f in rounded['document']['history']['features'] if f['id'] not in {v['id'] for v in partial['document']['history']['features']}]
        candidate['document']['history']['features']=history[:split_index]+added+history[split_index:]
        candidate['document']['history']['rollback_index']=len(candidate['document']['history']['features'])
        for key in ['fillets','sketches','revolves']:candidate[key]=rounded[key]
        candidate['counters']=rounded['counters']
        c.call('cad_load_project_model',{'model_json':json.dumps(candidate)})
        scene=c.call('solid_scene');assert not scene['errors']
        bodies={b['id']:b for b in scene['bodies']}
        report['housing']={}
        for bid,z in [(26,20.6),(46,-20.6)]:
            mesh,_=export_mesh(c,bid)
            assert mesh.is_watertight and mesh.is_volume and component_count(mesh)==1
            assert mesh.volume<old[bid].volume
            native_plane(bodies[bid],2,z)
            flat=np.all(np.abs(mesh.triangles[:,:,2]-z)<1e-7,axis=1)
            report['housing'][str(bid)]={'before_volume_mm3':old[bid].volume,'after_volume_mm3':mesh.volume,
                'removed_net_mm3':old[bid].volume-mesh.volume,'flat_bed_area_mm2':float(mesh.area_faces[flat].sum()),
                'bounds_mm':mesh.bounds.tolist(),'closed_connected':True}
        for bid in [1,15,90,216,221]:assert bodies[bid]['mesh']==next(b for b in old_scene['bodies'] if b['id']==bid)['mesh']
        report['unchanged_mesh_body_ids']=[1,15,90,216,221]
        report['nominal_assembly']=c.call('assembly_interference_check',{'occurrence_ids':[3,6,7,8,14,16],'clearance_threshold_mm':2})
        assert report['nominal_assembly']['exact'] and not any(p['interfering'] for p in report['nominal_assembly']['pairs'])
        final=save_project(c,CAD);assert final['body_appearances']==original['body_appearances']
        (BUILD/'scene.json').write_text(json.dumps(scene))
    report['cad']=str(CAD.relative_to(ROOT));report['cad_sha256']=digest(CAD)
    REPORT.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report['housing'],indent=2),flush=True)


if __name__=='__main__':main()
