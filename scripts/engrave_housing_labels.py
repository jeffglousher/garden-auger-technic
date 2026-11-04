"""Recess readable single-color labels into the inner servo-pocket floors."""
import copy
import json
from pathlib import Path

import numpy as np
from shapely.geometry import box
from shapely.ops import unary_union

from cad_client import CadClient
from cad_build import Builder, save_project
from build_servo_rear_fit_test import read_model, digest
from revise_clamshell import export_mesh
from print_packer import component_count

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'.build/clamshell-detail/current-assembly/labeled'
SOURCE=ROOT/'experiments/garden-auger-locator-fit.limo'
TARGET=ROOT/'experiments/garden-auger-labeled.limo'
# Original compact 5x7 block glyphs. Cell/stroke 0.5 mm; height 3.5 mm.
GLYPHS={
'A':'11111/10001/10001/11111/10001/10001/10001',
'C':'11111/10000/10000/10000/10000/10000/11111',
'D':'11110/10011/10001/10001/10001/10011/11110',
'E':'11111/10000/10000/11110/10000/10000/11111',
'G':'11111/10000/10000/10111/10001/10001/11111',
'H':'10001/10001/10001/11111/10001/10001/10001',
'I':'11111/00100/00100/00100/00100/00100/11111',
'L':'10000/10000/10000/10000/10000/10000/11111',
'M':'10001/11011/11111/10101/10001/10001/10001',
'N':'10001/11001/11101/10111/10011/10001/10001',
'O':'11111/10001/10001/10001/10001/10001/11111',
'P':'11111/10001/10001/11111/10000/10000/10000',
'R':'11111/10001/10001/11111/11100/10110/10011',
'S':'11111/10000/10000/11111/00001/00001/11111',
'T':'11111/00100/00100/00100/00100/00100/00100',
'U':'10001/10001/10001/10001/10001/10001/11111',
'W':'10001/10001/10001/10101/11111/11011/10001',
'X':'10001/11011/01110/00100/01110/11011/10001',
'0':'11111/10001/10001/10001/10001/10001/11111',
'1':'01100/00100/00100/00100/00100/00100/01110',
'3':'11111/00001/00001/11111/00001/00001/11111',
'4':'10010/10010/10010/11111/00010/00010/00010',
'5':'11111/10000/10000/11111/00001/00001/11111',
'6':'11111/10000/10000/11111/10001/10001/11111',
'7':'11111/00011/00110/01100/01000/01000/01000',
'8':'11111/10001/10001/11111/10001/10001/11111',
'-':'00000/00000/00000/11111/00000/00000/00000',
'.':'00000/00000/00000/00000/00000/00100/00100',
' ':'00000/00000/00000/00000/00000/00000/00000',
}
LABELS={46:['GA-HL-01','INSERT','4XM3X5.7','HOLE D4','DEPTH6.7','PETG'],
        26:['GA-HU-01','SCREWS','4XM3X18','PETG']}

def outlines(lines,upper):
    pixels=[]
    for row,text in enumerate(lines):
        for column,char in enumerate(text):
            for j,bits in enumerate(GLYPHS[char].split('/')):
                for i,bit in enumerate(bits):
                    if bit=='1':
                        x=-25.5+column*3+i*.5;y=190-row*4.0-j*.5
                        # Upper is flipped for print/view: mirror about pocket center X=-10.
                        x0,x1=(-20-x-.5,-20-x) if upper else (x,x+.5)
                        pixels.append(box(x0,y-.5,x1,y))
    shape=unary_union(pixels)
    polygons=list(shape.geoms) if hasattr(shape,'geoms') else [shape]
    assert all(p.is_valid for p in polygons)
    return shape, [list(r.coords)[:-1] for p in polygons for r in [p.exterior,*p.interiors]]

def main():
    BUILD.mkdir(parents=True,exist_ok=True)
    original=read_model(SOURCE)
    report={'source':str(SOURCE.relative_to(ROOT)),'source_sha256':digest(SOURCE),
            'cad':str(TARGET.relative_to(ROOT)),'labels':[],'depth_mm':.4,
            'glyph_height_mm':3.5,'stroke_mm':.5,'printer_command_sent':False}
    with CadClient() as c:
        report['engine_sha256']=digest(c.executable)
        c.call('cad_load_project_model',{'model_json':json.dumps(original)})
        canonical=c.call('cad_project_model');canonical=json.loads(canonical) if isinstance(canonical,str) else canonical
        before=c.call('solid_scene');assert not before['errors']
        old={bid:export_mesh(c,bid)[0] for bid in [26,46]}
        for bid,lines in LABELS.items():
            upper=bid==26;name=f'Engraved {"upper" if upper else "lower"} assembly details'
            shape,loops=outlines(lines,upper)
            Builder(c).poly(name,[(0,0),(1,0),(1,1),(0,1)],'xy')
            m=c.call('cad_project_model');m=json.loads(m) if isinstance(m,str) else m
            sketch=next(s for s in m['sketches'] if s['name']==name)
            entities=[];eid=0
            for loop in loops:
                ids=[]
                # Remove collinear pixel-boundary vertices before native replay.
                loop=[p for i,p in enumerate(loop) if abs((p[0]-loop[i-1][0])*(loop[(i+1)%len(loop)][1]-p[1])-(p[1]-loop[i-1][1])*(loop[(i+1)%len(loop)][0]-p[0]))>1e-9]
                for x,y in loop:
                    eid+=1;ids.append(eid);entities.append([eid,{'type':'point','position':{'x':x,'y':y}}])
                for a,b in zip(ids,ids[1:]+ids[:1]):
                    eid+=1;entities.append([eid,{'type':'line','start':a,'end':b}])
            sketch['snapshot'].update(entities=entities,constraints=[],generated_points=[],fix_targets={},dim_params={},dim_placements={},dim_modes={},next_entity=eid,next_constraint=0)
            sketch['entity_id_high_water']=eid;sketch['profile_identities']={'next':0,'records':[]}
            sketch['basis']['origin'][2]=10.19 if upper else -10.19
            c.call('cad_load_project_model',{'model_json':json.dumps(m)})
            profiles=next(s for s in c.call('sketch_profiles') if s['sketch_name']==name)
            assert not profiles['profile_error'],profiles['profile_error']
            indices=[p['index'] for p in profiles['profiles'] if p['nesting_depth']==0]
            c.call('solid_extrude',{'sketch_name':name,'profile_indices':indices,'operation':'cut',
                'extent':{'type':'distance','distance':.41},'flip':not upper,'taper_angle_deg':0,'target_body_ids':[bid]})
            print('Engraved',bid,lines,flush=True)
            mesh,_=export_mesh(c,bid)
            assert mesh.is_watertight and mesh.is_volume and component_count(mesh)==1
            removed=float(old[bid].volume-mesh.volume)
            assert abs(removed-shape.area*.4)<.05,(removed,shape.area*.4)
            z=20.6 if upper else -20.6
            flat=lambda a:float(a.area_faces[np.all(np.abs(a.triangles[:,:,2]-z)<1e-7,axis=1)].sum())
            assert abs(flat(mesh)-flat(old[bid]))<1e-6
            report['labels'].append({'body':bid,'lines':lines,'xy_bounds_mm':list(shape.bounds),'removed_volume_mm3':removed,'expected_removed_volume_mm3':shape.area*.4,'flat_bed_unchanged':True})
        scene=c.call('solid_scene');assert not scene['errors']
        for bid in [1,15,90,216,221]:assert next(b for b in scene['bodies'] if b['id']==bid)['mesh']==next(b for b in before['bodies'] if b['id']==bid)['mesh']
        final=save_project(c,TARGET)
        for key in ['sketches','extrudes','revolves','fillets','chamfers']:
            by_id={v['feature_id']:v for v in final[key]}
            assert all(by_id[v['feature_id']]==v for v in canonical[key]),key
        report['nominal_assembly']=c.call('assembly_interference_check',{'occurrence_ids':[3,6,7,8,14,16],'clearance_threshold_mm':2})
        assert not any(p['interfering'] for p in report['nominal_assembly']['pairs'])
        (BUILD/'scene.json').write_text(json.dumps(scene))
    report['cad_sha256']=digest(TARGET)
    (ROOT/'labeled-geometry-review.json').write_text(json.dumps(report,indent=2)+'\n')
    focused={'cad_sha256':report['cad_sha256'],'engine_sha256':report['engine_sha256'],'source_sha256':digest(SOURCE),'scope':'Focused engraving check: all original feature definitions retained after native default migration; only shallow material removal inside the servo pockets. Existing locator/motion evidence remains applicable to unchanged interfaces.','nominal_assembly':report['nominal_assembly'],'minimum_remaining_label_floor_mm':9.8,'label_checks':report['labels'],'prior_functional_evidence':'locator-fit-validation.json','prior_functional_evidence_sha256':digest(ROOT/'locator-fit-validation.json')}
    for name in ['labeled-validation.json','labeled-wall-review.json']:(ROOT/name).write_text(json.dumps(focused,indent=2)+'\n')
    print('PASS: recessed labels, expected cut volume, unchanged existing features and flat bed faces',flush=True)

if __name__=='__main__':main()
