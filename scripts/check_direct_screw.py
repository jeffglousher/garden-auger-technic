"""Check the actual adapter passage and a temporary M3x6 CAD envelope.

The vendor shaft/thread cavity is not supplied in the servo reference. This
proves printed-part clearance, not actual servo thread depth or compatibility.
"""
import json
from pathlib import Path
import numpy as np
import trimesh
from cad_client import CadClient
from cad_build import Builder
from audit_dimensions import vertical_hits
from direct_drive_parameters import *

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.build/direct-drive'


def main():
    model=json.loads((OUT/'model.json').read_text())
    scene=json.loads((OUT/'scene.json').read_text())
    body=next(b for b in scene['bodies'] if b['id']==216)['mesh']
    mesh=trimesh.Trimesh(vertices=np.array(body['positions']).reshape(-1,3),
        faces=np.array(body['indices']).reshape(-1,3),process=False)
    # Use the existing ray helper with Y as its depth coordinate.
    mesh.vertices=mesh.vertices[:,[0,2,1]]
    assert not vertical_hits(mesh,[0,0]),'Center screw / driver passage blocked'
    assert not vertical_hits(mesh,[1.6,0]),'M3 shaft envelope blocked'
    seat=vertical_hits(mesh,[2.1,0])
    assert np.allclose(seat,[HEAD_SEAT_Y,SHAFT_TIP_SEAT_Y],atol=.0002),seat
    neck=vertical_hits(mesh,[1.9,0])
    assert np.allclose(neck,[HEAD_SEAT_Y+.1,SHAFT_TIP_SEAT_Y],atol=.0002),neck
    with CadClient() as c:
        c.call('cad_load_project_model',{'model_json':json.dumps(model)})
        # An intentionally conservative neck proxy supplements the nominal
        # 5.5x3.0 head and 3.0 shaft. It is not an exact thread/fillet model.
        screw=Builder(c).revolve('Temporary M3x6 clearance envelope',
            [(HEAD_SEAT_Y-3,0),(HEAD_SEAT_Y-3,2.75),
             (HEAD_SEAT_Y,2.75),(HEAD_SEAT_Y,1.8),
             (HEAD_SEAT_Y+.3,1.5),(HEAD_SEAT_Y+6,1.5),(HEAD_SEAT_Y+6,0)],
            'new_body',[])['created_body_id']
        report=c.call('assembly_interference_check',{'clearance_threshold_mm':.01})
        assert report['exact']
        printed={15,90,26,46,216,221}
        unexpected=[p for p in report['pairs'] if p['interfering'] and screw in {p['body_a'],p['body_b']}
            and bool(printed&{p['body_a'],p['body_b']})]
        assert not unexpected,unexpected
        projections={}
        for key,ids,scope in [('adapter',[216],'definition'),('screw',[screw],'definition'),('servo',[1],'assembly')]:
            projections[key]=c.call('drawing_projection',{'body_ids':ids,'scope':scope,
                'direction':[1,0,0],'up':[0,0,1],'include_hidden':False,'deflection':.01,
                'section_plane':{'point':[0,0,0],'normal':[1,0,0]}})
        (OUT/'screw-projections.json').write_text(json.dumps(projections))
    r=json.loads((ROOT/'direct-drive-verification.json').read_text())
    r['center_screw_cad_check']={'exact_native_screw_envelope_to_printed_parts_overlap_mm3':0,
        'center_axis_passage_open':True,'screw_shaft_envelope_passage_open':True,
        'head_seat_to_tip_annular_seat_measured_mm':seat[1]-seat[0],
        'underhead_relief_measured':True,'temporary_screw_geometry_saved_to_design':False,
        'servo_cavity_excluded':'Reference servo has no modeled internal threaded bore; its solid volume overlaps the hypothetical screw and cannot validate thread depth.',
        'actual_servo_thread_depth_verified':False}
    r['center_screw_inspection']=screw_stack()
    (ROOT/'direct-drive-verification.json').write_text(json.dumps(r,indent=2))
    print('M3x6 CAD envelope clears all printed parts; axis passage and 2.60 mm seat stack checked',flush=True)
    print('Actual INJORA thread depth and factory screw length remain unpublished/unmeasured',flush=True)

if __name__=='__main__':main()
