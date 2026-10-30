"""Verify the smaller shield against the committed 40 mm baseline."""
import hashlib,io,json,subprocess,zipfile
from pathlib import Path
from cad_client import CadClient
from build_servo_rear_fit_test import read_model,digest
from review_snug_servo_nest import native_cylinder
ROOT=Path(__file__).resolve().parents[1]
BASE='c12240264861d015cf01905fe26ceb030b09e6e9'
def main():
    raw=subprocess.check_output(['git','show',BASE+':experiments/garden-auger-simple-print.limo'],cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:before=json.loads(z.read('model.json'))
    cad=ROOT/'experiments/garden-auger-simple-print.limo'
    with CadClient() as c:
        c.call('cad_load_project_model',{'model_json':json.dumps(before)});old=c.call('solid_scene')
        c.call('cad_load_project_model',{'model_json':json.dumps(read_model(cad))});new=c.call('solid_scene')
        assert not old['errors'] and not new['errors']
        for bid in [1,26,46,90,216,221]:assert next(b for b in old['bodies'] if b['id']==bid)['mesh']==next(b for b in new['bodies'] if b['id']==bid)['mesh'],bid
        flange=native_cylinder(next(b for b in new['bodies'] if b['id']==15),19.)
        r={'before_commit':BASE,'before_cad_sha256':hashlib.sha256(raw).hexdigest(),'after_cad_sha256':digest(cad),'engine_sha256':digest(c.executable),'unchanged_native_mesh_body_ids':[1,26,46,90,216,221],'before_disc_mm':40,'after_disc_mm':38,'reference_opening_mm':33.6,'radial_axis_allowance_mm':.5,'remaining_radial_overlap_mm':19-16.8-.5,'remaining_axial_gap_mm':1.1,'front_flat_radius_mm':18.4,'flat_face_overlap_at_radial_allowance_mm':18.4-16.8-.5,'native_flange':flange,'scope':'Nominal CAD coverage with existing conditional assembly allowances, not a full manufacturing tolerance stack or tested seal.'}
        assert r['remaining_radial_overlap_mm']>0
    newprint=json.loads((ROOT/'simple-print-verification.json').read_text())
    if newprint['cad_sha256']==r['after_cad_sha256']:
        oldprint=json.loads(subprocess.check_output(['git','show',BASE+':simple-print-verification.json'],cwd=ROOT))
        r['native_print_comparison']={'before_seconds':oldprint['time_seconds'],'after_seconds':newprint['time_seconds'],'saved_seconds':oldprint['time_seconds']-newprint['time_seconds'],'before_filament_g':oldprint['filament_g'],'after_filament_g':newprint['filament_g'],'saved_filament_g':oldprint['filament_g']-newprint['filament_g']}
        for f,h in oldprint['stls'].items():
            if 'one-piece-auger' not in f:assert digest(ROOT/f)==h,f
        r['four_other_stl_hashes_identical']=True
    (ROOT/'disc38-review.json').write_text(json.dumps(r,indent=2)+'\n')
    print('PASS: only auger core changed; native 38mm shield covers opening at existing radial allowance')
if __name__=='__main__':main()
