"""Editable split-seam cable route; assumed cable envelopes are not supplier data."""
import copy
import math
from cad_build import profile

CHANNEL_WIDTH = 6.0
CHANNEL_HEIGHT = 8.0
BEND_RADIUS = 8.0
BOOT_BAY = (10.4, 180.6, 16.0, 191.2)
ROUTE_START = (10.05, 187.0)
STRAIGHT_END = (20.0, 187.0)
BEND_CENTER = (20.0, 195.0)
TURN_END = (28.0, 195.0)
ROUTE_END = (28.0, 214.5)
CABLE_DIAMETER_TRIAL = 4.0
NAME = 'Cable rear outlet - one tangent bend toward controls'


def route_points(step_degrees=3.0):
    points=[ROUTE_START,STRAIGHT_END]
    for center,angles in [(BEND_CENTER,(270,360))]:
        count=math.ceil(abs(angles[1]-angles[0])/step_degrees)
        for i in range(1,count+1):
            angle=math.radians(angles[0]+(angles[1]-angles[0])*i/count)
            points.append((center[0]+BEND_RADIUS*math.cos(angle),
                           center[1]+BEND_RADIUS*math.sin(angle)))
    points.append(ROUTE_END)
    return points


def route_profile(sketch):
    # Native analytic arcs, trimmed into the retained boot bay. Positive CCW
    # arcs can be reversed because native profile connectivity is undirected.
    inner=BEND_RADIUS-CHANNEL_WIDTH/2;outer=BEND_RADIUS+CHANNEL_WIDTH/2
    points=[(10.4,180.6),(16,180.6),(16,184),(20,184),
            (31,195),(31,214.5),(25,214.5),(25,195),
            (20,190),(16,190),(16,191.2),(10.4,191.2)]
    arcs={3:(BEND_CENTER,outer,3*math.pi/2,2*math.pi),
          7:(BEND_CENTER,inner,3*math.pi/2,2*math.pi)}
    profile(sketch,points,arcs)


def apply_cable_route(original):
    model=copy.deepcopy(original)
    sketch=next(s for s in model['sketches'] if s['feature_id']==272)
    route_profile(sketch);sketch['name']=NAME
    for f in model['document']['history']['features']:
        if f['id'] in (272,278):f['name']=NAME
    cut=next(e for e in model['extrudes'] if e['feature_id']==278)
    cut.update(name=NAME,sketch_name=NAME,
        extent={'type':'two_sides','distance':CHANNEL_HEIGHT/2,
                'second_distance':CHANNEL_HEIGHT/2})
    # Rear pad joins otherwise refill the boot bay. Apply the existing cut
    # after every housing join; do not add a compensating second cut.
    history=model['document']['history']['features']
    joins={e['feature_id'] for e in model['extrudes'] if e['operation']=='join'
           and bool({26,46}&set(e['target_body_ids']))}
    cut_feature=next(f for f in history if f['id']==278)
    history.remove(cut_feature)
    history.insert(max(i for i,f in enumerate(history) if f['id'] in joins)+1,cut_feature)
    return model


def route_spec():
    return {'channel_width_mm':CHANNEL_WIDTH,'channel_height_mm':CHANNEL_HEIGHT,
        'centerline_bend_radius_mm':BEND_RADIUS,'boot_bay_xy_mm':list(BOOT_BAY),
        'centerline_start_mm':list(ROUTE_START),'centerline_end_mm':list(ROUTE_END),
        'exit_direction':'+Y, rear face of housing toward controls',
        'cut_applied_after_housing_pad_joins':True,
        'route_length_mm':STRAIGHT_END[0]-ROUTE_START[0]+math.pi*BEND_RADIUS/2+ROUTE_END[1]-TURN_END[1],
        'trial_bundle_diameter_mm':CABLE_DIAMETER_TRIAL,
        'dimensional_authority':'Servo dimensions are drawing-controlled. Boot size, bundle diameter, seam height and bend radius are design trials, not INJORA published dimensions.',
        'strain_relief':'Factory servo boot only; this clearance channel does not clamp the wire or qualify pull resistance.'}
