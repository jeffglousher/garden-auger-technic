"""Build the fully specified collar-captured auger and metal-horn adapter."""

import base64
import json
import math
from pathlib import Path

from cad_client import CadClient
from cad_build import Builder, prepare_baseline, profile, save_project
from design_parameters import *
from model_cleanup import clean_checked

ROOT=Path(__file__).resolve().parents[1]


def rounded_square(sketch,width,radius):
    h=width/2;r=radius
    profile(sketch,[(-h+r,-h),(h-r,-h),(h,-h+r),(h,h-r),
                   (h-r,h),(-h+r,h),(-h,h-r),(-h,-h+r)],{
        1:((h-r,-h+r),r,1.5*math.pi,2*math.pi),
        3:((h-r,h-r),r,0,.5*math.pi),
        5:((-h+r,h-r),r,.5*math.pi,math.pi),
        7:((-h+r,-h+r),r,math.pi,1.5*math.pi),
    })


def configure():
    m=prepare_baseline();s={x['name']:x for x in m['sketches']}
    rounded_square(s['Sketch99'],PEG,PEG_RADIUS)
    rounded_square(s['Sketch100'],SOCKET,SOCKET_RADIUS)
    next(e for e in m['extrudes'] if e['feature_id']==289)['extent']['distance']=PEG_ROOT_Y-PEG_TIP_Y
    next(e for e in m['extrudes'] if e['feature_id']==293)['extent']['distance']=FLANGE_THICKNESS
    s['Sketch101']['snapshot']['entities'][0][1]['radius']=FLANGE_DIAMETER/2
    s['Sketch101']['profile_identities']={'next':0,'records':[]}
    next(e for e in m['body_features'] if e['feature_id']==299)['translation']['y']=PEG_ROOT_Y-139.5
    profile(s['Chassis integral thrust stops and journal seat'],housing_profile())
    profile(s['Plain loose PLA wear sleeve'],[(SLEEVE_FRONT,15.0),(SLEEVE_FRONT+.7,14.3),
        (SLEEVE_REAR-.2,14.3),(SLEEVE_REAR,14.5),(SLEEVE_REAR,17),(SLEEVE_FRONT,17)])
    profile(s['Adapter center screw clearance'],[(129.3,0),(129.3,1.7),(149,1.7),(149,0)])
    old='Servo interface placeholder - unqualified';new='Metal horn pilot and center screw head relief'
    s[old]['name']=new
    profile(s[old],[(142.6,0),(142.6,3.2),(HORN_FACE_Y-PILOT_DEPTH,3.2),
                   (HORN_FACE_Y-PILOT_DEPTH,PILOT_DIAMETER/2),(149,PILOT_DIAMETER/2),(149,0)])
    for r in m['revolves']:
        if r['sketch_name']==old:r['sketch_name']=new
    for f in m['document']['history']['features']:
        if f['name']==old:f['name']=new
        if f['id']==307:f['suppressed']=True # superseded peg-tip screw counterbore
    # Move the case, ear capture and wire passage together.
    moved=set()
    for name in ['Sketch45','Sketch62']:
        k=s[name];k['basis']['origin'][1]+=SERVO_SHIFT
        id=k['plane']['datum_id']
        if id not in moved:
            p=next(p for p in m['datum_planes'] if p['datum_id']==id)
            p['basis']['origin'][1]+=SERVO_SHIFT;p['source']['distance']-=SERVO_SHIFT;moved.add(id)
    for name in ['Sketch80','Sketch81','Sketch95']:
        for _,e in s[name]['snapshot']['entities']:
            if e['type']=='point':e['position']['y']+=SERVO_SHIFT
        s[name]['profile_identities']={'next':0,'records':[]}
    for name in ['Sketch54','Sketch55','Sketch56']:
        for _,e in s[name]['snapshot']['entities']:
            p=e.get('center') if e['type']=='circle' else e.get('position')
            if p and abs(p['y']-189.8)<1e-6:p['y']=REAR_SCREW_Y
        s[name]['profile_identities']={'next':0,'records':[]}
    for o in m['assembly']['component_structure']['occurrences']:
        if o['component_id']==3:o['local_pose']['translation'][1]=SERVO_TRANSLATION_Y
    m['document']['name']='Garden auger - release B - metal 25T horn and collar capture'
    return m


def circle_cut(c,name,centers,diameter,origin_y,depth,target):
    # XZ origin plane has its normal toward -Y. Offset -origin_y places
    # the plane at the positive Y coordinate; flip cuts toward the servo.
    c.call('construction_plane_offset',{'name':name+' plane',
        'reference':{'type':'origin_plane','plane':'xz'},'distance':-origin_y})
    # Return schemas are read through the project, avoiding guessed IDs.
    model=c.call('cad_project_model');model=json.loads(model) if isinstance(model,str) else model
    datum=model['datum_planes'][-1]['datum_id']
    c.call('sketch_begin',{'name':name,'plane':{'type':'datum_plane','datum_id':datum}})
    c.call('sketch_set_grid_snap',{'enabled':False})
    for x,z in centers:
        c.call('sketch_add_circle',{'mode':'center_diameter','p1':{'x':x,'y':z},
            'p2':{'x':x+diameter/2,'y':z},'ctrl_held':True})
    c.call('sketch_finish')
    c.call('solid_extrude',{'sketch_name':name,'profile_indices':list(range(len(centers))),
        'operation':'cut','extent':{'type':'distance','distance':depth},'taper_angle_deg':0,
        'flip':True,'target_body_ids':[target]})


def export(c):
    r=c.call('solid_export_3mf',{'body_ids':[26,46,15,90,216,SLEEVE_BODY],
        'scope':'definition','linear_deflection':.08,'angular_deflection':.2,'slicer_target':'bambu_studio'})
    (ROOT/'.build/raw.3mf').write_bytes(base64.b64decode(r['bytes_base64']))
    p=c.call('solid_export_preflight');assert p['ok'] and not p['timeline_errors'],p
    (ROOT/'.build/preflight.json').write_text(json.dumps(p))


def rear_pads(c):
    c.call('sketch_begin',{'name':'Rear fastener pads clear of wire channel',
        'plane':{'type':'origin_plane','plane':'xy'}})
    c.call('sketch_set_grid_snap',{'enabled':False})
    for x in [-36,16]:
        c.call('sketch_add_circle',{'mode':'center_diameter','p1':{'x':x,'y':REAR_SCREW_Y},
            'p2':{'x':x+7,'y':REAR_SCREW_Y},'ctrl_held':True})
    c.call('sketch_finish')
    for body,depth,flip in [(26,17,False),(46,12,True)]:
        c.call('solid_extrude',{'sketch_name':'Rear fastener pads clear of wire channel',
            'profile_indices':[0,1],'operation':'join','extent':{'type':'distance','distance':depth},
            'taper_angle_deg':0,'flip':flip,'target_body_ids':[body]})
    m=c.call('cad_project_model');m=json.loads(m) if isinstance(m,str) else m
    history=m['document']['history']['features']
    holes=[f for f in history if f['id'] in [157,159,161]]
    m['document']['history']['features']=[f for f in history if f['id'] not in [157,159,161]]+holes
    c.call('cad_load_project_model',{'model_json':json.dumps(m)})


def main():
    (ROOT/'.build').mkdir(exist_ok=True)
    with CadClient() as c:
        c.call('cad_load_project_model',{'model_json':json.dumps(configure())})
        print('Release dimensions and collar capture loaded',flush=True)
        rear_pads(c)
        centers=[(MOUNT_RADIUS,0),(-MOUNT_RADIUS,0),(0,MOUNT_RADIUS),(0,-MOUNT_RADIUS)]
        circle_cut(c,'Four metal horn mounting holes',centers,SCREW_CLEARANCE,PEG_ROOT_Y-.02,
                   FLANGE_THICKNESS+.04,216)
        circle_cut(c,'Four recessed M4 socket heads',centers,SCREW_COUNTERBORE,PEG_ROOT_Y-.02,
                   SCREW_COUNTERBORE_DEPTH+.02,216)
        print('M4 pattern and head seats cut',flush=True)
        before={b['id'] for b in c.call('solid_scene')['bodies']}
        step=ROOT/'source/horn-1906-0025-0032/1906-0025-0032.STEP'
        c.call('solid_import_step',{'file_name':step.name,'data_base64':base64.b64encode(step.read_bytes()).decode()})
        horn=next(b['id'] for b in c.call('solid_scene')['bodies'] if b['id'] not in before)
        # Supplier front faces +Y. Our horn faces the auger (-Y).
        c.call('solid_move_copy',{'body_ids':[horn],'translation':{'x':0,'y':HORN_TRANSLATION_Y,'z':0},
            'rotation':[1,0,0,0],'pivot':{'x':0,'y':0,'z':0},'copy':False})
        c.call('assembly_create_component',{'name':'Metal 25T horn - goBILDA 1906-0025-0032',
            'body_ids':[horn],'absorb_promoted_bodies':True})
        c.call('set_body_appearance',{'body_id':horn,'color':{'r':174,'g':184,'b':196,'a':255},
            'material_name':'Aluminum - clear anodized - purchased'})
        model=c.call('cad_project_model');model=json.loads(model) if isinstance(model,str) else model
        model,cleanup=clean_checked(c,model,SLEEVE_BODY)
        scene=c.call('solid_scene');assert not scene['errors'],scene['errors']
        report=c.call('assembly_interference_check',{'clearance_threshold_mm':.05})
        assert report['exact']
        unexpected=[p for p in report['pairs'] if p['interfering'] and {p['body_a'],p['body_b']}!={15,90}]
        assert not unexpected,unexpected
        model=save_project(c,ROOT/'garden-auger-drive.nbcad')
        (ROOT/'.build/model.json').write_text(json.dumps(model))
        (ROOT/'.build/scene.json').write_text(json.dumps(scene))
        (ROOT/'.build/cleanup.json').write_text(json.dumps(cleanup,indent=2))
        parts={'sleeve':SLEEVE_BODY,'horn':horn,'hub_diameter_mm':JOURNAL_DIAMETER,
            'square_peg_mm':PEG,'square_socket_mm':SOCKET,'socket_depth_mm':SOCKET_DEPTH,
            'peg_corner_radius_mm':PEG_RADIUS,'socket_corner_radius_mm':SOCKET_RADIUS,
            'retention':'integral collar captured between 3 mm chassis webs',
            'metal_horn':'goBILDA 1906-0025-0032','mount_screws':'4 x M4 x 6 ISO 4762',
            'center_screw':'M3 x 6; confirm against factory thread at first fit',
            'heat_set_insert':{'quantity':4,'model':'ruthex RX-M3x5.7','thread':'M3',
                'outer_diameter_mm':4.6,'length_mm':5.7,'pilot_diameter_mm':4.0,'pilot_depth_mm':6.7}}
        (ROOT/'.build/parts.json').write_text(json.dumps(parts,indent=2))
        export(c)
        print('Release B native assembly and print geometry saved',flush=True)


if __name__=='__main__':main()
