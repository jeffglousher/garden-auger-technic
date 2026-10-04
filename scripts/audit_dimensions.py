"""Check native drive dimensions, relative rotation, and insert surrounding walls."""

import json
import math
from pathlib import Path
import numpy as np
import trimesh

from cad_client import CadClient
from design_parameters import *

ROOT=Path(__file__).resolve().parents[1]


def section_segments(mesh,z):
    return trimesh.intersections.mesh_plane(mesh,[0,0,1],[0,0,z])[:,:,:2]


def segment_distance(point,segments):
    a=segments[:,0];delta=segments[:,1]-a
    length=(delta*delta).sum(axis=1)
    t=np.clip(((point-a)*delta).sum(axis=1)/np.maximum(length,1e-20),0,1)
    return np.linalg.norm(a+t[:,None]*delta-point,axis=1)


def vertical_hits(mesh,xy):
    t=mesh.triangles;q=np.array(xy)
    v0=t[:,1,:2]-t[:,0,:2];v1=t[:,2,:2]-t[:,0,:2];v2=q-t[:,0,:2]
    den=v0[:,0]*v1[:,1]-v0[:,1]*v1[:,0];ok=abs(den)>1e-9
    a=np.divide(v2[:,0]*v1[:,1]-v2[:,1]*v1[:,0],den,out=np.zeros_like(den),where=ok)
    b=np.divide(v0[:,0]*v2[:,1]-v0[:,1]*v2[:,0],den,out=np.zeros_like(den),where=ok)
    hit=ok&(a>=-1e-8)&(b>=-1e-8)&(a+b<=1+1e-8)
    z=t[:,0,2]+a*(t[:,1,2]-t[:,0,2])+b*(t[:,2,2]-t[:,0,2])
    return sorted(set(np.round(z[hit],4)))


def main():
    model=json.loads((ROOT/'.build/model.json').read_text())
    scene=json.loads((ROOT/'.build/scene.json').read_text())
    sketches={s['name']:s for s in model['sketches']}
    def points(name):
        return [e['position'] for _,e in sketches[name]['snapshot']['entities'] if e['type']=='point']
    widths={n:2*max(p['x'] for p in points(n)) for n in ['Sketch99','Sketch100']}
    assert abs(widths['Sketch99']-14)<1e-9 and abs(widths['Sketch100']-14.4)<1e-9
    peg_length=next(e['extent']['distance'] for e in model['extrudes'] if e['feature_id']==289)
    move=next(e['translation']['y'] for e in model['body_features'] if e['feature_id']==299)
    peg_root=sketches['Sketch99']['basis']['origin'][1]+move
    peg_tip=peg_root-peg_length
    mouth=sketches['Sketch100']['basis']['origin'][1]
    depth=next(e['extent']['distance'] for e in model['extrudes'] if e['feature_id']==291)
    assert abs(peg_tip-129.5)<1e-8 and abs(mouth-139.5)<1e-8
    engagement=mouth-peg_tip
    radius=1.2;corner_center=widths['Sketch100']/2-radius
    min_hub_wall=14-(math.sqrt(2)*corner_center+radius)
    inserts=sketches['Sketch56']
    centers=[(e['center']['x'],e['center']['y']) for _,e in inserts['snapshot']['entities'] if e['type']=='circle']
    assert len(centers)==4
    assert all(e['radius']==2 for _,e in inserts['snapshot']['entities'] if e['type']=='circle')
    hole_depth=next(e['extent']['distance'] for e in model['extrudes'] if e['feature_id']==161)
    assert hole_depth==6.7
    lower=next(b for b in scene['bodies'] if b['id']==46)['mesh']
    mesh=trimesh.Trimesh(vertices=np.array(lower['positions']).reshape(-1,3),
                        faces=np.array(lower['indices']).reshape(-1,3),process=False)
    upper=next(b for b in scene['bodies'] if b['id']==26)['mesh']
    top=trimesh.Trimesh(vertices=np.array(upper['positions']).reshape(-1,3),
                       faces=np.array(upper['indices']).reshape(-1,3),process=False)
    seats=[]
    for center in centers:
        wall_samples=[]
        for z in [-.05,-2.85,-5.65]:
            segments=section_segments(mesh,z)
            dist=segment_distance(np.array(center),segments)
            # Ignore the circular pilot wall, retaining every other boundary.
            outside=dist[dist>2.15]
            wall_samples.append(float(outside.min())-2.3)
        wall=min(wall_samples)
        assert wall-.225>=1.6,(center,wall)
        assert not vertical_hits(top,center),('Blocked screw hole',center)
        hits=vertical_hits(mesh,center)
        assert len(hits)==2 and hits[0]<=-8 and abs(hits[1]+6.7)<1e-4,('Blocked insert pocket',center,hits)
        seat=vertical_hits(top,(center[0]+2.5,center[1]))[-1]
        expected=8 if center[1]<150 else 12.7
        assert abs(seat-expected)<1e-4,(center,seat)
        screw=12 if center[1]<150 else 18
        screw_engagement=screw-seat
        assert 3<=screw_engagement<=5.7
        seats.append({'xy_mm':center,'minimum_sampled_radial_wall_after_insert_mm':wall,
            'minimum_wall_with_print_and_insert_allowance_mm':wall-.225,
            'screw_hole_open':True,'insert_pocket_open':True,'screw_head_seat_z_mm':float(seat),
            'screw_length_mm':screw,'screw_thread_engagement_mm':float(screw_engagement),
            'screw_bottom_room_mm':float(hole_depth-screw_engagement)})
    relative=[]
    with CadClient() as c:
        c.call('cad_load_project_model',{'model_json':json.dumps(model)})
        auger=next(o['id'] for o in model['assembly']['component_structure']['occurrences'] if o['component_id']==8)
        for angle,expect in [(1.8,False),(2.2,True)]:
            q=[0,math.sin(math.radians(angle)/2),0,math.cos(math.radians(angle)/2)]
            c.call('assembly_set_occurrence_pose',{'occurrence_id':auger,
                'local_pose':{'translation':[0,0,0],'rotation':q}})
            result=c.call('assembly_interference_check',{'clearance_threshold_mm':.01})
            assert result['exact']
            contact=any(p['interfering'] for p in result['pairs'] if {p['body_a'],p['body_b']}=={15,216})
            assert contact==expect,(angle,result)
            relative.append({'relative_angle_deg':angle,'peg_socket_overlap':contact,'exact':True})
    # The geometrical leading-corner contact angle for these offset profiles.
    theta=math.degrees(math.asin((7.2-1)/(6*math.sqrt(2)))-math.pi/4)
    report={'square':{'male_across_flats_mm':widths['Sketch99'],'male_corner_radius_mm':1,
        'female_across_flats_mm':widths['Sketch100'],'female_corner_radius_mm':radius,
        'normal_clearance_mm':.2,'socket_depth_mm':depth,
        'engagement_nominal_mm':engagement,'engagement_min_mm':engagement-.3,
        'peg_to_socket_bottom_nominal_mm':depth-engagement,
        'peg_to_socket_bottom_min_mm':depth-engagement-.3,
        'flange_gap_nominal_mm':peg_root-mouth,'flange_gap_min_mm':peg_root-mouth-.3,
        'hub_diameter_mm':28,'straight_hub_radial_wall_mm':min_hub_wall,
        'minimum_radial_hub_wall_mm':min_hub_wall-.5,
        'geometric_backlash_total_deg':2*theta,'relative_rotation_checks':relative},
        'heat_set_inserts':{'quantity':4,'model':'ruthex RX-M3x5.7','outer_diameter_mm':4.6,
            'length_mm':5.7,'pilot_diameter_mm':4.0,'pilot_depth_mm':hole_depth,
            'bottom_room_mm':hole_depth-5.7,'seats':seats},
        'servo':{'model':'INJORA INJS035-360','published_spline_diameter_mm':5.9,
            'published_spline_teeth':25,'selected_horn':'goBILDA 1906-0025-0032',
            'horn_mount_nominal_CAD_verified':True,'physical_fit_tested':False,
            'source':'source/horn-1906-0025-0032/1906-0025-0032.STEP',
            'attachment':'4 x M4 x 6 ISO 4762; metal 25T spline; M3 x 6 center screw',
            'pilot_diameter_mm':PILOT_DIAMETER,'pilot_depth_mm':PILOT_DEPTH,
            'flange_diameter_mm':FLANGE_DIAMETER,'flange_thickness_mm':FLANGE_THICKNESS}}
    # Worst-case arithmetic, not root-sum-square. Printed +/-0.10 values
    # are inspection limits; they must be qualified on the chosen printer.
    h=HORN_FACE_Y-HOUSING_FRONT_STOP
    tip=HORN_FACE_Y-peg_tip
    a=mouth-COLLAR_FRONT
    span=HOUSING_REAR_STOP-HOUSING_FRONT_STOP
    width=COLLAR_REAR-COLLAR_FRONT
    flange=next(e['extent']['distance'] for e in model['extrudes'] if e['feature_id']==293)
    t=PRINT_SIZE_TOLERANCE;ht=HORN_FACE_LOCATION_TOLERANCE
    emin=a-h+tip-(2*t+ht)
    emax=a+span-width-h+tip+(4*t+ht)
    gap=h-flange-a-span+width
    stack={'method':'worst-case arithmetic; acceptance limits, not measured printer capability',
        'printed_critical_size_tolerance_mm':t,'installed_horn_face_location_tolerance_mm':ht,
        'installed_horn_face_from_front_stop_mm':h,
        'adapter_tip_to_horn_face_mm':tip,'collar_front_to_socket_mouth_mm':a,
        'collar_capture_span_mm':span,'collar_width_mm':width,
        'end_float_min_mm':span-width-2*t,'end_float_max_mm':span-width+2*t,
        'square_engagement_min_mm':emin,'square_engagement_max_mm':emax,
        'socket_bottom_clearance_min_mm':depth-t-emax,
        'flange_to_hub_gap_min_mm':gap-(4*t+ht),
        'journal_radial_clearance_min_mm':(HOUSING_JOURNAL_DIAMETER-JOURNAL_DIAMETER-2*t)/2,
        'maximum_installed_drive_axis_offset_mm':MAX_DRIVE_AXIS_OFFSET,
        'journal_offset_clearance_margin_mm':(HOUSING_JOURNAL_DIAMETER-JOURNAL_DIAMETER-2*t)/2-MAX_DRIVE_AXIS_OFFSET,
        'sleeve_combined_radial_float_min_mm':(SLEEVE_BORE-JOURNAL_DIAMETER-2*t+HOUSING_RING_CAVITY-SLEEVE_OD-2*t)/2,
        'square_flat_clearance_min_mm':(SOCKET-PEG-2*t)/2,
        'horn_pilot_diametral_clearance_min_mm':PILOT_DIAMETER-t-14.05,
        'horn_pilot_bottom_clearance_min_mm':PILOT_DEPTH-t-2.05,
        'M4_mount_thread_engagement_nominal_mm':6-(flange-SCREW_COUNTERBORE_DEPTH),
        'M4_mount_thread_engagement_min_mm':6-.1-(flange+t-SCREW_COUNTERBORE_DEPTH+t),
        'M4_head_recess_min_mm':SCREW_COUNTERBORE_DEPTH-t-4,
        'M4_hole_position_clearance_margin_mm':(SCREW_CLEARANCE-t-4)/2-.1-.05,
        'center_screw_nominal_thread_engagement_mm':3.4,
        'center_screw_thread_engagement_min_mm':3.1,
        'center_screw_thread_engagement_max_mm':3.7,
        'center_screw_seat_to_shaft_tip_acceptance_mm':[2.4,2.8],
        'center_screw_bottom_clearance_min_mm':.3,
        'purchased_part_inspection_limits':{'pilot_boss_max_mm':14.05,'boss_height_max_mm':2.05,
            'horn_hole_position_radial_error_max_mm':.05,
            'center_screw_available_thread_depth_min_mm':4.0},
        'incoming_limits_are_not_vendor_tolerances':True}
    assert emin>9 and stack['socket_bottom_clearance_min_mm']>1
    assert stack['flange_to_hub_gap_min_mm']>.7
    assert all(stack[k]>0 for k in ['end_float_min_mm','journal_offset_clearance_margin_mm',
        'square_flat_clearance_min_mm','horn_pilot_diametral_clearance_min_mm',
        'horn_pilot_bottom_clearance_min_mm','M4_hole_position_clearance_margin_mm'])
    report['tolerance_stack']=stack
    (ROOT/'dimension-audit.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
