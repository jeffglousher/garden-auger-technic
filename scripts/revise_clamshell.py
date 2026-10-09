"""Editable detail revision from the physically fitted baseline, headless only.

Run: uv run --no-project --python 3.14 --with numpy --with trimesh
--with manifold3d --with pillow python scripts/revise_clamshell.py
No desktop interaction or printer commands. New files preserve the fitted pair.
"""
import base64
import copy
import json
import math
from pathlib import Path

from cad_client import CadClient
from cad_build import Builder, profile, save_project
from build_servo_rear_fit_test import read_model, digest, native_plane
from prepare_sparse_servo_upper_test import exported_mesh
from print_packer import component_count
from review_snug_servo_nest import set_pose, pairs

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'experiments/garden-auger-servo-snug-test.limo'
TARGET = ROOT / 'experiments/garden-auger-clamshell-detail-test.limo'
BUILD = ROOT / '.build/clamshell-detail'


def model(c):
    value = c.call('cad_project_model')
    return json.loads(value) if isinstance(value, str) else value


def sketch_at(c, name, points, origin, plane='xz'):
    Builder(c).poly(name, points, plane)
    m = model(c)
    next(s for s in m['sketches'] if s['name'] == name)['basis']['origin'] = list(origin)
    c.call('cad_load_project_model', {'model_json': json.dumps(m)})


def locator(c, x, owner):
    other = 46 if owner == 26 else 26
    sign = -1 if owner == 26 else 1
    for operation, target, points in [
        ('join', owner, [(0,-.4),(3.5,-.4),(3.5,2.2),(2.9,2.8),(0,2.8)]),
        ('cut', other, [(0,-.2),(3.85,-.2),(3.65,.2),(3.65,3.2),(0,3.2)])]:
        name = f'Handle {x:+g} {operation} - chamfered 7mm locator'
        sketch_at(c, name, [(x+r, sign*z) for r,z in points], (0,192,0))
        c.call('solid_revolve', {'sketch_name':name, 'profile_indices':[0],
            'axis_origin':{'x':x,'y':0}, 'axis_direction':{'x':0,'y':1},
            'angle_deg':360, 'flip':False, 'operation':operation, 'target_body_ids':[target]})
        scene = c.call('solid_scene')
        assert not scene['errors'], scene['errors']
        print(name, 'OK', flush=True)


def sculpt(c, name, x0, direction, y0, y1):
    # Side-only removal: seam width is x0; 45-degree slope widens toward
    # retained outer bed floors. Never approaches the central cavities.
    for sign, body in [(1,26),(-1,46)]:
        n = f'{name} {"upper" if sign == 1 else "lower"}'
        points=[(x0,0),(x0+direction*9.5,sign*9.5),
                (direction*120,sign*9.5),(direction*120,0)]
        sketch_at(c,n,points,(0,y1,0))
        c.call('solid_extrude', {'sketch_name':n,'profile_indices':[0],
            'operation':'cut','extent':{'type':'distance','distance':y1-y0},
            'taper_angle_deg':0,'flip':False,'target_body_ids':[body]})
        assert not c.call('solid_scene')['errors']
        print(n, 'OK', flush=True)


def export_mesh(c, bid):
    value=c.call('solid_export_3mf', {'body_ids':[bid],'scope':'definition',
        'linear_deflection':.08,'angular_deflection':.2,'slicer_target':'standard'})
    raw=base64.b64decode(value['bytes_base64'])
    return exported_mesh(raw),raw


def main():
    BUILD.mkdir(parents=True,exist_ok=True)
    original=read_model(SOURCE)
    hashes={str(p.relative_to(ROOT)):digest(p) for p in [SOURCE,
        ROOT/'garden-auger-lower-servo-sparse-test.3mf',
        ROOT/'garden-auger-upper-servo-sparse-test.3mf',
        ROOT/'garden-auger-lower-fit-test.3mf']}
    report={'source':str(SOURCE.relative_to(ROOT)), 'source_sha256':digest(SOURCE),
        'physical_baseline':'Owner reports successful assembly; tightened screws and dirty trial untested.',
        'dimensions_locked':'Servo nest, drive, sleeve, stops, existing entrance taper and rear cable route.',
        'locators':{'centers_xy_mm':[[-55,192],[-88,192],[55,192],[88,192]],
            'upper_owned_x_mm':[-55,88], 'lower_owned_x_mm':[-88,55],
            'pin_diameter_mm':7,'straight_socket_diameter_mm':7.3,
            'nominal_diametral_clearance_mm':.3,'projection_mm':2.8,
            'socket_depth_mm':3.2,'tip_chamfer_mm':.6,
            'status':'Provisional PETG clearance; all four round locators require printed fit verification.'},
        'housing_hardware':{'screw':'4 identical M3 x 18 socket head cap screws',
            'insert':'4 identical ruthex RX-M3x5.7, unchanged pilots',
            'head_seat_z_mm':14,'head_pocket_diameter_mm':6.2,
            'nominal_head_height_mm':3,'head_top_z_mm':17,
            'outer_bed_z_mm':20.6,'head_recess_mm':3.6,
            'nominal_thread_penetration_mm':4,'pilot_bottom_margin_mm':2.7,
            'scope':'Nominal stack only; verify purchased screw/insert dimensions and usable threads.'},
        'guard':{'axial_extent_y_mm':[103.9,108.2],'inner_radius_mm':18.8,
            'maximum_outer_radius_mm':20.6,'projection_beyond_old_nose_mm':4,
            'scope':'Fixed noncontact deflector; does not seal fine dirt or slurry.'},
        'printer_command_sent':False}
    with CadClient(stderr_path=BUILD/'engine.log') as c:
        report['engine_sha256']=digest(c.executable)
        c.call('cad_load_project_model',{'model_json':json.dumps(original)})
        before=c.call('solid_scene')
        assert not before['errors']
        old_mesh={bid:export_mesh(c,bid)[0] for bid in [26,46]}
        candidate=copy.deepcopy(original)
        for f in candidate['document']['history']['features']:
            if f['id'] in [246,248,250,253,226]: f['suppressed']=True
        next(e for e in candidate['extrudes'] if e['feature_id']==159)['extent']['distance']=6.6
        candidate['document']['name']='Garden auger - clamshell detail test'
        # Grips retain the original bed lands; soften the broad seam shoulders.
        handle=next(s for s in candidate['sketches'] if s['feature_id']==49)
        profile(handle,[(188,-20.6),(199.5,-20.6),(204,-16.1),
            (204,16.1),(199.5,20.6),(188,20.6),(183.5,16.1),(183.5,-16.1)])
        c.call('cad_load_project_model',{'model_json':json.dumps(candidate)})
        for x,owner in [(-55,26),(-88,46),(55,46),(88,26)]:locator(c,x,owner)
        for args in [('Bearing right shoulder',20.8,1,126,143),
                     ('Bearing left shoulder',-20.8,-1,126,143),
                     ('Servo right shoulder',13.2,1,173,180),
                     ('Servo left shoulder',-33.7,-1,173,180)]: sculpt(c,*args)
        # Guard is an editable annular revolve, split and joined to the halves.
        ring=Builder(c).revolve('External auger dirt deflector',
            [(103.9,18.8),(103.9,20),(104.5,20.6),(108.2,20.6),(108.2,18.8)],
            'new_body',[])['created_body_id']
        ids={b['id'] for b in c.call('solid_scene')['bodies']}
        c.call('solid_split_body',{'body_id':ring,'plane':{'type':'origin_plane','plane':'xy'}})
        scene=c.call('solid_scene')
        guard_ids=[ring]+[b['id'] for b in scene['bodies'] if b['id'] not in ids]
        assert len(guard_ids)==2
        for gid in guard_ids:
            b=next(b for b in scene['bodies'] if b['id']==gid)
            zs=b['mesh']['positions'][2::3]
            target=26 if max(zs)>1 else 46
            c.call('solid_combine',{'target_body_id':target,'tool_body_ids':[gid],
                'operation':'join','keep_tools':False})
        scene=c.call('solid_scene')
        assert not scene['errors'],scene['errors']
        final=save_project(c,TARGET)
        # Immutable component definitions and meshes provide direct evidence.
        for bid in [1,15,90,216,221]:
            a=next(b for b in before['bodies'] if b['id']==bid)
            b=next(b for b in scene['bodies'] if b['id']==bid)
            assert a['mesh']==b['mesh'], f'Locked body {bid} changed'
        assert final['body_appearances']==original['body_appearances']
        report['unchanged_mesh_body_ids']=[1,15,90,216,221]
        for key,ids in [('extrudes',[131,161,183,278]),('revolves',[301])]:
            for fid in ids:
                assert next(f for f in final[key] if f['feature_id']==fid)==next(f for f in original[key] if f['feature_id']==fid)
        report['locked_feature_records_identical']=[131,161,183,278,301]
        recorded=json.loads((ROOT/'servo-snug-review.json').read_text())['native_nest_faces']
        report['retained_native_datums']={}
        report['housing_meshes']={}
        for bid in [26,46]:
            b=next(b for b in scene['bodies'] if b['id']==bid)
            report['retained_native_datums'][str(bid)]={k:native_plane(b,'XYZ'.index(v['axis']),v['coordinate_mm']) for k,v in recorded[str(bid)].items()}
            mesh,raw=export_mesh(c,bid)
            assert mesh.is_watertight and mesh.is_volume and component_count(mesh)==1
            (BUILD/f'{bid}-native.3mf').write_bytes(raw)
            report['housing_meshes'][str(bid)]={'one_closed_connected_solid':True,
                'before_volume_mm3':float(old_mesh[bid].volume),'after_volume_mm3':float(mesh.volume),
                'net_volume_removed_mm3':float(old_mesh[bid].volume-mesh.volume),
                'bounds_mm':mesh.bounds.tolist()}
        nominal=c.call('assembly_interference_check',{'occurrence_ids':[3,6,7,8,14,16],'clearance_threshold_mm':1})
        assert nominal['exact'] and not any(p['interfering'] for p in nominal['pairs']),nominal
        report['nominal_assembly']=nominal
        samples=[]
        for angle in range(0,360,30):
            for travel in [-.29,.29]:
                set_pose(c,8,shift=(.5,travel,0),axis=1,degrees=angle)
                r=c.call('assembly_interference_check',{'occurrence_ids':[6,7,8],'clearance_threshold_mm':1})
                ps=pairs(r,{15,90},{26,46})
                assert ps and not any(p['interfering'] for p in ps),(angle,travel,ps)
                samples.append({'angle_deg':angle,'axial_shift_mm':travel,'radial_x_mm':.5,'pairs':ps})
        set_pose(c,8)
        report['auger_motion_samples']=samples
        set_pose(c,8,shift=(.5,-.5,0))
        negative=c.call('assembly_interference_check',{'occurrence_ids':[6,7,8],'clearance_threshold_mm':1})
        assert any(p['interfering'] for p in negative['pairs'])
        report['beyond_end_float_blocked_control']=negative
        set_pose(c,8)
        # Locator-only clear and deliberately blocked joint translation controls.
        controls=[]
        for shift in [(0.10,0,0),(.20,0,0),(0,.10,0),(0,.20,0)]:
            set_pose(c,6,shift)
            r=c.call('assembly_interference_check',{'occurrence_ids':[6,7],'clearance_threshold_mm':1})
            blocked=any(p['interfering'] for p in r['pairs'])
            assert blocked==(max(shift)>.15),(shift,r)
            controls.append({'upper_translation_mm':shift,'blocked':blocked,'pairs':r['pairs']})
        set_pose(c,6)
        report['joint_translation_controls']=controls
        (BUILD/'scene.json').write_text(json.dumps(scene))
        report['cad']=str(TARGET.relative_to(ROOT));report['cad_sha256']=digest(TARGET)
    for p,h in hashes.items():assert digest(ROOT/p)==h,p
    report['preserved_files']=hashes
    report['scope']='Exact nominal interference and sampled motion/locating checks, not manufactured fit, loaded strength or sealing qualification.'
    (ROOT/'clamshell-detail-review.json').write_text(json.dumps(report,indent=2)+'\n')
    print('CAD and native review complete',flush=True)


if __name__=='__main__':main()
