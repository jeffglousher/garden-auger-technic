"""Qualify the D-grip clamshell and retain native fit/print witnesses."""
import argparse
import itertools
import json
import math
from pathlib import Path

import numpy as np
from cad_client import CadClient
from build_servo_rear_fit_test import read_model,digest,native_plane
from review_snug_servo_nest import native_cylinder,set_pose,pairs
from refine_geometry import probe_occurrence
from check_cable_route import sweep_probe,check as cable_check

ROOT=Path(__file__).resolve().parents[1]
CAD=ROOT/'experiments/garden-auger-child-d-grips.limo'
REPORT=ROOT/'d-grip-validation.json'
BUILD=ROOT/'.build/clamshell-detail/current-assembly/d-grip'


def main():
    global CAD,REPORT,BUILD
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--solid-frame',action='store_true')
    parser.add_argument('--outer-envelope',action='store_true')
    parser.add_argument('--chamfer-envelope',action='store_true')
    parser.add_argument('--ingress-flange',action='store_true')
    parser.add_argument('--simple-print',action='store_true')
    parser.add_argument('--build-root',type=Path)
    args=parser.parse_args()
    if args.simple_print:args.ingress_flange=True
    if args.ingress_flange:args.chamfer_envelope=True
    if args.chamfer_envelope:args.outer_envelope=True
    if args.solid_frame:
        CAD=ROOT/'experiments/garden-auger-solid-frame.limo'
        REPORT=ROOT/'solid-frame-validation.json'
        BUILD=ROOT/'.build/clamshell-detail/current-assembly/d-grip/solid-frame'
    if args.outer_envelope:
        CAD=ROOT/'experiments/garden-auger-rounded-envelope.limo'
        REPORT=ROOT/'outer-envelope-validation.json'
        BUILD=ROOT/'.build/clamshell-detail/current-assembly/outer-envelope'
    if args.chamfer_envelope:
        CAD=ROOT/'experiments/garden-auger-chamfer-envelope.limo'
        REPORT=ROOT/'chamfer-envelope-validation.json'
        BUILD=ROOT/'.build/clamshell-detail/current-assembly/chamfer-envelope'
    if args.ingress_flange:
        CAD=ROOT/'experiments/garden-auger-ingress-flange.limo'
        REPORT=ROOT/'ingress-flange-validation.json'
        BUILD=ROOT/'.build/clamshell-detail/current-assembly/ingress-flange'
    if args.simple_print:
        CAD=ROOT/'experiments/garden-auger-simple-print.limo'
        REPORT=ROOT/'simple-print-validation.json'
        BUILD=ROOT/'.build/clamshell-detail/current-assembly/simple-print'
    review='simple-print-geometry-review.json' if args.simple_print else 'ingress-flange-geometry-review.json' if args.ingress_flange else 'chamfer-envelope-geometry-review.json' if args.chamfer_envelope else 'outer-envelope-geometry-review.json' if args.outer_envelope else 'solid-frame-geometry-review.json' if args.solid_frame else 'd-grip-geometry-review.json'
    if args.build_root:BUILD=args.build_root
    proof=json.loads((ROOT/review).read_text())
    assert digest(CAD)==proof['cad_sha256']
    original=read_model(ROOT/proof['source']);final=read_model(CAD)
    sections=[('ear-nest',46,'xy',-.1,164.15),('servo-floor',46,'xz',179.9,-10),
              ('rear-wall',46,'xy',-5,193),('square-socket',15,'xz',134,0),
              ('adapter-seat',216,'xy',0,149),('pla-bushing',221,'xz',125,0)]
    report={'cad_sha256':digest(CAD),'engine_sha256':None,'printer_command_sent':False}
    with CadClient() as c:
        report['engine_sha256']=digest(c.executable)
        c.call('cad_load_project_model',{'model_json':json.dumps(original)})
        old=[c.call('solid_section_review',{'body_id':b,'plane':p,'offset_mm':o,'probe_mm':v,'deflection_mm':.01}) for _,b,p,o,v in sections]
        c.call('cad_load_project_model',{'model_json':json.dumps(final)})
        report['retained_section_probes']=[]
        for (name,b,p,o,v),before in zip(sections,old):
            after=c.call('solid_section_review',{'body_id':b,'plane':p,'offset_mm':o,'probe_mm':v,'deflection_mm':.01})
            a=[[s['start_mm'],s['end_mm']] for s in before['probe_spans']]
            d=[[s['start_mm'],s['end_mm']] for s in after['probe_spans']]
            if args.outer_envelope and name in ['ear-nest','servo-floor','rear-wall']:
                assert len(a)==len(d)==2,(name,a,d)
                assert np.allclose([a[0][1],a[1][0]],[d[0][1],d[1][0]],rtol=0,atol=1e-7),(name,a,d)
                assert min(r-l for l,r in d)>=2.8,(name,d)
                report['retained_section_probes'].append({'name':name,'before_spans_mm':a,'after_spans_mm':d,
                    'retained_cavity_limits_mm':[d[0][1],d[1][0]],
                    'scope':'Functional cavity limits unchanged; outside stock intentionally trimmed/blended.'})
            elif name=='rear-wall':
                # The approved grip ends move; retain the actual central
                # case-wall intervals rather than requiring the old span.
                clip=lambda spans:[[max(l,-43.),min(r,34.)] for l,r in spans if r>-43 and l<34]
                assert np.allclose(clip(a),clip(d),rtol=0,atol=1e-7),(name,a,d)
                report['retained_section_probes'].append({'name':name,'before_full_spans_mm':a,
                    'after_full_spans_mm':d,'retained_core_spans_mm':clip(d),
                    'scope':'Central case X -43 to +34 unchanged; outer grip ends intentionally shortened.'})
            else:
                assert np.allclose(a,d,rtol=0,atol=1e-7),(name,a,d)
                report['retained_section_probes'].append({'name':name,'spans_mm':d})
        bodies={b['id']:b for b in c.call('solid_scene')['bodies']}
        for bid in [26,46]:
            for axis,value in [(1,162.65),(1,165.65),(0,-38.2),(0,18.2),(1,194),(2,20.6 if bid==26 else -20.6)]:native_plane(bodies[bid],axis,value)
            native_cylinder(bodies[bid],17.8)
        for bid,r in [(15,14),(221,14.3),(221,17)]:native_cylinder(bodies[bid],r)
        for bid,axis,value in [(221,1,120.85),(221,1,130.65),(216,0,-7),(216,0,7),(15,0,-7.2),(15,0,7.2)]:native_plane(bodies[bid],axis,value)
        report['screw_stacks']=[]
        report['driver_access']=[]
        for x,y in [(-27,118.5),(27,118.5),(-36,196.8),(16,196.8)]:
            head=native_cylinder(bodies[26],3.1,axis=2,location={'x':x,'y':y})
            insert=native_cylinder(bodies[46],2,axis=2,location={'x':x,'y':y})
            levels=lambda w:sorted({e['circle']['center']['z'] for e in w['native_boundary_circles']})
            assert np.allclose(levels(head),[14,20.6],rtol=0,atol=1e-7)
            assert np.allclose(levels(insert),[-6.7,0],rtol=0,atol=1e-7)
            report['screw_stacks'].append({'xy_mm':[x,y],'head':head,'insert':insert})
            bid,oid=probe_occurrence(c,f'Inspection driver {x} {y}',x,y,2.25,17,60)
            test=c.call('assembly_interference_check',{'occurrence_ids':[6,7,oid],'clearance_threshold_mm':2})
            ps=pairs(test,{bid},{26,46});assert not any(p['interfering'] for p in ps)
            report['driver_access'].append({'xy_mm':[x,y],'pairs':ps})
        c.call('cad_load_project_model',{'model_json':json.dumps(final)})
        report['grip_section']=c.call('solid_section_review',{'body_id':46,'plane':'yz','offset_mm':75,'deflection_mm':.01})
        (BUILD/'grip-section.json').write_text(json.dumps(report['grip_section'],indent=2))
        print('Six retained sections, screw stacks and four driver approaches pass',flush=True)
        report['locator_controls']=[]
        for x,y in proof['locators']['pin_centers_xy_mm']:
            bid,oid=probe_occurrence(c,f'Inspection 4mm locator {x} {y}',x,y,2,.3,2.2)
            for shift,blocked in [((.14,0,0),False),((-.14,0,0),False),((.16,0,0),True),((0,.14,0),False),((0,.16,0),True)]:
                set_pose(c,oid,shift)
                test=c.call('assembly_interference_check',{'occurrence_ids':[6,oid],'clearance_threshold_mm':2})
                ps=pairs(test,{bid},{26});assert any(p['interfering'] for p in ps)==blocked,(x,y,shift,ps)
                report['locator_controls'].append({'xy_mm':[x,y],'shift_mm':shift,'blocked':blocked,'pairs':ps})
            set_pose(c,oid)
        c.call('cad_load_project_model',{'model_json':json.dumps(final)})
        report['closure_samples']=[]
        for lift in [10,2,.5,.1,0]:
            set_pose(c,6,(0,0,lift))
            test=c.call('assembly_interference_check',{'occurrence_ids':[3,6,7,8,14,16],'clearance_threshold_mm':2})
            assert test['exact'] and not any(p['interfering'] for p in test['pairs']),(lift,test)
            report['closure_samples'].append({'upper_lift_mm':lift,'exact':True,'interfering':False})
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
        report['cable_envelopes']=[]
        for diameter in [4.,5.,6.2]:
            c.call('cad_load_project_model',{'model_json':json.dumps(final)})
            bid,oid=sweep_probe(c,diameter)
            check=cable_check(c,bid,oid)
            assert any(p['interfering'] for p in check['housing_pairs'])==(diameter==6.2)
            report['cable_envelopes'].append({'diameter_mm':diameter,'result':check})
        report['sample_counts']={'sections':6,'driver_approaches':4,'locator_controls':20,'closure':5,
            'bushing_capture':4,'auger_rotation_endfloat':24,'coupled_poses':9,'continuous_cable_sweeps':3}
    report['scope']='Nominal sampled geometry, assumed cable/driver envelopes and flat contact. Physical comfort, loaded strength, actual engagement, threads and dirty use remain unqualified.'
    REPORT.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: D-grip closure, drive motion, relocated locators and rear cable route',flush=True)


if __name__=='__main__':main()
