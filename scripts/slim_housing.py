"""Flat print face and tangent blended exterior; retain mating datums."""
import copy
import math
from cad_build import profile
from model_cleanup import prune
from cable_routing import apply_cable_route, route_spec

MIN_WALL = 2.8
HALF_DEPTH = 17.8 + MIN_WALL

def rounded_profile(sketch, vertices, radii):
    """Author tangent lines/arcs in the existing native sketch."""
    points=[]; arcs={}; n=len(vertices)
    for i,v in enumerate(vertices):
        p=vertices[(i-1)%n]; q=vertices[(i+1)%n]
        a=(p[0]-v[0],p[1]-v[1]); b=(q[0]-v[0],q[1]-v[1])
        la=math.hypot(*a); lb=math.hypot(*b)
        a=tuple(x/la for x in a); b=tuple(x/lb for x in b)
        angle=math.acos(max(-1.,min(1.,a[0]*b[0]+a[1]*b[1])))
        radius=radii.get(i,0.)
        if not radius:points.append(v);continue
        distance=radius/math.tan(angle/2)
        assert distance<min(la,lb)/2,(i,distance,la,lb)
        entry=tuple(v[k]+a[k]*distance for k in (0,1))
        leave=tuple(v[k]+b[k]*distance for k in (0,1))
        bisector=(a[0]+b[0],a[1]+b[1]); length=math.hypot(*bisector)
        center=tuple(v[k]+bisector[k]/length*radius/math.sin(angle/2) for k in (0,1))
        start=math.atan2(entry[1]-center[1],entry[0]-center[0])
        end=math.atan2(leave[1]-center[1],leave[0]-center[0])
        turn=(-a[0])*b[1]-(-a[1])*b[0]
        if turn>0:
            while end<start:end+=2*math.pi
        else:
            while end>start:end-=2*math.pi
            # Native sketch arcs use a positive CCW sweep. Reverse the
            # endpoints for a concave corner; profile connectivity is
            # undirected. A negative sweep creates an unwanted major arc.
            start,end=end,start
        arcs[len(points)]=(center,radius,start,end)
        points.extend([entry,leave])
    profile(sketch,points,arcs)

def slim_housing(original):
    model=copy.deepcopy(original)
    sketches={s['name']:s for s in model['sketches']}
    extrudes={e['feature_id']:e for e in model['extrudes']}
    features={f['id']:f for f in model['document']['history']['features']}
    outline=[(-34,107.9),(34,107.9),(34,134),(17.6,144),
        (22.3,158.8),(22.3,169.5),(13.2,180),(13.2,189.8),
        (23,195),(23,206.5),(-43,206.5),(-43,195),
        (-33.7,189.8),(-33.7,180),(-42.3,169.5),
        (-42.3,158.8),(-33.7,144),(-34,134)]
    blank=next(s for s in model['sketches'] if s['feature_id']==40)
    rounded_profile(blank,outline,{2:4,3:3,4:4,5:4,6:3,7:2,
        8:2,11:2,12:2,13:3,14:4,15:4,16:3,17:1})
    name='Housing continuous blended outer profile'
    blank['name']=name; features[40]['name']=name
    extrudes[41].update(name=name,sketch_name=name,
        extent={'type':'two_sides','distance':HALF_DEPTH,'second_distance':HALF_DEPTH})
    features[41]['name']=name
    handle=sketches['Sketch18']
    profile(handle,[(188,-HALF_DEPTH),(199.5,-HALF_DEPTH),(206.5,-13.6),
        (206.5,13.6),(199.5,HALF_DEPTH),(188,HALF_DEPTH),
        (181,13.6),(181,-13.6)])
    handle['name']='Handles - bed lands and 45 degree shoulders'
    features[49]['name']=handle['name'];features[50]['name']=handle['name']
    extrudes[50].update(name=handle['name'],sketch_name=handle['name'])
    for fid in (263,264,265,267,268,269,271,275,276,277):
        if fid in features:features[fid]['suppressed']=True
    for name in ('Sketch54','Sketch55','Sketch79'):
        sketches[name]['basis']['origin'][2]=HALF_DEPTH
    plane=next(p for p in model['datum_planes'] if p['datum_id']==33)
    plane['basis']['origin'][2]=HALF_DEPTH;plane['source']['distance']=HALF_DEPTH
    extrudes[157]['extent']['distance']=HALF_DEPTH
    extrudes[159]['extent']['distance']=HALF_DEPTH-12.7
    extrudes[226]['extent']['distance']=HALF_DEPTH-8
    model=apply_cable_route(model)
    model,cleanup=prune(model)
    return model,{'nominal_minimum_exterior_wall_mm':MIN_WALL,
        'servo_floor_mm':HALF_DEPTH-10.4,'servo_section_total_depth_mm':2*HALF_DEPTH,
        'bearing_section_total_depth_mm':2*HALF_DEPTH,'handle_total_depth_mm':2*HALF_DEPTH,
        'handle_bed_land_width_mm':11.5,'handle_shoulders_degrees':45,
        'history_before':len(original['document']['history']['features']),
        'history_after':len(model['document']['history']['features']),
        'removed_history_entries':cleanup['removed_inactive_features'],
        'preserved_screw_head_seats_z_mm':[8,12.7],
        'scope':'Flat underside, tangent blended exterior, bed-supported handles and a curved rear cable route. Mating datums preserved.',
        'cable_route':route_spec(),
        'tradeoff':'Fixed bearing axis requires 10.2 mm servo floor and thicker grips for flat pocket-up printing.'}
