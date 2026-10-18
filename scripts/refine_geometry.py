"""Review all three design areas in an isolated native document.

Exterior relief removes stock; outer locating sockets gain X accommodation.
Fixed servo, drive and bushing dimensions are retained. No printer commands.
"""
import copy
import itertools
import json
import math
from pathlib import Path

import numpy as np
import trimesh
from cad_client import CadClient
from cad_build import Builder, profile, save_project
from build_servo_rear_fit_test import read_model, digest, native_plane
from review_snug_servo_nest import native_cylinder, set_pose, pairs
from revise_clamshell import export_mesh, model as live_model, sketch_at
from print_packer import component_count

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'experiments/garden-auger-constraint-bushing-test.limo'
CAD=ROOT/'experiments/garden-auger-relieved-housing.limo'
BUILD=ROOT/'.build/clamshell-detail/current-assembly/geometry-refinement'
REPORT=ROOT/'geometry-refinement-review.json'
RELIEF=12.5


def slot(c,x,body):
    name=f'Outer locator {x:+g} X relief'
    r=3.65;d=.4;y=192.
    points=[(x-d,y-r),(x+d,y-r),(x+d,y+r),(x-d,y+r)]
    Builder(c).poly(name,points,plane='xy')
    m=live_model(c)
    s=next(s for s in m['sketches'] if s['name']==name)
    profile(s,points,{1:((x+d,y),r,-math.pi/2,math.pi/2),
                      3:((x-d,y),r,math.pi/2,3*math.pi/2)})
    c.call('cad_load_project_model',{'model_json':json.dumps(m)})
    c.call('solid_extrude',{'sketch_name':name,'profile_indices':[0],
        'operation':'cut','extent':{'type':'distance','distance':3.2},
        'taper_angle_deg':0,'flip':body==46,'target_body_ids':[body]})
    assert not c.call('solid_scene')['errors']
    print(name,'OK',flush=True)


def probe_occurrence(c,name,x,y,r,z0,z1):
    before={b['id'] for b in c.call('solid_scene')['bodies']}
    sketch_at(c,name,[(x,z0),(x+r,z0),(x+r,z1),(x,z1)],(0,y,0))
    c.call('solid_revolve',{'sketch_name':name,'profile_indices':[0],
        'axis_origin':{'x':x,'y':0},'axis_direction':{'x':0,'y':1},
        'angle_deg':360,'flip':False,'operation':'new_body','target_body_ids':[]})
    bid=next(iter({b['id'] for b in c.call('solid_scene')['bodies']}-before))
    c.call('assembly_create_component',{'name':name,'body_ids':[bid],'absorb_promoted_bodies':True})
    oid=next(o['id'] for o in live_model(c)['assembly']['component_structure']['occurrences'] if o['name']==name)
    return bid,oid


def main():
    BUILD.mkdir(parents=True,exist_ok=True)
    original=read_model(SOURCE);candidate=copy.deepcopy(original)
    candidate['document']['name']='Garden auger - relieved housing and accommodating locators'
    changed=[]
    for s in candidate['sketches']:
        if s['name'].startswith(('Bearing right shoulder','Bearing left shoulder','Servo right shoulder','Servo left shoulder')):
            old=[(e['position']['x'],e['position']['y']) for _,e in s['snapshot']['entities'] if e['type']=='point']
            direction=1 if 'right' in s['name'] else -1
            sign=1 if 'upper' in s['name'] else -1
            x=old[0][0];endx=x+direction*RELIEF
            points=[(x,0),(endx,sign*RELIEF),(direction*120,sign*RELIEF),(direction*120,0)]
            a=math.pi if direction==1 else 0.;b=sign*math.pi/2
            if a-b>math.pi:b+=2*math.pi
            profile(s,points,{0:((endx,0),RELIEF,min(a,b),max(a,b))})
            changed.append(s['name'])
    assert len(changed)==8
    report={'source':str(SOURCE.relative_to(ROOT)),'source_sha256':digest(SOURCE),
        'requirements':['housing shape and material reduction','bushing shaft and adapter fit','assembly locators and screw access'],
        'relief_radius_mm':RELIEF,'outer_socket_x_extra_each_side_mm':.4,
        'fixed_dimensions':'Servo nest, square, journal, bushing, thrust stops, screw stacks and rear cable path retained.',
        'printer_command_sent':False}
    with CadClient() as c:
        report['engine_sha256']=digest(c.executable)
        c.call('cad_load_project_model',{'model_json':json.dumps(original)})
        before=c.call('solid_scene');assert not before['errors']
        old_mesh={bid:export_mesh(c,bid)[0] for bid in [26,46]}
        sections=[('ear-nest',46,'xy',-.1,164.15),('servo-floor',46,'xz',179.9,-10),
                  ('rear-wall',46,'xy',-5,193),('square-socket',15,'xz',134,0),
                  ('adapter-seat',216,'xy',0,149),('pla-bushing',221,'xz',125,0)]
        old_sections=[c.call('solid_section_review',{'body_id':b,'plane':p,'offset_mm':o,'probe_mm':v,'deflection_mm':.01}) for _,b,p,o,v in sections]
        c.call('cad_load_project_model',{'model_json':json.dumps(candidate)})
        assert not c.call('solid_scene')['errors']
        slot(c,-88,26);slot(c,88,46)
        final=save_project(c,CAD)
        scene=c.call('solid_scene');assert not scene['errors']
        bodies={b['id']:b for b in scene['bodies']}
        for bid in [1,15,90,216,221]:assert bodies[bid]['mesh']==next(b for b in before['bodies'] if b['id']==bid)['mesh']
        assert final['body_appearances']==original['body_appearances']
        report['unchanged_body_ids']=[1,15,90,216,221]
        for key,ids in [('extrudes',[131,161,183,278]),('revolves',[301])]:
            for fid in ids:assert next(f for f in original[key] if f['feature_id']==fid)==next(f for f in final[key] if f['feature_id']==fid)
        report['housing']={}
        for bid in [26,46]:
            mesh,raw=export_mesh(c,bid)
            assert mesh.is_watertight and mesh.is_volume and component_count(mesh)==1
            assert mesh.volume<old_mesh[bid].volume
            added=trimesh.boolean.difference([mesh,old_mesh[bid]],engine='manifold')
            assert abs(added.volume)<10.,added.volume
            report['housing'][str(bid)]={'before_volume_mm3':old_mesh[bid].volume,'after_volume_mm3':mesh.volume,
                'removed_volume_mm3':old_mesh[bid].volume-mesh.volume,'tessellation_difference_added_mm3':abs(added.volume)}
        report['retained_section_probes']=[]
        for (name,b,p,o,v),old in zip(sections,old_sections):
            new=c.call('solid_section_review',{'body_id':b,'plane':p,'offset_mm':o,'probe_mm':v,'deflection_mm':.01})
            a=[[s['start_mm'],s['end_mm']] for s in old['probe_spans']]
            d=[[s['start_mm'],s['end_mm']] for s in new['probe_spans']]
            assert np.allclose(a,d,rtol=0,atol=1e-7),(name,a,d)
            report['retained_section_probes'].append({'name':name,'spans_mm':d})
        for bid in [26,46]:
            for axis,value in [(1,162.65),(1,165.65),(0,-38.2),(0,18.2),(1,194),(2,20.6 if bid==26 else -20.6)]:native_plane(bodies[bid],axis,value)
            native_cylinder(bodies[bid],17.8)
        for bid,r in [(15,14),(221,14.3),(221,17)]:native_cylinder(bodies[bid],r)
        for bid,axis,value in [(221,1,120.85),(221,1,130.65),(216,0,-7),(216,0,7),(15,0,-7.2),(15,0,7.2)]:native_plane(bodies[bid],axis,value)
        report['drive_fit']={'journal_mm':28,'bushing_bore_mm':28.6,'bushing_outer_mm':34,
            'bushing_length_mm':9.8,'seat_mm':35.6,'seat_span_mm':10.9,'bushing_end_room_each_mm':.55,
            'square_peg_mm':14,'square_socket_mm':14.4,'physical_engagement_and_thread_depth_unconfirmed':True}
        nominal=c.call('assembly_interference_check',{'occurrence_ids':[3,6,7,8,14,16],'clearance_threshold_mm':2})
        assert nominal['exact'] and not any(p['interfering'] for p in nominal['pairs'])
        report['nominal_assembly']=nominal
        report['preflight']=c.call('solid_export_preflight',{'body_ids':[26,46,15,90,216,221]})
        assert report['preflight']['ok'] and not report['preflight']['timeline_errors']
        (BUILD/'scene.json').write_text(json.dumps(scene))
        print('Material removal, locked geometry, six section probes and nominal assembly passed',flush=True)
        # Inspection artifacts below are never saved in the delivered CAD.
        report['driver_access']=[]
        for x,y in [(-27,118.5),(27,118.5),(-36,196.8),(16,196.8)]:
            driver,oid=probe_occurrence(c,f'Inspection driver {x} {y}',x,y,2.25,17.,60.)
            test=c.call('assembly_interference_check',{'occurrence_ids':[6,7,oid],'clearance_threshold_mm':2})
            ps=pairs(test,{driver},{26,46});assert not any(p['interfering'] for p in ps)
            report['driver_access'].append({'xy_mm':[x,y],'driver_diameter_mm':4.5,'pairs':ps})
        c.call('cad_load_project_model',{'model_json':json.dumps(final)})
        report['slot_controls']=[]
        for x,body,half,z0,z1 in [(-88,26,6,.1,2.2),(88,46,7,-2.2,-.1)]:
            bid,oid=probe_occurrence(c,f'Inspection locator {x}',x,192,3.5,z0,z1)
            for shift,blocked in [((.50,0,0),False),((-.50,0,0),False),((.56,0,0),True),((0,.14,0),False),((0,.16,0),True)]:
                set_pose(c,oid,shift)
                test=c.call('assembly_interference_check',{'occurrence_ids':[half,oid],'clearance_threshold_mm':2})
                ps=pairs(test,{bid},{body});assert any(p['interfering'] for p in ps)==blocked,(x,shift,ps)
                report['slot_controls'].append({'x_mm':x,'shift_mm':shift,'blocked':blocked,'pairs':ps})
            set_pose(c,oid)
        c.call('cad_load_project_model',{'model_json':json.dumps(final)})
        for lift in [10,2,.5,.1,0]:
            set_pose(c,6,(0,0,lift))
            test=c.call('assembly_interference_check',{'occurrence_ids':[6,7,8,16],'clearance_threshold_mm':2})
            assert not any(p['interfering'] for p in pairs(test,{221},{26,46,15,90}))
        set_pose(c,6)
        for y in [-.5,.5,-.56,.56]:
            set_pose(c,16,(0,y,0))
            test=c.call('assembly_interference_check',{'occurrence_ids':[6,7,8,16],'clearance_threshold_mm':2})
            assert any(p['interfering'] for p in pairs(test,{221},{26,46,15,90}))==(abs(y)>.55)
        set_pose(c,16)
        for angle in range(0,360,30):
            for y in [-.29,.29]:
                set_pose(c,8,(0,y,0),axis=1,degrees=angle)
                test=c.call('assembly_interference_check',{'occurrence_ids':[6,7,8,16],'clearance_threshold_mm':2})
                assert not any(p['interfering'] for p in pairs(test,{15,90},{26,46,221}))
        set_pose(c,8)
        for shift in [(0,0,0)]+list(itertools.product([-.19,.19],[-.14,.14],[-.19,.19])):
            for oid in [8,14]:set_pose(c,oid,shift)
            c.call('assembly_set_occurrence_pose',{'occurrence_id':3,'local_pose':{'translation':[shift[0],148.7+shift[1],shift[2]],'rotation':[math.sqrt(.5),0,0,math.sqrt(.5)]}})
            test=c.call('assembly_interference_check',{'occurrence_ids':[3,6,7,8,14,16],'clearance_threshold_mm':2})
            assert test['exact'] and not any(p['interfering'] for p in test['pairs'])
        report['sample_counts']={'driver_access':4,'slot_controls':10,'closure':5,'bushing_capture':4,'auger_rotation_endfloat':24,'coupled_poses':9}
    report['cad']=str(CAD.relative_to(ROOT));report['cad_sha256']=digest(CAD)
    report['limitations']='Nominal and sampled digital checks. Printed fit, stiffness, torque, wear, dirt trial, actual shaft engagement and usable metal thread depth need physical validation.'
    REPORT.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: all three geometry review areas; native motion, driver access and slot controls passed',flush=True)


if __name__=='__main__':main()
