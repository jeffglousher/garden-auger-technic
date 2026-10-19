"""Remove cosmetic seam recesses while retaining outer rounds and all fits.

Uses the existing installed native engine and a 100 MiB evidence sublane.
No shared runtime changes or printer commands.
"""
import copy,json
from pathlib import Path

import numpy as np
from cad_client import CadClient
from cad_build import save_project
from build_servo_rear_fit_test import read_model,digest,native_plane
from revise_clamshell import export_mesh
from round_housing_review import vertical_edges
from print_packer import component_count

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'experiments/garden-auger-child-d-grips.limo'
CAD=ROOT/'experiments/garden-auger-solid-frame.limo'
BUILD=ROOT/'.build/clamshell-detail/current-assembly/d-grip/solid-frame'
REPORT=ROOT/'solid-frame-geometry-review.json'
RECESSES=set(range(333,349))


def main():
    BUILD.mkdir(parents=True,exist_ok=True)
    original=read_model(SOURCE);candidate=copy.deepcopy(original)
    candidate['document']['name']='Garden auger - continuous frame with outer rounds'
    suppressed=[]
    for feature in candidate['document']['history']['features']:
        if feature['id'] in RECESSES|{369,370}:
            feature['suppressed']=True
            suppressed.append({'id':feature['id'],'name':feature['name'],'kind':feature['kind']})
    report={'source':str(SOURCE.relative_to(ROOT)),'source_sha256':digest(SOURCE),
        'suppressed_features':suppressed,'cosmetic_recess_cut_ids':[334,336,338,340,342,344,346,348],
        'change':'Remove paired seam scallops. Rebuild R6 exterior front corners; preserve complete lower D grips.',
        'profile':json.loads((ROOT/'d-grip-geometry-review.json').read_text())['profile'],
        'locators':json.loads((ROOT/'d-grip-geometry-review.json').read_text())['locators'],
        'printer_command_sent':False}
    with CadClient() as c:
        report['engine_sha256']=digest(c.executable)
        c.call('cad_load_project_model',{'model_json':json.dumps(original)})
        before=c.call('solid_scene');assert not before['errors']
        old={bid:export_mesh(c,bid)[0] for bid in [26,46]}
        c.call('cad_load_project_model',{'model_json':json.dumps(candidate)})
        assert not c.call('solid_scene')['errors'],c.call('solid_scene')['errors']
        for bid in [26,46]:
            body=next(b for b in c.call('solid_scene')['bodies'] if b['id']==bid)
            edges=vertical_edges(body,lambda p:abs(abs(p['x'])-34)<1e-7 and abs(p['y']-107.9)<1e-7)
            assert len(edges)==2,(bid,edges)
            c.call('solid_fillet',{'body_id':bid,'edge_ids':edges,'radius':6.,'tangent_chain':False})
            assert not c.call('solid_scene')['errors']
        final=save_project(c,CAD)
        scene=c.call('solid_scene');assert not scene['errors']
        bodies={b['id']:b for b in scene['bodies']}
        for bid in [1,15,90,216,221]:assert bodies[bid]['mesh']==next(b for b in before['bodies'] if b['id']==bid)['mesh']
        assert final['body_appearances']==original['body_appearances']
        # Only history suppression and new outer fillets may differ. Every
        # preceding feature definition, including cavity cuts and datums, stays.
        retained={}
        for key,value in original.items():
            if key=='document':continue
            if isinstance(value,list) and value and isinstance(value[0],dict) and 'feature_id' in value[0]:
                by_id={v['feature_id']:v for v in final[key]}
                assert all(by_id[v['feature_id']]==v for v in value),key
                retained[key]=[v['feature_id'] for v in value]
            elif key not in ['assembly','counters']:
                assert value==final[key],key
        report['unchanged_original_feature_definitions']=retained
        print('Eight cosmetic seam cuts removed; retained feature definitions and appearances match',flush=True)
        report['unchanged_mesh_body_ids']=[1,15,90,216,221]
        report['housing']={}
        for bid in [26,46]:
            mesh,_=export_mesh(c,bid)
            assert mesh.is_watertight and mesh.is_volume and component_count(mesh)==1
            assert mesh.volume>old[bid].volume
            z=20.6 if bid==26 else -20.6
            native_plane(bodies[bid],2,z)
            flat=np.all(np.abs(mesh.triangles[:,:,2]-z)<1e-7,axis=1)
            assert np.allclose(mesh.bounds,old[bid].bounds,rtol=0,atol=1e-7)
            report['housing'][str(bid)]={'before_volume_mm3':old[bid].volume,'after_volume_mm3':mesh.volume,
                'restored_stock_mm3':mesh.volume-old[bid].volume,'flat_bed_area_mm2':float(mesh.area_faces[flat].sum()),
                'bounds_mm':mesh.bounds.tolist(),'closed_connected':True}
        nominal=c.call('assembly_interference_check',{'occurrence_ids':[3,6,7,8,14,16],'clearance_threshold_mm':2})
        assert nominal['exact'] and not any(p['interfering'] for p in nominal['pairs'])
        report['nominal_assembly']=nominal
        report['preflight']=c.call('solid_export_preflight',{'body_ids':[26,46,15,90,216,221]})
        assert report['preflight']['ok'] and not report['preflight']['timeline_errors']
        (BUILD/'scene.json').write_text(json.dumps(scene))
    report['cad']=str(CAD.relative_to(ROOT));report['cad_sha256']=digest(CAD)
    REPORT.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: solid frame, outside R6 rounds, unchanged fitted definitions and nominal assembly',flush=True)


if __name__=='__main__':main()
