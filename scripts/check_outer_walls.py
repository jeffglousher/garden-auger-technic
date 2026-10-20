"""Sample native walls/bed contact of the rounded envelope, not global GD&T."""
import hashlib,json
from pathlib import Path
import numpy as np
from cad_client import CadClient
from build_servo_rear_fit_test import read_model,digest
from build_d_grips import contact_region_area
from revise_clamshell import export_mesh
from print_packer import component_count

ROOT=Path(__file__).resolve().parents[1]
CAD=ROOT/'experiments/garden-auger-rounded-envelope.limo'
REPORT=ROOT/'outer-envelope-wall-review.json'


def vertical_spans(section,y):
    crossings=[]
    for curve in section['section']:
        ps=curve['points']
        for p,q in zip(ps,ps[1:]):
            if min(p[0],q[0])<=y<max(p[0],q[0]):
                crossings.append(p[1]+(y-p[0])/(q[0]-p[0])*(q[1]-p[1]))
    zs=[]
    for z in sorted(crossings):
        if not zs or abs(z-zs[-1])>1e-7:zs.append(z)
    assert len(zs)%2==0,(y,zs)
    return list(zip(zs[::2],zs[1::2]))


def main():
    source=read_model(ROOT/'experiments/garden-auger-solid-frame.limo');final=read_model(CAD)
    # The component cavities, screw stacks, ear stops, cable path and grip
    # feature definitions remain exact. The exterior sketch is the exception.
    retained={}
    for key in ['sketches','extrudes','revolves','datum_planes','fillets']:
        by_id={v['feature_id']:v for v in final[key]}
        for item in source[key]:
            if item['feature_id']==40:continue
            assert by_id[item['feature_id']]==item,(key,item['feature_id'])
        retained[key]=[v for v in source[key] if v['feature_id']!=40]
    result={'cad':str(CAD.relative_to(ROOT)),'cad_sha256':digest(CAD),
        'retained_feature_definitions_sha256':hashlib.sha256(json.dumps(retained,sort_keys=True).encode()).hexdigest(),
        'section_deflection_mm':.01,'longitudinal_stock':[],'side_stock':[],'bed_contact':{},
        'scope':'Selected native section and mesh contact samples; not a global minimum-wall, strength or manufacturing-certification result.'}
    with CadClient() as c:
        result['engine_sha256']=digest(c.executable)
        c.call('cad_load_project_model',{'model_json':json.dumps(final)})
        for bid,x,ys in [(26,0,[108.5,110,114,121,125,130,140]),(46,0,[108.5,110,114,121,125,130,140]),
                         (26,-10.25,[155,164.15,176,189]),(46,-10.25,[155,164.15,176,189])]:
            section=c.call('solid_section_review',{'body_id':bid,'plane':'yz','offset_mm':x,'deflection_mm':.01})
            for y in ys:
                spans=vertical_spans(section,y);assert spans,(bid,x,y)
                span=max(spans,key=lambda s:s[1]) if bid==26 else min(spans,key=lambda s:s[0])
                thickness=span[1]-span[0]
                assert thickness>=2.799,(bid,x,y,span)
                result['longitudinal_stock'].append({'body':bid,'x_mm':x,'y_mm':y,'z_span_mm':span,'stock_mm':thickness})
        for y,z,label in [(164.15,0,'ear capture'),(186,0,'cable bend'),(188,0,'cable bend'),(190,0,'cable bend'),(192,0,'cable bend'),(195,0,'cable outlet'),(196.8,14.1,'counterbore outer land')]:
            section=c.call('solid_section_review',{'body_id':26,'plane':'xz','offset_mm':y,'probe_mm':z,'deflection_mm':.01})
            spans=[[s['start_mm'],s['end_mm']] for s in section['probe_spans']]
            assert spans,(label,y)
            if label=='ear capture':assert min(r-l for l,r in spans)>=2.8
            if label.startswith('cable'):assert spans[-1][1]-spans[-1][0]>=2.8,(y,spans)
            result['side_stock'].append({'label':label,'y_mm':y,'z_mm':z,'material_spans_mm':spans})
        for bid,z in [(26,20.6),(46,-20.6)]:
            mesh,_=export_mesh(c,bid);flat=np.all(np.abs(mesh.triangles[:,:,2]-z)<1e-7,axis=1)
            assert mesh.is_watertight and mesh.is_volume and component_count(mesh)==1
            item={'flat_area_mm2':float(mesh.area_faces[flat].sum()),'closed_connected':True};assert item['flat_area_mm2']>4000
            if bid==46:
                item['left_grip_flat_area_mm2']=contact_region_area(mesh.triangles[flat],-43,False)
                item['right_grip_flat_area_mm2']=contact_region_area(mesh.triangles[flat],34,True)
                assert min(item['left_grip_flat_area_mm2'],item['right_grip_flat_area_mm2'])>1100
            result['bed_contact'][str(bid)]=item
    REPORT.write_text(json.dumps(result,indent=2)+'\n')
    print('PASS: retained feature definitions, sampled roof/ear/cable stock and continuous bed/grip contact',flush=True)


if __name__=='__main__':main()
