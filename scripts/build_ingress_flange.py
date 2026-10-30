"""Add an integral rotating dirt shield; preserve the fitted auger and housing.

Private installed native CAD only. The owned ingress-flange evidence sublane
has a 90 MiB ceiling. This is a noncontact shield, not a certified dirt seal.
"""
import json
from pathlib import Path

from cad_client import CadClient
from cad_build import Builder,save_project
from build_servo_rear_fit_test import read_model,digest,native_plane
from revise_clamshell import export_mesh
from review_snug_servo_nest import set_pose,pairs
from print_packer import component_count

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'experiments/garden-auger-chamfer-envelope.limo'
CAD=ROOT/'experiments/garden-auger-ingress-flange.limo'
BUILD=ROOT/'.build/clamshell-detail/current-assembly/ingress-flange'
REPORT=ROOT/'ingress-flange-geometry-review.json'
# Coordinates are axial Y and radius about the existing auger Y axis.
PROFILE=[(99.,0.),(99.,23.4),(99.6,24.),(101.7,24.),(102.3,23.4),(102.3,0.)]
WRAPPED=[(99.8,0.),(99.8,22.8),(101.,24.),(105.8,24.),(105.8,21.6),(102.3,21.6),(102.3,0.)]


def main():
    BUILD.mkdir(parents=True,exist_ok=True)
    original=read_model(SOURCE)
    previous=json.loads((ROOT/'chamfer-envelope-geometry-review.json').read_text())
    assert previous['cad_sha256']==digest(SOURCE)
    report={'source':str(SOURCE.relative_to(ROOT)),'source_sha256':digest(SOURCE),
        'profile':previous['profile'],'locators':previous['locators'],
        'shield':{'profile_y_radius_mm':PROFILE,'outside_diameter_mm':48.,
            'axial_span_y_mm':[99.,102.3],'broad_web_thickness_mm':3.3,
            'outer_edge_thickness_mm':2.1,'edge_chamfers_mm':.6,
            'housing_lip_front_y_mm':103.9,'housing_lip_max_radius_mm':20.6,
            'nominal_rear_face_gap_mm':1.6,'nominal_outer_radius_overhang_mm':3.4,
            'conditional_axial_allowance_mm':.5,'conditional_radial_axis_offset_mm':.5,
            'conditional_rear_face_gap_mm':1.1,'conditional_outer_radius_overhang_mm':2.9,
            'scope':'Nominal CAD dimensions and existing conditional assembly allowances; no new measured hardware or print tolerance.'},
        'printer_command_sent':False}
    with CadClient() as c:
        report['engine_sha256']=digest(c.executable)
        c.call('cad_load_project_model',{'model_json':json.dumps(original)})
        old_scene=c.call('solid_scene');assert not old_scene['errors']
        old_core,_=export_mesh(c,15)
        # Test the tempting wraparound option first: the closed skirt can
        # trap the fixed upper lip during ordinary vertical clamshell closure.
        Builder(c).revolve('Rejected trial - overlapping rearward shield skirt',WRAPPED,'join',[15])
        set_pose(c,6,(0,0,2.))
        trial=c.call('assembly_interference_check',{'occurrence_ids':[6,8],'clearance_threshold_mm':2})
        collision=pairs(trial,{26},{15,90})
        assert any(p['interfering'] for p in collision),collision
        report['rejected_wraparound_trial']={'profile_y_radius_mm':WRAPPED,'upper_lift_mm':2.,
            'native_pairs':collision,'reason':'Rearward skirt blocks the existing upper-half closure path.'}
        print('Rejected wraparound skirt: native upper closure collision at 2 mm lift',flush=True)
        c.call('cad_load_project_model',{'model_json':json.dumps(original)})
        Builder(c).revolve('Integral auger dirt shield - forward flange with open rear clearance',PROFILE,'join',[15])
        c.call('cad_set_document_name',{'name':'Garden auger - integral rotating ingress flange'})
        scene=c.call('solid_scene');assert not scene['errors']
        bodies={b['id']:b for b in scene['bodies']}
        for bid in [1,26,46,90,216,221]:
            assert bodies[bid]['mesh']==next(b for b in old_scene['bodies'] if b['id']==bid)['mesh'],bid
        report['unchanged_mesh_body_ids']=[1,26,46,90,216,221]
        core,_=export_mesh(c,15)
        assert core.is_watertight and core.is_volume and component_count(core)==1
        assert core.volume>old_core.volume
        report['auger_core']={'before_volume_mm3':old_core.volume,'after_volume_mm3':core.volume,
            'added_volume_mm3':core.volume-old_core.volume,'bounds_mm':core.bounds.tolist(),'closed_connected':True}
        report['native_rear_flange_plane']=native_plane(bodies[15],1,102.3)
        report['native_fixed_lip_plane']=native_plane(bodies[26],1,103.9)
        report['nominal_assembly']=c.call('assembly_interference_check',{'occurrence_ids':[3,6,7,8,14,16],'clearance_threshold_mm':2})
        assert report['nominal_assembly']['exact'] and not any(p['interfering'] for p in report['nominal_assembly']['pairs'])
        final=save_project(c,CAD)
        assert final['body_appearances']==original['body_appearances']
        # All previous construction records are retained; only the two new
        # shield sketch/revolve records are added to the original history.
        for key in ['sketches','extrudes','revolves','fillets','chamfers','datum_planes','body_features']:
            by_id={json.dumps(v,sort_keys=True) for v in final[key]}
            assert all(json.dumps(v,sort_keys=True) in by_id for v in original[key]),key
        report['retained_original_feature_records']=True
        (BUILD/'scene.json').write_text(json.dumps(scene))
        # Inspect only the shield at the larger conditional axial/radial
        # allowance. The real collar is intentionally travel-limited sooner.
        c.call('cad_load_project_model',{'model_json':json.dumps(original)})
        shield=Builder(c).revolve('Inspection only - isolated rotating shield',PROFILE,'new_body',[])['created_body_id']
        c.call('assembly_create_component',{'name':'Inspection only - flange envelope','body_ids':[shield],'absorb_promoted_bodies':True})
        model=c.call('cad_project_model');model=json.loads(model) if isinstance(model,str) else model
        oid=next(o['id'] for o in model['assembly']['component_structure']['occurrences'] if o['name']=='Inspection only - flange envelope')
        report['isolated_shield_samples']=[]
        for dx,dz in [(0,0),(.5,0),(-.5,0),(0,.5),(0,-.5)]:
            for dy in [-.5,.5]:
                set_pose(c,oid,(dx,dy,dz))
                check=c.call('assembly_interference_check',{'occurrence_ids':[6,7,oid],'clearance_threshold_mm':3})
                ps=pairs(check,{shield},{26,46})
                assert ps and not any(p['interfering'] for p in ps),(dx,dy,dz,ps)
                report['isolated_shield_samples'].append({'shift_mm':[dx,dy,dz],'pairs':ps})
        print('Final flange: unchanged housing/drive fits, nominal assembly and 10 isolated shield poses pass',flush=True)
    report['cad']=str(CAD.relative_to(ROOT));report['cad_sha256']=digest(CAD)
    REPORT.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
