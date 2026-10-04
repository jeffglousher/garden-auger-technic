"""Verify chassis-only capture, produce the no-ring variant and fit coupon."""

import base64
import copy
import json
import math
from pathlib import Path

from cad_client import CadClient
from cad_build import Builder,profile,save_project
from model_cleanup import clean_checked
from design_parameters import housing_profile

ROOT=Path(__file__).resolve().parents[1]


def native_export(c,body_ids,path):
    result=c.call('solid_export_3mf',{'body_ids':body_ids,'scope':'definition',
        'linear_deflection':.08,'angular_deflection':.2,'slicer_target':'bambu_studio'})
    path.write_bytes(base64.b64decode(result['bytes_base64']))


def verify(c,model,label):
    c.call('cad_load_project_model',{'model_json':json.dumps(model)})
    structure=model['assembly']['component_structure']
    auger=next(o['id'] for o in structure['occurrences'] if o['component_id']==8)
    adapter=next(o['id'] for o in structure['occurrences'] if o['component_id']==14)
    horn_component=next(d['id'] for d in structure['definitions'] if '1906-0025-0032' in d['name'])
    horn=next(o['id'] for o in structure['occurrences'] if o['component_id']==horn_component)
    reports=[]
    for position,shift,angle in [('centered',0,0),('push stop',.3,0),('pull stop',-.3,0),
                                 ('rotation 45',0,45),('rotation 90',0,90)]:
        q=[0,math.sin(math.radians(angle)/2),0,math.cos(math.radians(angle)/2)]
        for occurrence,dy in [(auger,shift),(adapter,0),(horn,0)]:
            c.call('assembly_set_occurrence_pose',{'occurrence_id':occurrence,
                'local_pose':{'translation':[0,dy,0],'rotation':q}})
        result=c.call('assembly_interference_check',{'clearance_threshold_mm':.1})
        assert result['exact']
        assert not any(p['interfering'] for p in result['pairs'] if {p['body_a'],p['body_b']}!={15,90}),result
        reports.append({'position':position,'auger_shift_mm':shift,'angle_degrees':angle,
                        'exact':True,'unintended_overlap_mm3':0})
    # Crossing either intended travel limit must hit the chassis itself.
    for dy in [-.31,.31]:
        c.call('assembly_set_occurrence_pose',{'occurrence_id':auger,
            'local_pose':{'translation':[0,dy,0],'rotation':[0,0,0,1]}})
        c.call('assembly_set_occurrence_pose',{'occurrence_id':adapter,
            'local_pose':{'translation':[0,0,0],'rotation':[0,0,0,1]}})
        result=c.call('assembly_interference_check',{'clearance_threshold_mm':.1})
        stops=[p for p in result['pairs'] if p['interfering'] and 15 in {p['body_a'],p['body_b']}
               and bool({26,46}&{p['body_a'],p['body_b']})]
        assert stops,(label,dy,result)
        reports.append({'position':'overtravel blocked','auger_shift_mm':dy,
                        'blocked_by':'chassis','exact':True})
    print(label,'travel / rotation clear, chassis blocks both overtravel directions',flush=True)
    # Isolate the journal/thrust-seat clearance at the worst permitted drive
    # axis offset. This is not an off-axis spline-fit test.
    c.call('cad_load_project_model',{'model_json':json.dumps(model)})
    for dx,dz in [(0.5,0),(-0.5,0),(0,0.5),(0,-0.5)]:
        c.call('assembly_set_occurrence_pose',{'occurrence_id':auger,
            'local_pose':{'translation':[dx,0,dz],'rotation':[0,0,0,1]}})
        result=c.call('assembly_interference_check',{'clearance_threshold_mm':.01})
        assert result['exact']
        assert not any(p['interfering'] for p in result['pairs']
            if 15 in {p['body_a'],p['body_b']} and bool({26,46}&{p['body_a'],p['body_b']})),result
        reports.append({'position':'journal offset','offset_xz_mm':[dx,dz],
                        'auger_chassis_overlap_mm3':0,'exact':True})
    return reports


def main():
    model=json.loads((ROOT/'.build/model.json').read_text())
    parts=json.loads((ROOT/'.build/parts.json').read_text());ring=parts['sleeve']
    reports={}
    with CadClient() as c:
        reports['with_PLA_sleeve']=verify(c,model,'PLA sleeve assembly')
        c.call('cad_load_project_model',{'model_json':json.dumps(model)})
        save_project(c,ROOT/'garden-auger-drive.nbcad')
        # Test the slide path only against the auger, before placing in the
        # clamshell. The sleeve has no key and no separate locking object.
        ring_component=next(d['id'] for d in model['assembly']['component_structure']['definitions'] if ring in d['body_ids'])
        ring_occurrence=next(o['id'] for o in model['assembly']['component_structure']['occurrences'] if o['component_id']==ring_component)
        for dy in [24,12,4,0]:
            c.call('assembly_set_occurrence_pose',{'occurrence_id':ring_occurrence,
                'local_pose':{'translation':[0,dy,0],'rotation':[0,0,0,1]}})
            result=c.call('assembly_interference_check',{'clearance_threshold_mm':.1})
            assert result['exact']
            assert not any(p['interfering'] for p in result['pairs'] if ring in {p['body_a'],p['body_b']}
                           and bool({15,90}&{p['body_a'],p['body_b']})),result
        reports['sleeve_slide_path']={'positions_mm':[24,12,4,0],'exact':True,'auger_overlap_mm3':0}
        # Direct-bearing alternative uses the SAME auger / servo adapter.
        bare=copy.deepcopy(model)
        bare['document']['name']='Garden auger - direct chassis bearing, no sleeve'
        seat=next(s for s in bare['sketches'] if s['name']=='Chassis integral thrust stops and journal seat')
        profile(seat,housing_profile(False))
        ring_feature=next(r['feature_id'] for r in bare['revolves'] if ring in r.get('new_body_ids',[]))
        next(f for f in bare['document']['history']['features'] if f['id']==ring_feature)['suppressed']=True
        structure=bare['assembly']['component_structure']
        structure['definitions']=[d for d in structure['definitions'] if d['id']!=ring_component]
        structure['occurrences']=[o for o in structure['occurrences'] if o['component_id']!=ring_component]
        bare['body_appearances']=[a for a in bare['body_appearances'] if a['body_id']!=ring]
        c.call('cad_load_project_model',{'model_json':json.dumps(bare)})
        bare,_=clean_checked(c,bare,None)
        reports['without_sleeve']=verify(c,bare,'Direct chassis assembly')
        c.call('cad_load_project_model',{'model_json':json.dumps(bare)})
        save_project(c,ROOT/'garden-auger-no-ring.nbcad')
        (ROOT/'.build/no-ring-model.json').write_text(json.dumps(bare))
        (ROOT/'.build/no-ring-scene.json').write_text(json.dumps(c.call('solid_scene')))
        native_export(c,[26,46,15,90,216],ROOT/'.build/no-ring-raw.3mf')
        # Preserve both thrust stops in the physical coupon.
        c.call('cad_load_project_model',{'model_json':json.dumps(model)})
        b=Builder(c)
        b.box('Crop chassis capture fit check',(-120,153.0,120,220,-35,35),'cut',[26,46])
        b.box('Crop large journal fit coupon',(-35,-6,35,105,-35,35),'cut',[15])
        fit=c.call('cad_project_model');fit=json.loads(fit) if isinstance(fit,str) else fit
        fit['document']['name']='Garden auger - chassis capture and large square fit check'
        fit['visibility']['hidden_body_ids']=[1,90]
        next(d for d in fit['assembly']['component_structure']['definitions'] if d['id']==8)['body_ids']=[15]
        for o in fit['assembly']['component_structure']['occurrences']:
            if o['component_id']==3:o['visible']=False
        c.call('cad_load_project_model',{'model_json':json.dumps(fit)})
        save_project(c,ROOT/'garden-auger-fit-check.nbcad')
        native_export(c,[26,46,15,216,ring],ROOT/'.build/fit-raw.3mf')
    (ROOT/'.build/checks.json').write_text(json.dumps(reports,indent=2))
    print('Both design variants and representative fit check saved',flush=True)


if __name__=='__main__':main()
