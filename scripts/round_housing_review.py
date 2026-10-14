"""Round only housing exteriors and audit the unchanged loose PLA sleeve.

Uses the existing headless/native review lane. New output budget: 20 MB;
preserve recovery models and native evidence until physical review settles.
Run with the same uv numpy/trimesh/manifold3d/pillow environment as detail CAD.
"""
import copy
import json
import math
from pathlib import Path
import numpy as np
import trimesh
from cad_client import CadClient
from cad_build import profile,save_project
from slim_housing import rounded_profile
from build_servo_rear_fit_test import read_model,digest,native_plane
from revise_clamshell import export_mesh
from review_snug_servo_nest import native_cylinder,set_pose,pairs
from print_packer import component_count

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'experiments/garden-auger-clamshell-detail-test.limo'
CAD=ROOT/'experiments/garden-auger-rounded-housing-test.limo'
REPORT=ROOT/'rounded-housing-review.json'
BUILD=ROOT/'.build/clamshell-detail'


def vertical_edges(body,predicate):
    return [e['id'] for e in body['edges'] if len(e['points'])==2
        and predicate(e['points'][0]) and predicate(e['points'][1])
        and abs(e['points'][0]['z']-e['points'][1]['z'])>5]


def main():
    preserved={str(p.relative_to(ROOT)):digest(p) for p in [SOURCE,
        ROOT/'garden-auger-upper-servo-sparse-test.3mf',
        ROOT/'garden-auger-lower-servo-sparse-test.3mf',
        ROOT/'garden-auger-upper-clamshell-detail-sparse-test.3mf',
        ROOT/'garden-auger-lower-clamshell-detail-sparse-test.3mf',
        ROOT/'print-parts/direct-drive/pla-full-wear-sleeve.stl']}
    source=read_model(SOURCE);candidate=copy.deepcopy(source)
    candidate['document']['name']='Garden auger - rounded housing test'
    handle=next(s for s in candidate['sketches'] if s['feature_id']==49)
    rounded_profile(handle,[(188,-20.6),(199.5,-20.6),(204,-16.1),(204,16.1),
        (199.5,20.6),(188,20.6),(183.5,16.1),(183.5,-16.1)],{i:4 for i in range(8)})
    for sketch in candidate['sketches']:
        if sketch['name'].startswith(('Bearing right shoulder','Bearing left shoulder',
                                     'Servo right shoulder','Servo left shoulder')):
            points=[(e['position']['x'],e['position']['y'])
                for _,e in sketch['snapshot']['entities'] if e['type']=='point']
            direction=1 if 'right' in sketch['name'] else -1
            sign=1 if 'upper' in sketch['name'] else -1
            start=math.pi if direction==1 else 0;end=sign*math.pi/2
            if start-end>math.pi:end+=2*math.pi
            profile(sketch,points,{0:((points[1][0],0),9.5,min(start,end),max(start,end))})
    report={'source':str(SOURCE.relative_to(ROOT)),'source_sha256':digest(SOURCE),
        'status':'Rounded exterior candidate; sleeve unchanged pending clarification of physical complaint.',
        'radii_mm':{'grip_cross_section':4,'grip_tip_corners':4,'front_side_corners':6,
                    'curved_side_relief':9.5},
        'scope':'Exterior material removal only. Functional cavities, locators, screw stacks, cable route and all non-housing parts retained.',
        'preserved_files':preserved,'printer_command_sent':False}
    with CadClient(stderr_path=BUILD/'rounded-engine.log') as c:
        report['engine_sha256']=digest(c.executable)
        c.call('cad_load_project_model',{'model_json':json.dumps(source)})
        before=c.call('solid_scene');assert not before['errors']
        old={bid:export_mesh(c,bid)[0] for bid in [26,46]}
        c.call('cad_load_project_model',{'model_json':json.dumps(candidate)})
        for bid in [26,46]:
            for label,radius,predicate in [
                ('front side corners',6,lambda p:abs(abs(p['x'])-34)<1e-7 and abs(p['y']-107.9)<1e-7),
                ('grip tip corners',4,lambda p:abs(abs(p['x'])-100)<1e-7 and
                    (abs(p['y']-183.5)<1e-7 or abs(p['y']-204)<1e-7))]:
                body=next(b for b in c.call('solid_scene')['bodies'] if b['id']==bid)
                edges=vertical_edges(body,predicate)
                assert len(edges)==(2 if radius==6 else 4),(bid,label,edges)
                c.call('solid_fillet',{'body_id':bid,'edge_ids':edges,'radius':radius,'tangent_chain':False})
                assert not c.call('solid_scene')['errors']
                print(bid,label,'rounded',flush=True)
        scene=c.call('solid_scene');bodies={b['id']:b for b in scene['bodies']}
        for bid in [1,15,90,216,221]:
            assert next(b for b in before['bodies'] if b['id']==bid)['mesh']==bodies[bid]['mesh']
        final=save_project(c,CAD)
        assert final['body_appearances']==source['body_appearances']
        report['unchanged_mesh_body_ids']=[1,15,90,216,221]
        report['housing_meshes']={}
        for bid in [26,46]:
            mesh,raw=export_mesh(c,bid)
            assert mesh.is_watertight and mesh.is_volume and component_count(mesh)==1
            # Fillets must remove housing stock, never add stock into fitted cavities.
            added=trimesh.boolean.difference([mesh,old[bid]],engine='manifold')
            # Curved-face tessellation changes at trimmed fillet boundaries.
            # This is a mesh screening allowance, never a fit uncertainty.
            assert abs(added.volume)<.1,(bid,added.volume)
            report['housing_meshes'][str(bid)]={'before_volume_mm3':old[bid].volume,
                'after_volume_mm3':mesh.volume,'removed_mm3':old[bid].volume-mesh.volume,
                'tessellated_added_stock_mm3':added.volume,'mesh_screen_limit_mm3':.1,
                'watertight_connected':True,
                'retained_bed_plane':native_plane(bodies[bid],2,20.6 if bid==26 else -20.6)}
        ring={
            'shaft_journal':native_cylinder(bodies[15],14),
            'sleeve_bore':native_cylinder(bodies[221],14.3),
            'sleeve_outer':native_cylinder(bodies[221],17),
            'housing_seat':native_cylinder(bodies[46],17.8),
            'sleeve_front':native_plane(bodies[221],1,120.6),
            'sleeve_rear':native_plane(bodies[221],1,131),
            'housing_front_stop':native_plane(bodies[46],1,120.3),
            'housing_rear_stop':native_plane(bodies[46],1,131.2)}
        report['sleeve_audit']={'native_witnesses':ring,'shaft_diameter_mm':28,
            'bore_diameter_mm':28.6,'inner_diametral_clearance_mm':.6,
            'inner_radial_clearance_mm':.3,'outer_diameter_mm':34,
            'seat_diameter_mm':35.6,'outer_diametral_clearance_mm':1.6,
            'outer_radial_clearance_mm':.8,'sleeve_length_mm':10.4,
            'seat_length_mm':10.9,'front_axial_gap_mm':.3,'rear_axial_gap_mm':.2,
            'total_axial_float_mm':.5,'radial_wall_mm':2.7,
            'interpretation':'Loose floating sleeve, not a press-fit ring or electrical slip ring. CAD has clearance, not an oversized OD collision. Manufactured dimensions and complaint axis remain unconfirmed.'}
        stl=trimesh.load(ROOT/'print-parts/direct-drive/pla-full-wear-sleeve.stl',force='mesh')
        native,_=export_mesh(c,221)
        # STL tessellation order differs; compare native vertices against stored print vertices.
        matches=[]
        for sign in [-1,1]:
            # Stored STL stands on an annular end at the bed origin;
            # native definition lies along assembly Y. Compare rigid poses.
            placed=native.vertices[:,[0,2,1]]*np.array([1,-sign,sign])
            placed-=placed.min(0)
            delta=max(min(np.linalg.norm(stl.vertices-v,axis=1)) for v in placed)
            if len(placed)==len(stl.vertices) and delta<1e-5:matches.append((sign,delta))
        assert matches,'Sleeve STL geometry differs after print-pose normalization'
        report['sleeve_audit']['existing_sleeve_stl_matches_native_vertices']=True
        report['sleeve_audit']['stl_print_pose_y_axis_sign']=matches[0][0]
        report['sleeve_audit']['stl_float32_max_vertex_delta_mm']=matches[0][1]
        nominal=c.call('assembly_interference_check',{'occurrence_ids':[3,6,7,8,14,16],'clearance_threshold_mm':2})
        assert nominal['exact'] and not any(p['interfering'] for p in nominal['pairs'])
        report['nominal_assembly']=nominal
        motion=[]
        for angle in range(0,360,30):
            for travel in [-.29,.29]:
                set_pose(c,8,(0,travel,0),axis=1,degrees=angle)
                result=c.call('assembly_interference_check',{'occurrence_ids':[6,7,8,16],'clearance_threshold_mm':2})
                ps=pairs(result,{15,90},{26,46,221})
                assert ps and not any(p['interfering'] for p in ps)
                motion.append({'angle_deg':angle,'axial_mm':travel,'pairs':ps})
        set_pose(c,8)
        report['auger_sleeve_motion_samples']=motion
        for shift in [(.1,0,0),(.2,0,0),(0,.1,0),(0,.2,0)]:
            set_pose(c,6,shift)
            result=c.call('assembly_interference_check',{'occurrence_ids':[6,7],'clearance_threshold_mm':1})
            assert any(p['interfering'] for p in result['pairs'])==(max(shift)>.15)
        set_pose(c,6)
        (BUILD/'rounded-scene.json').write_text(json.dumps(scene))
    for path,h in preserved.items():assert digest(ROOT/path)==h,path
    report.update(cad=str(CAD.relative_to(ROOT)),cad_sha256=digest(CAD))
    REPORT.write_text(json.dumps(report,indent=2)+'\n')
    print('Rounded native CAD and ring tolerance audit complete',flush=True)


if __name__=='__main__':main()
