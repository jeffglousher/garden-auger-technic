"""Independent retained sections, screw seats, and coupled-assembly checks."""
import itertools
import json
import math
from pathlib import Path
import numpy as np
from cad_client import CadClient
from build_servo_rear_fit_test import read_model,digest
from review_snug_servo_nest import native_cylinder,set_pose

ROOT=Path(__file__).resolve().parents[1]
CAD=ROOT/'experiments/garden-auger-clamshell-detail-test.limo'


def main():
    r=json.loads((ROOT/'clamshell-detail-review.json').read_text())
    assert digest(CAD)==r['cad_sha256']
    source=read_model(ROOT/r['source']);candidate=read_model(CAD)
    sections=[('ear-nest',46,'xy',-.1,164.15),('servo-floor',46,'xz',179.9,-10),
        ('rear-wall',46,'xy',-5,193),('square-socket',15,'xz',134,0),
        ('adapter-seat',216,'xy',0,149),('pla-bushing',221,'xz',125,0)]
    records=[]
    with CadClient() as c:
        c.call('cad_load_project_model',{'model_json':json.dumps(source)})
        before=[c.call('solid_section_review',{'body_id':b,'plane':p,'offset_mm':o,
            'probe_mm':v,'deflection_mm':.01}) for _,b,p,o,v in sections]
        c.call('cad_load_project_model',{'model_json':json.dumps(candidate)})
        boundary={'body_id':46,'plane':'xz','offset_mm':180,'probe_mm':-10,'deflection_mm':.01}
        try:
            c.call('solid_section_review',boundary)
            boundary_finding={'request':boundary,'status':'native section succeeded on this engine'}
        except RuntimeError as error:
            assert 'Section boundary is open' in str(error),error
            boundary_finding={'request':boundary,'status':'open-boundary hatching limitation',
                'error':str(error),'workaround_offset_mm':179.9,
                'upstream_finding':'https://github.com/limo-cad/Limo-CAD/issues/350#issuecomment-6072498034'}
        for (name,b,p,o,v),old in zip(sections,before):
            print('Section',name,flush=True)
            new=c.call('solid_section_review',{'body_id':b,'plane':p,'offset_mm':o,
                'probe_mm':v,'deflection_mm':.01})
            # Compare the selected material spans, not whole exterior sections.
            a=[[s['start_mm'],s['end_mm']] for s in old['probe_spans']]
            d=[[s['start_mm'],s['end_mm']] for s in new['probe_spans']]
            assert np.allclose(a,d,rtol=0,atol=1e-7),(name,a,d)
            records.append({'name':name,'native_material_probe_spans_unchanged':True,'spans_mm':d,
                'body_id':b,'plane':p,'offset_mm':o,'probe_mm':v})
        scene=c.call('solid_scene');bodies={b['id']:b for b in scene['bodies']}
        screws=[]
        for x,y in [(-27,118.5),(27,118.5),(-36,196.8),(16,196.8)]:
            head=native_cylinder(bodies[26],3.1,axis=2,location={'x':x,'y':y})
            levels=sorted({e['circle']['center']['z'] for e in head['native_boundary_circles']})
            assert np.allclose(levels,[14,20.6],rtol=0,atol=1e-7),levels
            insert=native_cylinder(bodies[46],2,axis=2,location={'x':x,'y':y})
            levels=sorted({e['circle']['center']['z'] for e in insert['native_boundary_circles']})
            assert np.allclose(levels,[-6.7,0],rtol=0,atol=1e-7),levels
            screws.append({'xy_mm':[x,y],'head':head,'insert':insert})
        coupled=[]
        for shift in [(0,0,0)]+list(itertools.product([-.19,.19],[-.14,.14],[-.19,.19])):
            for oid in [8,14]:set_pose(c,oid,shift)
            c.call('assembly_set_occurrence_pose',{'occurrence_id':3,'local_pose':{
                'translation':[shift[0],148.7+shift[1],shift[2]],
                'rotation':[math.sqrt(.5),0,0,math.sqrt(.5)]}})
            result=c.call('assembly_interference_check',{'occurrence_ids':[3,6,7,8,14,16],
                'clearance_threshold_mm':2})
            assert result['exact'] and not any(p['interfering'] for p in result['pairs']),(shift,result)
            coupled.append({'common_drive_translation_mm':shift,'result':result})
    r.update(retained_native_section_probes=records,native_equal_screw_stacks=screws,
             coupled_assembly_samples=coupled,native_section_boundary_finding=boundary_finding)
    (ROOT/'clamshell-detail-review.json').write_text(json.dumps(r,indent=2)+'\n')
    print('Six retained section probes, four native screw stacks and nine coupled poses passed',flush=True)


if __name__=='__main__':main()
