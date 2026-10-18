"""Functional cable-envelope experiment using native continuous solid sweeps.

No cable flexibility, friction, strain or supplier boot-size model is claimed.
Temporary swept/boot probes are discarded, never exported as print parts.
Run with uv --with shapely==2.1.2; only the planar outlet check uses Shapely.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

from cad_build import Builder
from cad_client import CadClient
from cable_routing import route_spec, ROUTE_START, STRAIGHT_END, BEND_CENTER, TURN_END, ROUTE_END

ROOT=Path(__file__).resolve().parents[1]
REFERENCE='2a9feb2ea0f2370d2babc0aece511b15af7ff430'


def read_model(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:return json.loads(z.read('model.json'))


def model_value(c):
    m=c.call('cad_project_model')
    return json.loads(m) if isinstance(m,str) else m


def promote(c,body,name):
    c.call('assembly_create_component',{'name':name,'body_ids':[body],'absorb_promoted_bodies':True})
    return next(o['id'] for o in model_value(c)['assembly']['component_structure']['occurrences'] if o['name']==name)


def sweep_probe(c,diameter):
    before={b['id'] for b in c.call('solid_scene')['bodies']}
    name=f'EXPERIMENT - {diameter:g} mm cable envelope'
    c.call('construction_plane_offset',{'name':name+' section plane',
        'reference':{'type':'origin_plane','plane':'yz'},'distance':ROUTE_START[0]})
    plane=model_value(c)['datum_planes'][-1]['datum_id']
    c.call('sketch_begin',{'name':name+' circle','plane':{'type':'datum_plane','datum_id':plane}})
    c.call('sketch_set_grid_snap',{'enabled':False})
    c.call('sketch_add_circle',{'mode':'center_diameter','p1':{'x':ROUTE_START[1],'y':0},
        'p2':{'x':ROUTE_START[1]+diameter/2,'y':0},'ctrl_held':True})
    c.call('sketch_finish')
    c.call('sketch_begin',{'name':name+' path','plane':{'type':'origin_plane','plane':'xy'}})
    c.call('sketch_set_grid_snap',{'enabled':False})
    c.call('sketch_add_line',{'from':dict(zip(('x','y'),ROUTE_START)),
        'to_raw':dict(zip(('x','y'),STRAIGHT_END)),'ctrl_held':True})
    for center,start,end in [(BEND_CENTER,STRAIGHT_END,TURN_END)]:
        c.call('sketch_add_arc_center',{'center':dict(zip(('x','y'),center)),
            'start':dict(zip(('x','y'),start)),'sweep':dict(zip(('x','y'),end)),'ctrl_held':True})
    c.call('sketch_add_line',{'from':dict(zip(('x','y'),TURN_END)),
        'to_raw':dict(zip(('x','y'),ROUTE_END)),'ctrl_held':True})
    c.call('sketch_finish')
    path=model_value(c)['sketches'][-1]
    ids=[i for i,e in path['snapshot']['entities'] if e['type'] in ('arc','line')]
    c.call('solid_sweep',{'profile':{'sketch_name':name+' circle','profile_index':0},
        'path_sketch_name':name+' path','path_entity_ids':ids,'operation':'new_body',
        'target_body_ids':[],'orientation':'corrected_frenet','transition':'transformed','force_c1':True})
    scene=c.call('solid_scene');assert not scene['errors'],scene['errors']
    body=next(b['id'] for b in scene['bodies'] if b['id'] not in before)
    return body,promote(c,body,name)


def check(c,body,occurrence,translation=(0,0,0),fixed=(26,46)):
    c.call('assembly_set_occurrence_pose',{'occurrence_id':occurrence,
        'local_pose':{'translation':list(translation),'rotation':[0,0,0,1]}})
    housing={26:6,46:7}
    result=c.call('assembly_interference_check',{'clearance_threshold_mm':50,
        'occurrence_ids':[occurrence,*[housing[b] for b in fixed]]})
    pairs=[p for p in result['pairs'] if body in (p['body_a'],p['body_b']) and bool(set(fixed)&{p['body_a'],p['body_b']})]
    assert result['exact'] and len(pairs)==len(fixed),pairs
    return {'translation_mm':list(translation),'exact':True,'housing_pairs':pairs}


def old_outlet(c,model):
    c.call('cad_load_project_model',{'model_json':json.dumps(model)})
    before={b['id'] for b in c.call('solid_scene')['bodies']}
    name='EXPERIMENT - old straight outlet through grip'
    c.call('sketch_begin',{'name':name,'plane':{'type':'origin_plane','plane':'yz'}})
    c.call('sketch_set_grid_snap',{'enabled':False})
    c.call('sketch_add_circle',{'mode':'center_diameter','p1':{'x':183.2,'y':0},'p2':{'x':185.2,'y':0},'ctrl_held':True})
    c.call('sketch_finish')
    c.call('solid_extrude',{'sketch_name':name,'profile_indices':[0],'operation':'new_body',
        'extent':{'type':'distance','distance':95},'flip':False,'taper_angle_deg':0,'target_body_ids':[]})
    body=next(b['id'] for b in c.call('solid_scene')['bodies'] if b['id'] not in before)
    c.call('solid_move_copy',{'body_ids':[body],'translation':{'x':10.05,'y':0,'z':0},'pivot':{'x':0,'y':0,'z':0},'copy':False})
    test=check(c,body,promote(c,body,name))
    assert all(p['interfering'] for p in test['housing_pairs'])
    return test


def main():
    # Native sweep helpers do not need the optional planar-analysis package.
    import shapely
    from shapely.geometry import LineString, box

    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=ROOT/'garden-auger-direct-drive.nbcad')
    parser.add_argument('--output',type=Path,default=ROOT/'cable-route-verification.json')
    parser.add_argument('--inspection-model',type=Path,help='Optional non-production model containing the visible 4 mm trial probe')
    parser.add_argument('--inspection-project',type=Path,help='Optional native CAD experiment; contains a virtual cable, never a print export')
    args=parser.parse_args();data=args.project.read_bytes();model=read_model(data)
    previous=subprocess.check_output(['git','show',f'{REFERENCE}:garden-auger-direct-drive.nbcad'],cwd=ROOT)
    before=read_model(previous)
    checks=[];insertions=[];closures=[]
    with CadClient() as c:
        negative=old_outlet(c,before)
        for diameter in [4.0,5.0,6.2]:
            c.call('cad_load_project_model',{'model_json':json.dumps(model)})
            body,occurrence=sweep_probe(c,diameter)
            nominal=check(c,body,occurrence)
            collision=any(p['interfering'] for p in nominal['housing_pairs'])
            assert collision==(diameter==6.2),nominal
            nominal.update(trial_bundle_diameter_mm=diameter,expected_rejection=diameter==6.2)
            checks.append(nominal)
            print(f'Native continuous sweep: {diameter:g} mm, collision={collision}',flush=True)
            if diameter!=4:continue
            for dy,dz in [(.4,0),(-.4,0),(0,.4),(0,-.4),(.4,.4),(-.4,-.4)]:
                test=check(c,body,occurrence,(0,dy,dz))
                assert not any(p['interfering'] for p in test['housing_pairs']),test
                test.update(trial_bundle_diameter_mm=diameter,offset_sensitivity_trial=True);checks.append(test)
            for height in [30,12,6,3,0]:
                test=check(c,body,occurrence,(0,0,height),fixed=(46,))
                assert not any(p['interfering'] for p in test['housing_pairs']),test
                insertions.append(test)
            check(c,body,occurrence)
            if args.inspection_model or args.inspection_project:
                c.call('set_body_appearance',{'body_id':body,'color':{'r':42,'g':169,'b':196,'a':255},'color_name':'Cable trial cyan'})
                visible=model_value(c)
                if args.inspection_model:
                    args.inspection_model.parent.mkdir(parents=True,exist_ok=True)
                    args.inspection_model.write_text(json.dumps(visible))
            for height in [30,12,6,3,0]:
                c.call('assembly_set_occurrence_pose',{'occurrence_id':6,
                    'local_pose':{'translation':[0,0,height],'rotation':[0,0,0,1]}})
                test=check(c,body,occurrence,fixed=(26,))
                assert not any(p['interfering'] for p in test['housing_pairs']),test
                test['upper_lift_mm']=height;closures.append(test)
        c.call('cad_load_project_model',{'model_json':json.dumps(model)})
        prior_ids={b['id'] for b in c.call('solid_scene')['bodies']}
        Builder(c).box('EXPERIMENT - retained boot clearance trial',(10.05,181.1,15.5,190.7,-3.5,3.5),'new_body',[])
        boot=next(b['id'] for b in c.call('solid_scene')['bodies'] if b['id'] not in prior_ids)
        boot_test=check(c,boot,promote(c,boot,'EXPERIMENT - boot trial, no supplier dimensions'))
        assert not any(p['interfering'] for p in boot_test['housing_pairs']),boot_test
        c.call('cad_load_project_model',{'model_json':json.dumps(model)})
        assert c.call('solid_export_preflight')['ok']
        projection=c.call('drawing_projection',{'body_ids':[46],'scope':'definition',
            'direction':[0,0,1],'up':[0,1,0],'include_hidden':True})
        handle_anchors=[a for a in projection['anchors']
            if abs(abs(a['model_point'][0])-100)<1e-6]
        assert handle_anchors,'No native handle-end topology anchors returned'
        rear_anchor=max(handle_anchors,key=lambda a:a['model_point'][1])
        y=rear_anchor['model_point'][1]
        if args.inspection_project:
            c.call('cad_load_project_model',{'model_json':json.dumps(visible)})
            c.call('project_set_visibility',{'hidden_body_ids':[26,15,90,216,221],
                'hidden_datum_plane_ids':[p['datum_id'] for p in visible['datum_planes']],
                'hidden_sketch_names':[s['name'] for s in visible['sketches']]})
            c.call('cad_set_document_name',{'name':'Cable routing experiment - cyan 4 mm trial is NOT a print part'})
            visible=model_value(c)
            with zipfile.ZipFile(args.project) as z:manifest=json.loads(z.read('manifest.json'))
            manifest['model_schema_version']=visible['schema_version']
            args.inspection_project.parent.mkdir(parents=True,exist_ok=True)
            with zipfile.ZipFile(args.inspection_project,'w',zipfile.ZIP_DEFLATED) as z:
                z.writestr('manifest.json',json.dumps(manifest));z.writestr('model.json',json.dumps(visible))
    # Planar tooling is explicitly separate from the authoritative 3D sweep.
    # The cable now passes through the center rear stock and exits its rear
    # face. Check a fully external tail against that native rear-face datum.
    handle=next(s for s in model['sketches'] if s['feature_id']==49)
    authored_y=max(e['position']['x'] for _,e in handle['snapshot']['entities'] if e['type']=='point')
    assert abs(y-authored_y)<1e-6
    assert ROUTE_END[0]==TURN_END[0] and ROUTE_END[1]>y+3
    outlet=LineString([(ROUTE_END[0],y+3),ROUTE_END]).buffer(2,quad_segs=32)
    rear_stock=box(-100,181,100,y)
    gap=outlet.distance(rear_stock);assert gap>=1-1e-8 and not outlet.intersects(rear_stock)
    report={'source_project':args.project.name,'source_project_sha256':hashlib.sha256(data).hexdigest(),
        'revision':'One continuous tangent rear bend; existing sketch/cut reused; side bulge removed',
        'reference_commit':REFERENCE,'reference_project_sha256':hashlib.sha256(previous).hexdigest(),
        'previous_dead_end_reproduced_by_native_tool':negative,'route_spec':route_spec(),
        'native_continuous_swept_bundle_checks':checks,'native_boot_trial':boot_test,
        'boot_trial_bounds_mm':[10.05,181.1,15.5,190.7,-3.5,3.5],
        'lower_drop_in_samples':insertions,'upper_closure_samples':closures,
        'native_4mm_minimum_housing_clearance_mm':min(p['minimum_clearance_mm'] for p in checks[0]['housing_pairs']),
        'planar_tool_experiment':{'tool':'Shapely / GEOS','version':shapely.__version__,
            'scope':'Fully external trial tail vs actual native rear-face datum; XY only. The internal route intentionally passes through rear stock.',
            'rear_face_y_mm':y,'external_tail_to_rear_stock_mm':gap,
            'centerline_rear_face_crossing_mm':[ROUTE_END[0],y,0],
            'native_rear_face_anchor':rear_anchor,
            'native_topology_signature':projection['topology_signatures']['46'],
            'documentation':'https://shapely.readthedocs.io/en/stable/manual.html'},
        'temporary_probes_in_production_model':False,
        'method':'Installed CAD native solid_sweep over analytic line/arc spine, exact B-rep assembly interference. Shapely checks only the planar final exit location.',
        'limitations':['Bundle diameter, boot size, entry coordinates across the seam and an acceptable bend radius are not dimensioned by the supplier drawing; trial assumptions require physical checks.',
            'The 8 mm centerline bend is a design trial, not a cable-manufacturer minimum-radius specification.',
            'Continuous static sweep verifies occupied volume along the assumed route. Closure/drop-in tests are discrete samples, not continuous motion proofs.',
            'No wire elasticity, strain, friction, fatigue, tug retention, water sealing or print capability simulation.',
            'Shapely ignores Z and approximates curved buffers; its planar checks do not replace native 3D verification.',
            'Factory boot remains the only strain relief; the housing channel does not clamp the cable.']}
    if args.inspection_project:
        report['inspection_artifact']=args.inspection_project.relative_to(ROOT).as_posix()
        report['inspection_artifact_sha256']=hashlib.sha256(args.inspection_project.read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'native_minimum_4mm_gap':report['native_4mm_minimum_housing_clearance_mm'],
        'external_tail_to_rear_stock_mm':gap,'native_sweep_checks':len(checks),
        'previous_dead_end_reproduced':True,'oversize_bundle_rejected':True},indent=2),flush=True)


if __name__=='__main__':main()
