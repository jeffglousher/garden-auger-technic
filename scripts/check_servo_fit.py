"""Independent drawing-to-solid audit and regression for the servo fit failure.

The temporary probe uses literal dimensions from the attached drawing, rather
than the production reference or its shared parameters. It is never saved or
exported as a print part. Full solid ears conservatively fill the unshown slots.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

import numpy as np
import trimesh

from cad_build import Builder
from cad_client import CadClient
from geometry_measurements import section_segments

ROOT=Path(__file__).resolve().parents[1]
BASELINE='6816a19f59809b0960d3e3b408ffa8cbd29a3a23'


def read_model(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:return json.loads(archive.read('model.json'))


def model_value(client):
    value=client.call('cad_project_model')
    return json.loads(value) if isinstance(value,str) else value


def independent_probe(client):
    before={b['id'] for b in client.call('solid_scene')['bodies']}
    # Shaft tip Y148.7; rear Y148.7+41.5; front rear-37.5.
    Builder(client).box('Inspection only - diagram case',(-30.5,152.7,10,190.2,-10,10),'new_body',[])
    body=next(iter({b['id'] for b in client.call('solid_scene')['bodies']}-before))
    # Rear/underside of ears Y190.2-24.7=165.5; front 165.5-2.7=162.8.
    Builder(client).box('Inspection only - diagram left ear',(-38,162.8,-30.5,165.5,-10,10),'join',[body])
    Builder(client).box('Inspection only - diagram right ear',(10,162.8,18,165.5,-10,10),'join',[body])
    name='Independent dimensioned servo fit probe - do not print'
    client.call('assembly_create_component',{'name':name,'body_ids':[body],'absorb_promoted_bodies':True})
    model=model_value(client)
    occurrence=next(o['id'] for o in model['assembly']['component_structure']['occurrences'] if o['name']==name)
    return body,occurrence


def pair_check(client,body,occurrence,translation,fixed=(26,46)):
    client.call('assembly_set_occurrence_pose',{'occurrence_id':occurrence,
        'local_pose':{'translation':translation,'rotation':[0,0,0,1]}})
    # Include the deliberately separated insertion/closure poses, not only
    # bounding boxes close enough to collide at the final seated position.
    result=client.call('assembly_interference_check',{'clearance_threshold_mm':50})
    pairs=[{k:p[k] for k in ('body_a','body_b','interfering','minimum_clearance_mm','overlap_volume_mm3')}
           for p in result['pairs'] if body in {p['body_a'],p['body_b']} and bool(set(fixed)&{p['body_a'],p['body_b']})]
    assert result['exact'] and len(pairs)==len(fixed),pairs
    return {'probe_translation_mm':translation,'exact':True,'housing_pairs':pairs}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=ROOT/'garden-auger-direct-drive.nbcad')
    parser.add_argument('--output',type=Path,default=ROOT/'servo-fit-verification.json')
    args=parser.parse_args()
    data=args.project.read_bytes();model=read_model(data)
    prior=subprocess.check_output(['git','show',f'{BASELINE}:garden-auger-direct-drive.nbcad'],cwd=ROOT)
    before=read_model(prior)
    regression=[];fits=[];insertion=[];closure=[]
    with CadClient() as client:
        client.call('cad_load_project_model',{'model_json':json.dumps(before)})
        false=client.call('assembly_interference_check',{'clearance_threshold_mm':.001})
        false_pairs=[p for p in false['pairs'] if 1 in {p['body_a'],p['body_b']} and bool({26,46}&{p['body_a'],p['body_b']})]
        assert false['exact'] and len(false_pairs)==2 and not any(p['interfering'] for p in false_pairs)
        body,occurrence=independent_probe(client)
        for shift,label in [(0,'Drawing envelope at shaft-tip datum'),(2.7,'Real servo seated in erroneous old ear slots')]:
            test=pair_check(client,body,occurrence,[0,shift,0])
            assert all(p['interfering'] for p in test['housing_pairs']),test
            test['case']=label;regression.append(test)
        client.call('cad_load_project_model',{'model_json':json.dumps(model)})
        scene=client.call('solid_scene');assert not scene['errors'],scene['errors']
        raw=next(b['mesh'] for b in scene['bodies'] if b['id']==1)
        mesh=trimesh.Trimesh(np.array(raw['positions']).reshape(-1,3),np.array(raw['indices']).reshape(-1,3),process=False)
        section=section_segments(mesh,-30).reshape(-1,2)
        assert np.allclose(section.min(axis=0),[-30.5,-10]) and np.allclose(section.max(axis=0),[10,10])
        assert np.allclose(mesh.bounds[:,2],[-41.5,-4]),mesh.bounds
        ears=mesh.vertices[(mesh.vertices[:,0]<-30.6)|(mesh.vertices[:,0]>10.1)]
        assert np.allclose([ears[:,2].min(),ears[:,2].max()],[-16.8,-14.1])
        assert np.allclose([ears[:,0].min(),ears[:,0].max()],[-38,18])
        assert model['body_appearances']==before['body_appearances']
        for original in before['assembly']['component_structure']['occurrences']:
            current=next(o for o in model['assembly']['component_structure']['occurrences'] if o['id']==original['id'])
            assert current['local_pose']==original['local_pose'],original['id']
        body,occurrence=independent_probe(client)
        for shift in [-.19,0,.19]:
            for dx,dz in [(0,0),(.3,0),(-.3,0),(0,.3),(0,-.3),(.3,.3),(-.3,-.3)]:
                test=pair_check(client,body,occurrence,[dx,shift,dz])
                assert not any(p['interfering'] for p in test['housing_pairs']),test
                fits.append(test)
        for shift in [-.21,.21]:
            test=pair_check(client,body,occurrence,[0,shift,0])
            assert any(p['interfering'] for p in test['housing_pairs']),test
            test['case']='Ear stops block excess axial motion';fits.append(test)
        for height in [30,20,12,6,3,0]:
            test=pair_check(client,body,occurrence,[0,0,height],fixed=(46,))
            assert not any(p['interfering'] for p in test['housing_pairs']),test
            insertion.append(test)
        pair_check(client,body,occurrence,[0,0,0])
        for height in [30,12,6,3,0]:
            client.call('assembly_set_occurrence_pose',{'occurrence_id':6,
                'local_pose':{'translation':[0,0,height],'rotation':[0,0,0,1]}})
            test=pair_check(client,body,occurrence,[0,0,0],fixed=(26,))
            assert not any(p['interfering'] for p in test['housing_pairs']),test
            test['upper_lift_mm']=height;closure.append(test)
        # Discard every temporary probe operation before ending inspection.
        client.call('cad_load_project_model',{'model_json':json.dumps(model)})
        preflight=client.call('solid_export_preflight')
        assert preflight['ok'] and not preflight['timeline_errors'],preflight
    dimensions={'drawing_case_length':40,'catalog_case_length_cleared':40.5,'case_width':20,
        'tip_to_rear':41.5,'case_axial_height':37.5,'ear_underside_to_rear':24.7,
        'ear_thickness':2.7,'ear_span':56,'mount_hole_center_spacing':49,'shaft_from_right_edge':10,
        'case_y':[152.7,190.2],'ear_y':[162.8,165.5],'ear_pocket_y':[162.6,165.7],
        'case_pocket_y':[151.7,191.7],'case_pocket_x':[-30.9,10.4],'case_pocket_z':[-10.4,10.4],
        'available_rear_case_length_from_ear_underside':26.2,
        'required_rear_case_length_from_ear_underside':24.7,
        'rear_clearance_nominal':1.5,'rear_clearance_at_nominal_ear_travel_limit':1.3,
        'old_ear_y':[165.5,168.2],'old_ear_pocket_y':[165.3,168.4],
        'old_available_rear_case_length_from_ear_underside':23.5,'old_rear_case_deficit':1.2}
    # Check saved cut locations and measured native body sections separately.
    sketches={s['name']:s for s in model['sketches']};extrudes={e['feature_id']:e for e in model['extrudes']}
    assert np.isclose(sketches['Sketch62']['basis']['origin'][1],165.7)
    assert np.isclose(extrudes[183]['extent']['distance'],3.1)
    points=np.array([e['position'][key] for _,e in sketches['Sketch45']['snapshot']['entities'] if e['type']=='point' for key in ('x','y')]).reshape(-1,2)
    assert np.allclose(points.min(axis=0),[-30.9,-10.4]) and np.allclose(points.max(axis=0),[10.4,10.4])
    mounting=sketches['Sketch3']['snapshot']['entities']
    centers=[]
    for ids in ([1,2,3,4],[17,18,19,20]):
        centers.append(np.mean([dict(mounting)[i]['position']['x'] for i in ids]))
    assert np.isclose(centers[1]-centers[0],49)
    report={'source_project':args.project.name,'source_project_sha256':hashlib.sha256(data).hexdigest(),
        'baseline_commit':BASELINE,'baseline_project_sha256':hashlib.sha256(prior).hexdigest(),
        'root_cause':'24.7 mm was applied to the upper ear face instead of the underside, shifting reference ears and housing slots rearward by 2.7 mm. Mount-hole envelope centers were also 52 instead of 49 mm apart.',
        'dimension_authority':'User attachment 1000015289.png; supplied drawing controls axial datums. Larger 40.5 mm catalog plan length is cleared conservatively.',
        'dimensions_mm':dimensions,'old_reference_produced_false_clearance_pass':True,
        'independent_native_failure_reproduction':regression,'drawing_probe_fit_and_endstop_checks':fits,
        'lower_half_servo_drop_in_path':insertion,'upper_half_closure_with_servo':closure,
        'native_reference_case_and_ear_sections_measured':True,'assembly_poses_and_materials_preserved':True,
        'temporary_probe_saved_or_exported':False,'native_preflight':preflight,
        'scope':'Dimensions shown in drawing and a conservative full-ear envelope. Unshown case fillets, mounting-slot diameters, cable boot, internal thread and printed behavior are not certified by this check.'}
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'drawing_probe_fit_checks':len(fits),'lower_insertion_checks':len(insertion),
                     'upper_closure_checks':len(closure),'old_failure_reproduced':True,
                     'ear_shift_correction_mm':-2.7,'rear_case_clearance_nominal_mm':1.5},indent=2),flush=True)


if __name__=='__main__':main()
