"""Reduce the shared housing blank and reuse its exterior cut.

This changes only exterior stock. Servo pockets, drive seats, ear capture,
locators and fastener seating datums remain authored by the upstream model.
2.8 mm is a nominal manufacturing target, not a load qualification.
"""
import copy

from cad_build import profile
from model_cleanup import prune

MIN_WALL = 2.8
HALF_DEPTH = 17.8 + MIN_WALL
SERVO_OUTER_HALF = 10.4 + MIN_WALL


def slim_housing(original):
    model = copy.deepcopy(original)
    sketches = {s['name']: s for s in model['sketches']}
    extrudes = {e['feature_id']: e for e in model['extrudes']}
    features = {f['id']: f for f in model['document']['history']['features']}
    # Keep 2.8 mm around the rectangular ear pockets, including their
    # corners. Rear wings retain the original mounting-hole locations.
    outline = [(-34,107.9),(34,107.9),(34,134),(17.6,134),
        (17.6,156.4),(13.2,156.4),(13.2,159.8),(21.3,159.8),
        (21.3,168.5),(13.2,168.5),(13.2,189.8),(23,189.8),
        (23,206.5),(-43,206.5),(-43,189.8),(-33.7,189.8),
        (-33.7,168.5),(-41.3,168.5),(-41.3,159.8),
        (-33.7,159.8),(-33.7,131.2),(-34,131.2)]
    profile(sketches['Chassis stepped outer blank'], outline)
    extrudes[41]['extent'] = {'type':'two_sides', 'distance':HALF_DEPTH,
                             'second_distance':HALF_DEPTH}
    # Obsolete body extensions, mirrors and combines become unnecessary.
    for feature_id in (263,267,268,269,271,275,276,277):
        features[feature_id]['suppressed'] = True
    for name in ('Sketch54','Sketch55','Sketch79'):
        sketches[name]['basis']['origin'][2] = HALF_DEPTH
    plane = next(p for p in model['datum_planes'] if p['datum_id'] == 33)
    plane['basis']['origin'][2] = HALF_DEPTH
    plane['source']['distance'] = HALF_DEPTH
    extrudes[157]['extent']['distance'] = HALF_DEPTH
    # Preserve the actual under-head planes, hence existing screw lengths.
    extrudes[159]['extent']['distance'] = HALF_DEPTH - 12.7
    extrudes[226]['extent']['distance'] = HALF_DEPTH - 8

    floor = sketches['Sketch94']
    floor['name'] = 'Common thin-floor exterior profile'
    floor['plane'] = {'type':'origin_plane','plane':'yz'}
    floor['basis'] = {'origin':[0.,0.,0.], 'u':[0.,1.,0.],
                      'v':[0.,0.,1.], 'normal':[1.,0.,0.]}
    upper = [(107,20.6),(134,20.6),(137,17.6),(156.4,17.6),
             (160.8,13.2),(207,13.2),(207,50),(107,50)]
    profile(floor, upper)
    entities = floor['snapshot']['entities']
    count = len(upper)
    base = 2 * count
    for i,(y,z) in enumerate(upper):
        entities.append([base+i+1, {'type':'point','position':{'x':y,'y':-z}}])
    for i in range(count):
        entities.append([base+count+i+1, {'type':'line', 'start':base+i+1,
                                        'end':base+(i+1)%count+1}])
    floor['snapshot']['next_entity'] = 4 * count
    floor['entity_id_high_water'] = 4 * count
    extrudes[265].update(name='Common exterior floor relief - both halves',
        sketch_name=floor['name'], profile_indices=[0,1],
        target_body_ids=[26,46], extent={'type':'two_sides',
        'distance':150.,'second_distance':150.}, flip=False)
    features[264]['name'] = floor['name']
    features[265]['name'] = extrudes[265]['name']
    # Trim the common blank after the shared drive cavity. Fastener pads
    # are joined afterward to retain the rear recessed screw-head seats.
    history = model['document']['history']['features']
    moved = [f for f in history if f['id'] in (264,265)]
    history[:] = [f for f in history if f['id'] not in (264,265)]
    index = next(i for i,f in enumerate(history) if f['id'] == 301) + 1
    history[index:index] = moved
    model, cleanup = prune(model)
    return model, {'nominal_minimum_exterior_wall_mm':MIN_WALL,
        'servo_floor_mm':MIN_WALL, 'servo_section_total_depth_mm':2*SERVO_OUTER_HALF,
        'bearing_section_total_depth_mm':2*HALF_DEPTH,
        'history_before':len(original['document']['history']['features']),
        'history_after':len(model['document']['history']['features']),
        'removed_history_entries':cleanup['removed_inactive_features'],
        'preserved_screw_head_seats_z_mm':[8,12.7],
        'scope':'Exterior floor and side-wall reduction. Local bearing, ear and fastener transitions retain extra stock.'}
