"""Remove the redundant fixed nose ring and use a smaller, plain auger flange.

Native CAD only; preserve fitted interfaces and continuous bed lands. Owned
simple-print evidence stays in the existing D project lane, bounded to 90 MiB.
"""
import copy,json
from pathlib import Path
import numpy as np

from cad_client import CadClient
from cad_build import Builder,profile,save_project
from build_servo_rear_fit_test import read_model,digest,native_plane
from revise_clamshell import export_mesh
from review_snug_servo_nest import set_pose,pairs
from print_packer import component_count

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'experiments/garden-auger-ingress-flange.limo'
CAD=ROOT/'experiments/garden-auger-simple-print.limo'
BUILD=ROOT/'.build/clamshell-detail/current-assembly/simple-print'
REPORT=ROOT/'simple-print-geometry-review.json'
PROFILE=[(103.3,0.),(103.3,19.4),(103.9,20.),(106.3,20.),(106.3,0.)]


def shield_probe(c,name):
    bid=Builder(c).revolve(name,PROFILE,'new_body',[])['created_body_id']
    c.call('assembly_create_component',{'name':name,'body_ids':[bid],'absorb_promoted_bodies':True})
    m=c.call('cad_project_model');m=json.loads(m) if isinstance(m,str) else m
    oid=next(o['id'] for o in m['assembly']['component_structure']['occurrences'] if o['name']==name)
    return bid,oid


def main():
    BUILD.mkdir(parents=True,exist_ok=True)
    original=read_model(SOURCE);candidate=copy.deepcopy(original)
    previous=json.loads((ROOT/'ingress-flange-geometry-review.json').read_text())
    assert previous['cad_sha256']==digest(SOURCE)
    for f in candidate['document']['history']['features']:
        if 349<=f['id']<=353:f['suppressed']=True
    flange=next(s for s in candidate['sketches'] if s['feature_id']==393)
    profile(flange,PROFILE)
    report={'source':str(SOURCE.relative_to(ROOT)),'source_sha256':digest(SOURCE),
        'profile':previous['profile'],'locators':previous['locators'],
        'suppressed_redundant_ring_features':list(range(349,354)),
        'shield':{'profile_y_radius_mm':PROFILE,'outside_diameter_mm':40.,
            'axial_span_y_mm':[103.3,106.3],'broad_web_thickness_mm':3.,
            'outer_edge_thickness_mm':2.4,'front_edge_chamfer_mm':.6,
            'housing_front_y_mm':107.9,'opening_radius_reference_mm':16.8,
            'nominal_rear_face_gap_mm':1.6,'nominal_radial_opening_overlap_mm':3.2,
            'conditional_axial_allowance_mm':.5,'conditional_radial_axis_offset_mm':.5,
            'conditional_rear_face_gap_mm':1.1,'conditional_radial_opening_overlap_mm':2.7,
            'scope':'Conservative opening reference from the retained entrance profile; existing conditional allowances, not new physical readings or a full tolerance stack.'},
        'printer_command_sent':False}
    with CadClient() as c:
        report['engine_sha256']=digest(c.executable)
        c.call('cad_load_project_model',{'model_json':json.dumps(original)})
        old_scene=c.call('solid_scene');assert not old_scene['errors']
        old_mesh={bid:export_mesh(c,bid)[0] for bid in [15,26,46]}
        c.call('cad_load_project_model',{'model_json':json.dumps(candidate)})
        c.call('cad_set_document_name',{'name':'Garden auger - simple printable nose and flange'})
        c.call('solid_rename_feature',{'feature_id':393,'name':'Simple 40mm auger flange - one edge chamfer'})
        scene=c.call('solid_scene');assert not scene['errors']
        bodies={b['id']:b for b in scene['bodies']}
        report['changed_parts']={}
        for bid in [15,26,46]:
            mesh,_=export_mesh(c,bid)
            assert mesh.is_watertight and mesh.is_volume and component_count(mesh)==1
            assert mesh.volume<old_mesh[bid].volume
            item={'before_volume_mm3':old_mesh[bid].volume,'after_volume_mm3':mesh.volume,
                'removed_volume_mm3':old_mesh[bid].volume-mesh.volume,'closed_connected':True,
                'before_native_faces':len(next(b for b in old_scene['bodies'] if b['id']==bid)['faces']),
                'after_native_faces':len(bodies[bid]['faces']),'bounds_mm':mesh.bounds.tolist()}
            if bid in [26,46]:
                assert mesh.bounds[0,1]>=107.9-1e-6
                z=20.6 if bid==26 else -20.6
                flat=lambda m:float(m.area_faces[np.all(np.abs(m.triangles[:,:,2]-z)<1e-7,axis=1)].sum())
                item['flat_bed_area_mm2']=flat(mesh)
                assert abs(flat(mesh)-flat(old_mesh[bid]))<1e-6
            report['changed_parts'][str(bid)]=item
        for bid in [1,90,216,221]:
            assert bodies[bid]['mesh']==next(b for b in old_scene['bodies'] if b['id']==bid)['mesh'],bid
        report['unchanged_mesh_body_ids']=[1,90,216,221]
        report['native_flange_rear_plane']=native_plane(bodies[15],1,106.3)
        report['native_housing_front_plane']=native_plane(bodies[26],1,107.9)
        report['nominal_assembly']=c.call('assembly_interference_check',{'occurrence_ids':[3,6,7,8,14,16],'clearance_threshold_mm':2})
        assert report['nominal_assembly']['exact'] and not any(p['interfering'] for p in report['nominal_assembly']['pairs'])
        final=save_project(c,CAD)
        assert final['body_appearances']==original['body_appearances']
        for key in ['sketches','extrudes','revolves','fillets','chamfers','datum_planes','body_features']:
            by_id={json.dumps(v,sort_keys=True) for v in final[key]}
            for v in original[key]:
                if v.get('feature_id')==393:continue
                # Renaming the sketch updates its revolve reference only.
                if key=='revolves' and v['feature_id']==394:
                    v=copy.deepcopy(v);v['sketch_name']='Simple 40mm auger flange - one edge chamfer'
                assert json.dumps(v,sort_keys=True) in by_id,(key,v.get('feature_id'))
        report['active_feature_count']={'before':sum(not f['suppressed'] for f in original['document']['history']['features']),
            'after':sum(not f['suppressed'] for f in final['document']['history']['features'])}
        (BUILD/'scene.json').write_text(json.dumps(scene))
        bid,oid=shield_probe(c,'Inspection only - simple flange')
        report['isolated_shield_samples']=[]
        for dx,dz in [(0,0),(.5,0),(-.5,0),(0,.5),(0,-.5)]:
            for dy in [-.5,.5]:
                set_pose(c,oid,(dx,dy,dz))
                check=c.call('assembly_interference_check',{'occurrence_ids':[6,7,oid],'clearance_threshold_mm':3})
                ps=pairs(check,{bid},{26,46});assert ps and not any(p['interfering'] for p in ps)
                report['isolated_shield_samples'].append({'shift_mm':[dx,dy,dz],'pairs':ps})
        c.call('cad_load_project_model',{'model_json':json.dumps(original)})
        bid,oid=shield_probe(c,'Inspection only - incompatible legacy projecting ring')
        check=c.call('assembly_interference_check',{'occurrence_ids':[6,7,oid],'clearance_threshold_mm':3})
        ps=pairs(check,{bid},{26,46});assert any(p['interfering'] for p in ps)
        report['mixed_version_blocked_control']={'pairs':ps,
            'instruction':'Use the matching simple-print auger and both housing halves. The closer flange collides with the older projecting nose ring.'}
    report['cad']=str(CAD.relative_to(ROOT));report['cad_sha256']=digest(CAD)
    REPORT.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: smaller plain flange, redundant ring removed, flat lands unchanged, allowance poses and blocked mixed-version control',flush=True)


if __name__=='__main__':main()
