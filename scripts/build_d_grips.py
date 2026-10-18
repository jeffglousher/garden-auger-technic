"""Smaller complete D grips on the lower half, with coplanar print lands.

Uses an isolated installed native engine. Existing files and user templates
are preserved. The d-grip lane owns at most 150 MiB of additional evidence.
"""
import copy
import json
import math
from pathlib import Path

import numpy as np
from cad_client import CadClient
from cad_build import Builder, profile, save_project
from build_servo_rear_fit_test import read_model, digest, native_plane
from revise_clamshell import model as live_model, sketch_at, export_mesh
from round_housing_review import vertical_edges
from print_packer import component_count

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'experiments/garden-auger-relieved-housing.limo'
CAD=ROOT/'experiments/garden-auger-child-d-grips.limo'
BUILD=ROOT/'.build/clamshell-detail/current-assembly/d-grip'
REPORT=ROOT/'d-grip-geometry-review.json'
RADIUS=12.
CENTER_Y=193.75
CENTER_Z=-14.
BED_Z=-20.6
GRIP_START=-98.
GRIP_END=89.
PIN_CENTERS=[(-23.,112.),(23.,112.),(-36.,203.),(16.,203.)]


def contact_region_area(triangles,x_limit,keep_greater):
    """Clip flat triangles at a region boundary before summing contact area."""
    total=0.
    for triangle in triangles:
        points=list(triangle[:,:2]);clipped=[]
        for p,q in zip(points,points[1:]+points[:1]):
            a=(p[0]>=x_limit) if keep_greater else (p[0]<=x_limit)
            b=(q[0]>=x_limit) if keep_greater else (q[0]<=x_limit)
            if a:clipped.append(p)
            if a!=b:clipped.append(p+(x_limit-p[0])/(q[0]-p[0])*(q-p))
        if len(clipped)>=3:
            v=np.array(clipped)
            total+=abs(float(np.dot(v[:,0],np.roll(v[:,1],-1))-np.dot(v[:,1],np.roll(v[:,0],-1))))/2
    return total


def locator(c,x,y):
    for operation,body,points in [
        ('join',46,[(0,-.4),(2.,-.4),(2.,2.2),(1.4,2.8),(0,2.8)]),
        ('cut',26,[(0,-.2),(2.35,-.2),(2.15,.2),(2.15,3.2),(0,3.2)])]:
        name=f'Case locator {x:g} {y:g} {operation}'
        sketch_at(c,name,[(x+r,z) for r,z in points],(0,y,0))
        c.call('solid_revolve',{'sketch_name':name,'profile_indices':[0],
            'axis_origin':{'x':x,'y':0},'axis_direction':{'x':0,'y':1},
            'angle_deg':360,'flip':False,'operation':operation,'target_body_ids':[body]})
        assert not c.call('solid_scene')['errors']


def rounded_ends(c):
    body=next(b for b in c.call('solid_scene')['bodies'] if b['id']==46)
    ends=[e['id'] for e in body['edges'] if len(e['points'])>=2
          and any(all(abs(p['x']-x)<1e-7 for p in e['points']) for x in [GRIP_START,GRIP_END])]
    assert ends, 'No D-grip end edges'
    before=live_model(c)
    trials=[]
    for radius in [1.2,.8]:
        try:
            c.call('solid_fillet',{'body_id':46,'edge_ids':ends,'radius':radius,'tangent_chain':False})
            assert not c.call('solid_scene')['errors']
            mesh,_=export_mesh(c,46)
            assert mesh.is_watertight and mesh.is_volume
            return {'radius_mm':radius,'edge_count':len(ends),'status':'native end rounds and closed export passed','rejected_trials':trials}
        except (RuntimeError,AssertionError) as error:
            trials.append({'radius_mm':radius,'error':str(error)})
            c.call('cad_load_project_model',{'model_json':json.dumps(before)})
    return {'status':'native end-round trials rejected; unchanged round D cross-section retained','rejected_trials':trials}


def main():
    BUILD.mkdir(parents=True,exist_ok=True)
    original=read_model(SOURCE);candidate=copy.deepcopy(original)
    candidate['document']['name']='Garden auger - child-size D grips on lower housing'
    handle=next(s for s in candidate['sketches'] if s['feature_id']==49)
    handle['basis']['origin'][0]=GRIP_START
    plane=next(p for p in candidate['datum_planes'] if p['datum_id']==handle['plane']['datum_id'])
    plane['basis']['origin'][0]=GRIP_START
    plane['source']['distance']=GRIP_START
    next(e for e in candidate['extrudes'] if e['feature_id']==50)['extent']['distance']=GRIP_END-GRIP_START
    dz=BED_Z-CENTER_Z;half=math.sqrt(RADIUS**2-dz**2)
    start=math.atan2(dz,half);end=math.atan2(dz,-half)+2*math.pi
    profile(handle,[(CENTER_Y-half,BED_Z),(CENTER_Y+half,BED_Z)],
            {1:((CENTER_Y,CENTER_Z),RADIUS,start,end)})
    # These depend on the superseded paired handles and their old edge keys.
    obsolete=set(range(317,333))|set(range(354,362))
    for f in candidate['document']['history']['features']:
        if f['id'] in obsolete:f['suppressed']=True
    report={'source':str(SOURCE.relative_to(ROOT)),'source_sha256':digest(SOURCE),
        'ownership':'Both complete grips belong to lower housing; upper closes the central mechanism.',
        'profile':{'rounded_diameter_mm':2*RADIUS,'width_y_mm':2*RADIUS,
            'height_z_mm':CENTER_Z+RADIUS-BED_Z,'flat_land_width_mm':2*half,
            'center_y_mm':CENTER_Y,'center_z_mm':CENTER_Z,'bed_z_mm':BED_Z,
            'top_z_mm':CENTER_Z+RADIUS,'overall_x_span_mm':GRIP_END-GRIP_START,
            'x_ends_mm':[GRIP_START,GRIP_END],'clear_grip_lengths_mm':[55.,55.]},
        'locators':{'pin_centers_xy_mm':PIN_CENTERS,'pin_diameter_mm':4.,'socket_diameter_mm':4.3,
                    'pin_projection_mm':2.8,'socket_depth_mm':3.2,'all_pins_on_lower':True},
        'scope':'Child-size comfort candidate. Age is not a fit measurement; grip comfort and loaded strength need physical trials.',
        'printer_command_sent':False}
    with CadClient() as c:
        report['engine_sha256']=digest(c.executable)
        c.call('cad_load_project_model',{'model_json':json.dumps(original)})
        before=c.call('solid_scene');assert not before['errors']
        old={bid:export_mesh(c,bid)[0] for bid in [26,46]}
        c.call('cad_load_project_model',{'model_json':json.dumps(candidate)})
        scene=c.call('solid_scene');assert not scene['errors'],scene['errors']
        print('D profile recomputes with both grips on lower housing',flush=True)
        # The old upper handle supplied the cable-channel roof. Keep a local
        # cheek around that rear route rather than regrowing the entire arm.
        Builder(c).box('Upper rear cable cheek',(12,180.6,34,206.5,0,20.6),'join',[26])
        Builder(c).box('Lower rear cable cheek',(12,180.6,34,206.5,-20.6,0),'join',[46])
        m=live_model(c);history=m['document']['history']['features']
        for fid in [157,159,161,278]:
            f=next(f for f in history if f['id']==fid);history.remove(f);history.append(f)
        c.call('cad_load_project_model',{'model_json':json.dumps(m)})
        assert not c.call('solid_scene')['errors']
        for bid in [26,46]:
            body=next(b for b in c.call('solid_scene')['bodies'] if b['id']==bid)
            edges=vertical_edges(body,lambda p:abs(abs(p['x'])-34)<1e-7 and abs(p['y']-107.9)<1e-7)
            assert len(edges)==2,(bid,edges)
            c.call('solid_fillet',{'body_id':bid,'edge_ids':edges,'radius':6.,'tangent_chain':False})
            assert not c.call('solid_scene')['errors']
        report['end_rounds']=rounded_ends(c)
        print('Housing front corners and grip end treatment checked',flush=True)
        for x,y in PIN_CENTERS:locator(c,x,y)
        final=save_project(c,CAD)
        scene=c.call('solid_scene');assert not scene['errors'],scene['errors']
        bodies={b['id']:b for b in scene['bodies']}
        for bid in [1,15,90,216,221]:assert bodies[bid]['mesh']==next(b for b in before['bodies'] if b['id']==bid)['mesh']
        assert final['body_appearances']==original['body_appearances']
        report['unchanged_mesh_body_ids']=[1,15,90,216,221]
        report['housing']={}
        for bid in [26,46]:
            mesh,raw=export_mesh(c,bid)
            assert mesh.is_watertight and mesh.is_volume and component_count(mesh)==1
            native_plane(bodies[bid],2,20.6 if bid==26 else -20.6)
            z=20.6 if bid==26 else -20.6
            triangles=mesh.triangles
            flat=np.all(np.abs(triangles[:,:,2]-z)<1e-7,axis=1)
            areas=mesh.area_faces
            contact=float(areas[flat].sum())
            item={'before_volume_mm3':old[bid].volume,'after_volume_mm3':mesh.volume,
                  'flat_bed_area_mm2':contact}
            if bid==46:
                assert np.allclose(mesh.bounds[:,0],[GRIP_START,GRIP_END],rtol=0,atol=1e-7)
                item['left_grip_flat_area_mm2']=contact_region_area(triangles[flat],-43,False)
                item['right_grip_flat_area_mm2']=contact_region_area(triangles[flat],34,True)
                item['flat_area_region_method']='Flat triangles clipped at X -43 and X +34 before area summation'
                assert min(item['left_grip_flat_area_mm2'],item['right_grip_flat_area_mm2'])>800
                grip_vertices=mesh.vertices[np.abs(mesh.vertices[:,0])>45]
                assert grip_vertices[:,2].max()<=CENTER_Z+RADIUS+1e-6
                item['outer_grip_bounds_mm']=[grip_vertices.min(0).tolist(),grip_vertices.max(0).tolist()]
            else:
                assert abs(mesh.bounds[:,0]).max()<45
                assert contact>2500
            report['housing'][str(bid)]=item
        nominal=c.call('assembly_interference_check',{'occurrence_ids':[3,6,7,8,14,16],'clearance_threshold_mm':2})
        assert nominal['exact'] and not any(p['interfering'] for p in nominal['pairs']),nominal
        report['nominal_assembly']=nominal
        report['preflight']=c.call('solid_export_preflight',{'body_ids':[26,46,15,90,216,221]})
        assert report['preflight']['ok'] and not report['preflight']['timeline_errors']
        (BUILD/'scene.json').write_text(json.dumps(scene))
    report['cad']=str(CAD.relative_to(ROOT));report['cad_sha256']=digest(CAD)
    REPORT.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: D grips, flat lands, retained components and nominal assembly',flush=True)


if __name__=='__main__':main()
