"""Derive a replacement PLA bushing from fixed shaft/housing constraints.

Run in the existing numpy/trimesh/manifold3d/pillow uv environment. This task
owns up to 10 MB new evidence in the existing .build/clamshell-detail lane;
retain native models/reports until physical review and recovery coverage settle.
"""
import itertools
import json
import math
from pathlib import Path
import numpy as np
from cad_client import CadClient
from cad_build import profile,save_project
from build_servo_rear_fit_test import read_model,digest,native_plane
from revise_clamshell import export_mesh
from review_snug_servo_nest import native_cylinder,set_pose,pairs
from print_packer import component_count
from prepare_bambu_latest import UPRIGHT

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'experiments/garden-auger-rounded-housing-test.limo'
CAD=ROOT/'experiments/garden-auger-constraint-bushing-test.limo'
STL=ROOT/'print-parts/pla-constraint-fit-bushing.stl'
REPORT=ROOT/'constraint-bushing-review.json'
BUILD=ROOT/'.build/clamshell-detail'
SHAFT_DIAMETER=28.0
SEAT_DIAMETER=35.6
SEAT_FRONT,SEAT_REAR=120.3,131.2
BORE_DIAMETER=SHAFT_DIAMETER+.6
OUTSIDE_DIAMETER=34.0  # Existing radial fit is retained; no diameter guessing.
END_GAP=.55
FRONT,REAR=SEAT_FRONT+END_GAP,SEAT_REAR-END_GAP
INNER_LEAD=.4
OUTER_LEAD=.5


def main():
    preserved={str(p.relative_to(ROOT)):digest(p) for p in [SOURCE,
        ROOT/'garden-auger-upper-servo-sparse-test.3mf',
        ROOT/'garden-auger-upper-rounded-housing-sparse-test.3mf',
        ROOT/'garden-auger-lower-rounded-housing-sparse-test.3mf',
        ROOT/'print-parts/direct-drive/pla-full-wear-sleeve.stl']}
    m=read_model(SOURCE)
    shape=next(s for s in m['sketches'] if s['name']=='Plain loose PLA wear sleeve')
    bore=BORE_DIAMETER/2;outer=OUTSIDE_DIAMETER/2
    points=[(FRONT,bore+INNER_LEAD),(FRONT+INNER_LEAD,bore),
        (REAR-INNER_LEAD,bore),(REAR,bore+INNER_LEAD),
        (REAR,outer-OUTER_LEAD),(REAR-OUTER_LEAD,outer),
        (FRONT+OUTER_LEAD,outer),(FRONT,outer-OUTER_LEAD)]
    r={'source':str(SOURCE.relative_to(ROOT)),'source_sha256':digest(SOURCE),
        'design_intent':'Bushing conforms to fixed journal and housing; its old length is not a requirement.',
        'fixed_constraints':{'journal_diameter_mm':SHAFT_DIAMETER,'seat_diameter_mm':SEAT_DIAMETER,
            'seat_y_mm':[SEAT_FRONT,SEAT_REAR],'seat_span_mm':SEAT_REAR-SEAT_FRONT,
            'adjacent_front_throat_diameter_mm':31,'adjacent_rear_throat_diameter_mm':29.6},
        'bushing':{'bore_diameter_mm':BORE_DIAMETER,'outer_diameter_mm':OUTSIDE_DIAMETER,
            'length_mm':REAR-FRONT,'y_mm':[FRONT,REAR],'center_y_mm':(FRONT+REAR)/2,
            'front_end_gap_mm':END_GAP,'rear_end_gap_mm':END_GAP,
            'total_axial_freedom_mm':2*END_GAP,'inner_lead_mm':INNER_LEAD,
            'outer_lead_mm':OUTER_LEAD,'straight_bore_length_mm':REAR-FRONT-2*INNER_LEAD,
            'full_outer_land_length_mm':REAR-FRONT-2*OUTER_LEAD,
            'minimum_end_outer_diameter_mm':OUTSIDE_DIAMETER-2*OUTER_LEAD,
            'inner_diametral_clearance_mm':BORE_DIAMETER-SHAFT_DIAMETER,
            'outer_diametral_clearance_mm':SEAT_DIAMETER-OUTSIDE_DIAMETER,
            'profile_y_radius_mm':points},
        'scope':'Nominal constraint-derived candidate; manufacture, bearing wear and loaded performance remain unqualified.',
        'printer_command_sent':False,'preserved_files':preserved}
    with CadClient(stderr_path=BUILD/'constraint-bushing-engine.log') as c:
        c.call('cad_load_project_model',{'model_json':json.dumps(m)})
        before=c.call('solid_scene');assert not before['errors']
        profile(shape,points)
        m['document']['name']='Garden auger - constraint-fit PLA bushing'
        c.call('cad_load_project_model',{'model_json':json.dumps(m)})
        scene=c.call('solid_scene');assert not scene['errors']
        bodies={b['id']:b for b in scene['bodies']}
        for bid in [1,15,90,26,46,216]:
            assert next(b for b in before['bodies'] if b['id']==bid)['mesh']==bodies[bid]['mesh']
        final=save_project(c,CAD)
        assert final['body_appearances']==m['body_appearances']
        r['unchanged_mesh_body_ids']=[1,15,90,26,46,216]
        r['engine_sha256']=digest(c.executable)
        r['native_bushing_witnesses']={
            'bore':native_cylinder(bodies[221],bore),'outer':native_cylinder(bodies[221],outer),
            'front':native_plane(bodies[221],1,FRONT),'rear':native_plane(bodies[221],1,REAR)}
        nominal=c.call('assembly_interference_check',{'occurrence_ids':[3,6,7,8,14,16],'clearance_threshold_mm':2})
        assert nominal['exact'] and not any(p['interfering'] for p in nominal['pairs'])
        r['nominal_assembly']=nominal
        r['closure_samples']=[]
        for lift in [10,2,.5,.1,0]:
            set_pose(c,6,(0,0,lift))
            check=c.call('assembly_interference_check',{'occurrence_ids':[6,7,8,16],'clearance_threshold_mm':2})
            ps=pairs(check,{221},{26,46,15,90})
            assert not any(p['interfering'] for p in ps)
            r['closure_samples'].append({'upper_lift_mm':lift,'bushing_pairs':ps})
        set_pose(c,6)
        r['bushing_float_and_retention_controls']=[]
        for y in [-.5,.5,-.56,.56]:
            set_pose(c,16,(0,y,0))
            check=c.call('assembly_interference_check',{'occurrence_ids':[6,7,8,16],'clearance_threshold_mm':2})
            ps=pairs(check,{221},{26,46,15,90})
            blocked=any(p['interfering'] for p in ps)
            assert blocked==(abs(y)>.55),(y,ps)
            r['bushing_float_and_retention_controls'].append({'axial_shift_mm':y,'blocked':blocked,'pairs':ps})
        set_pose(c,16)
        r['auger_rotation_samples']=[]
        for angle in range(0,360,30):
            for y in [-.29,.29]:
                set_pose(c,8,(0,y,0),axis=1,degrees=angle)
                check=c.call('assembly_interference_check',{'occurrence_ids':[6,7,8,16],'clearance_threshold_mm':2})
                ps=pairs(check,{15,90},{26,46,221})
                assert not any(p['interfering'] for p in ps)
                r['auger_rotation_samples'].append({'degrees':angle,'axial_mm':y,'pairs':ps})
        set_pose(c,8)
        r['coupled_assembly_samples']=[]
        for shift in [(0,0,0)]+list(itertools.product([-.19,.19],[-.14,.14],[-.19,.19])):
            for oid in [8,14]:set_pose(c,oid,shift)
            c.call('assembly_set_occurrence_pose',{'occurrence_id':3,'local_pose':{
                'translation':[shift[0],148.7+shift[1],shift[2]],'rotation':[math.sqrt(.5),0,0,math.sqrt(.5)]}})
            check=c.call('assembly_interference_check',{'occurrence_ids':[3,6,7,8,14,16],'clearance_threshold_mm':2})
            assert check['exact'] and not any(p['interfering'] for p in check['pairs'])
            r['coupled_assembly_samples'].append({'shift_mm':shift,'result':check})
        # Restore the saved nominal model before printing/exporting.
        c.call('cad_load_project_model',{'model_json':json.dumps(final)})
        mesh,raw=export_mesh(c,221)
        assert mesh.is_watertight and mesh.is_volume and component_count(mesh)==1
        native_vertices=mesh.vertices.copy()
        posed=native_vertices@UPRIGHT.T;minimum=posed.min(0)
        mesh.vertices=posed-minimum
        mesh.export(STL)
        placement=np.array([128,128,0])-minimum
        c.call('upsert_named_view',{'name':'Print - PLA constraint-fit bushing',
            'camera':{'position':[180,60,90],'target':[128,128,5],'up':[0,0,1]},
            'visible_body_ids':[221],'occurrence_offsets':[{'occurrence_id':16,
                'translation':placement.tolist(),'rotation':[-math.sqrt(.5),0,0,math.sqrt(.5)]}],
            'print_layout':True,'print_bed':{'name':'Bambu X2D main','size_mm':[256,256,261]}})
        pre=c.call('solid_export_preflight',{'body_ids':[221],'named_view':'Print - PLA constraint-fit bushing'})
        assert pre['ok'] and not pre['timeline_errors']
        assert not any(i['code'] in ['below_bed','outside_bed','possible_overlap'] for i in pre['layout']['issues'])
        r['native_print_preflight']=pre
        r['stl']=str(STL.relative_to(ROOT));r['stl_sha256']=digest(STL)
        r['print_rotation']=UPRIGHT.tolist();r['print_centered_vertices']=(native_vertices-(native_vertices.min(0)+native_vertices.max(0))/2).tolist()
        r['print_faces']=mesh.faces.tolist()
        (BUILD/'constraint-bushing-scene.json').write_text(json.dumps(scene))
        (BUILD/'constraint-bushing-native.3mf').write_bytes(raw)
    assert all(digest(ROOT/p)==h for p,h in preserved.items())
    r.update(cad=str(CAD.relative_to(ROOT)),cad_sha256=digest(CAD))
    REPORT.write_text(json.dumps(r,indent=2)+'\n')
    print('Constraint-derived bushing passes native assembly/closure/rotation/capture checks',flush=True)


if __name__=='__main__':main()
