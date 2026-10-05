"""Prepare the current direct-drive construction seed without legacy variants."""

import json
import math

from cad_build import prepare_baseline, profile
from design_parameters import (
    PEG, SOCKET, PEG_RADIUS, SOCKET_RADIUS, PEG_ROOT_Y, PEG_TIP_Y,
    FLANGE_THICKNESS, FLANGE_DIAMETER, SLEEVE_FRONT, SLEEVE_REAR,
    SERVO_SHIFT, SERVO_TRANSLATION_Y, REAR_SCREW_Y, housing_profile,
)
from direct_drive_parameters import (
    HEAD_ACCESS, HEAD_SEAT_Y, UNDERHEAD_RELIEF_DIAMETER,
    UNDERHEAD_RELIEF_DEPTH, SCREW_CLEARANCE,
)
from servo_dimensions import configure_reference


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
    old='Servo interface placeholder - unqualified'
    new='Direct adapter axial screw access and head seat'
    s[old]['name']=new
    profile(s[old],[(129.3,0),(129.3,HEAD_ACCESS/2),(HEAD_SEAT_Y,HEAD_ACCESS/2),
        (HEAD_SEAT_Y,UNDERHEAD_RELIEF_DIAMETER/2),
        (HEAD_SEAT_Y+UNDERHEAD_RELIEF_DEPTH,SCREW_CLEARANCE/2),
        (HEAD_SEAT_Y+UNDERHEAD_RELIEF_DEPTH,0)])
    for r in m['revolves']:
        if r['sketch_name']==old:r['sketch_name']=new
    for f in m['document']['history']['features']:
        if f['name']==old:f['name']=new
        if f['id'] in (10,307):f['suppressed']=True
    # Feature 10 modeled an unsupported stationary nose. The confirmed
    # diagram controls the case/ear stack; the rotating shaft is unmodeled.
    for group in ('definitions','occurrences'):
        for item in m['assembly']['component_structure'][group]:
            if item.get('component_id',item['id'])==3:
                item['name']='INJS035-360 case reference - shaft and nose unmodeled'
    moved=set()
    for name in ['Sketch45','Sketch62']:
        k=s[name];k['basis']['origin'][1]+=SERVO_SHIFT
        datum=k['plane']['datum_id']
        if datum not in moved:
            p=next(p for p in m['datum_planes'] if p['datum_id']==datum)
            p['basis']['origin'][1]+=SERVO_SHIFT;p['source']['distance']-=SERVO_SHIFT;moved.add(datum)
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
    m['document']['name']='Garden auger - round pilot direct press-fit prototype'
    m['drawings']['sheets']=[]
    return configure_reference(m)


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
