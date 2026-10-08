"""Review the measured servo and tighten existing locating cuts in native CAD.

The 27/38 readings are independent inputs. Ear span, thickness, case width,
shaft-to-ear and shaft-to-case offset remain drawing references. This builds
a TEST ARTICLE, never a physically qualified release or a hardware tolerance.
"""
from __future__ import annotations

import base64
import copy
import itertools
import json
import math
from pathlib import Path

from build_servo_rear_fit_test import digest, read_model, native_plane, package_test
from cad_build import Builder, profile, save_project
from cad_client import CadClient

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'experiments/garden-auger-servo-27mm-test.limo'
CAD = ROOT / 'experiments/garden-auger-servo-snug-test.limo'
PRINT = ROOT / 'garden-auger-lower-servo-snug-test.3mf'
REPORT = ROOT / 'servo-snug-review.json'
BUILD = ROOT / '.build/servo-snug-review'


def pairs(result, moving, fixed):
    assert result['exact'], result
    return [{k: p[k] for k in ('body_a', 'body_b', 'interfering',
             'minimum_clearance_mm', 'overlap_volume_mm3')}
            for p in result['pairs'] if bool(moving & {p['body_a'], p['body_b']})
            and bool(fixed & {p['body_a'], p['body_b']})]


def set_pose(client, occurrence, shift=(0, 0, 0), axis=None, degrees=0, pivot=(0, 0, 0)):
    q = [0., 0., 0., 1.]
    translation = list(shift)
    if axis is not None:
        theta = math.radians(degrees)
        q[axis], q[3] = math.sin(theta/2), math.cos(theta/2)
        # Rodrigues rotation of the pivot about a principal axis.
        rotated = list(pivot)
        a, b = [(1, 2), (2, 0), (0, 1)][axis]
        rotated[a] = math.cos(theta)*pivot[a]-math.sin(theta)*pivot[b]
        rotated[b] = math.sin(theta)*pivot[a]+math.cos(theta)*pivot[b]
        translation = [s+p-r for s, p, r in zip(shift, pivot, rotated)]
    client.call('assembly_set_occurrence_pose', {'occurrence_id': occurrence,
        'local_pose': {'translation': translation, 'rotation': q}})


def independent_probe(client):
    before = {b['id'] for b in client.call('solid_scene')['bodies']}
    b = Builder(client)
    # Owner: case length 38; rear from nominal ear underside 165.5 + 27.
    # The source's right-edge-to-shaft 10 is explicitly provisional.
    b.box('Inspection only - measured 38 by 27 servo case',
          (-28, 152.7, 10, 192.5, -10, 10), 'new_body', [])
    body = next(iter({b['id'] for b in client.call('solid_scene')['bodies']}-before))
    # Fill mounting slots so they cannot hide collisions with the locating seats.
    b.box('Inspection only - left solid ear', (-38, 162.8, -28, 165.5, -10, 10), 'join', [body])
    b.box('Inspection only - right solid ear', (10, 162.8, 18, 165.5, -10, 10), 'join', [body])
    client.call('assembly_create_component', {'name': 'Inspection only - independent servo probe',
        'body_ids': [body], 'absorb_promoted_bodies': True})
    m = client.call('cad_project_model')
    m = json.loads(m) if isinstance(m, str) else m
    oid = next(o['id'] for o in m['assembly']['component_structure']['occurrences']
               if o['name'] == 'Inspection only - independent servo probe')
    return body, oid


def movement_review(client, revised=False):
    body, oid = independent_probe(client)
    records = []

    def inspect(axis, value, rotate=False):
        if rotate:
            set_pose(client, oid, axis=axis, degrees=value, pivot=(-10, 164.15, 0))
        else:
            shift = [0., 0., 0.]
            shift[axis] = value
            set_pose(client, oid, shift)
        ps = pairs(client.call('assembly_interference_check', {
            'occurrence_ids': [6, 7, oid], 'clearance_threshold_mm': 2}), {body}, {26, 46})
        assert len(ps) == 2
        return ps

    nominal = inspect(0, 0)
    assert not any(p['interfering'] for p in nominal)
    limits = [[.2,.2],[.15,.15],[.2,.2]] if revised else [[.5,.4],[.2,.2],[.4,.4]]
    for axis in range(3):
        for sign, limit in zip([-1,1], limits[axis]):
            lo,hi=limit-.01,limit+.01
            passing=inspect(axis,sign*lo)
            blocked=inspect(axis,sign*hi)
            assert not any(p['interfering'] for p in passing), (axis,sign,lo,passing)
            assert any(p['interfering'] for p in blocked), (axis,sign,hi,blocked)
            records.append({'motion':'translation','axis':'XYZ'[axis],'direction':sign,'unit':'mm',
                'last_clear_magnitude':lo,'first_blocked_magnitude':hi,
                'clear_pairs':passing,'blocked_pairs':blocked})
            print(f'Nest translation {"XYZ"[axis]} {sign:+d}: clear {lo:.2f}, blocked {hi:.2f} mm',flush=True)
    set_pose(client, oid)
    return {'nominal_pairs': nominal, 'one_axis_contact_brackets': records,
            'rotation_pivot_mm': [-10, 164.15, 0],
            'probe_input_mm': {'case_length_measured': 38, 'ear_to_rear_measured': 27,
                'case_width_source': 20, 'ear_thickness_source': 2.7, 'ear_span_source': 56,
                'right_case_edge_to_shaft_source': 10, 'ear_faces_source_world_y': [162.8,165.5]},
            'scope': 'Each translation bracket uses exact native placed solids at discrete poses. Other motions are zero. This is not a simultaneous six-DOF or continuous contact solution. Angular play is not qualified.'}


def native_cylinder(body, radius, axis=1, location=None):
    candidates = [f for f in body['faces'] if f.get('cylinder')
                  and abs(f['cylinder']['radius']-radius) < 1e-7
                  and abs(abs(list(f['cylinder']['axis'].values())[axis])-1) < 1e-7]
    if location:
        candidates = [f for f in candidates if all(abs(f['cylinder']['origin'][k]-v)<1e-7
                                                     for k, v in location.items())]
    assert candidates, (body['id'], radius, location)
    f = candidates[0]
    return {'body_id':body['id'],'face_key':f['key'],'cylinder':f['cylinder'],
            'native_boundary_circles':[{'edge_key':e['key'],'circle':e['circle']}
                for e in body['edges'] if e['key'] in f['edge_keys'] and e.get('circle')]}


def print_review(c):
    c.call('upsert_named_view', {'name':'Print - current lower servo fit test',
        'camera':{'position':[280,-180,330],'target':[128,128,10.3],'up':[0,0,1]},
        'visible_body_ids':[46], 'occurrence_offsets':[{'occurrence_id':7,
            'translation':[128,-29.2,20.6000002]}], 'print_layout':True,
        'print_bed':{'name':'Bambu X2D main','size_mm':[256,256,261]}})
    preflight=c.call('solid_export_preflight', {'body_ids':[46],
        'named_view':'Print - current lower servo fit test'})
    assert preflight['ok'] and not preflight['timeline_errors']
    bad=[i for i in preflight['layout']['issues']
         if i['code'] in ['below_bed','outside_bed','possible_overlap']]
    assert not bad, bad
    return preflight


def angular_review(c):
    body, oid = independent_probe(c)
    samples=[]
    for axis in range(3):
        for sign in [-1,1]:
            item={'axis':'XYZ'[axis],'direction':sign,'pivot_mm':[-10,164.15,0]}
            for degrees,blocked in [(.1,False),(1.,True)]:
                set_pose(c,oid,axis=axis,degrees=sign*degrees,pivot=(-10,164.15,0))
                ps=pairs(c.call('assembly_interference_check',{'occurrence_ids':[6,7,oid],
                    'clearance_threshold_mm':2}),{body},{26,46})
                assert any(p['interfering'] for p in ps)==blocked,(axis,sign,degrees,ps)
                item['blocked_at_1_degree' if blocked else 'clear_at_0_1_degree']=ps
            samples.append(item)
    return samples


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    preserved = {p: digest(ROOT/p) for p in [
        'garden-auger-direct-drive.nbcad', 'garden-auger-bambu-latest.3mf',
        'garden-auger-lower-fit-test.3mf', str(SOURCE.relative_to(ROOT))]}
    readings = json.loads((ROOT/'source/references/servo-caliper-readings.json').read_text())
    assert readings['readings']['1']['value'] == 27 and readings['readings']['5']['value'] == 38
    original = read_model(SOURCE)
    candidate = copy.deepcopy(original)
    sketches = {s['name']:s for s in candidate['sketches']}
    assert sketches['Sketch45']['basis']['origin'][1] == 194
    profile(sketches['Sketch45'], [(-30.9,-10.2),(10.4,-10.2),(10.4,10.2),(-30.9,10.2)])
    profile(sketches['Sketch62'], [(-38.2,-10.2),(-30.4,-10.2),(-30.4,10.2),(-38.2,10.2)])
    # Keep two loops in the existing ear-cut sketch, rather than new features.
    snap=sketches['Sketch62']['snapshot']
    snap['entities'] += [[9, {'type':'point','position':{'x':10.4,'y':-10.2}}],
        [10, {'type':'point','position':{'x':18.2,'y':-10.2}}],
        [11, {'type':'point','position':{'x':18.2,'y':10.2}}],
        [12, {'type':'point','position':{'x':10.4,'y':10.2}}],
        [13, {'type':'line','start':9,'end':10}], [14, {'type':'line','start':10,'end':11}],
        [15, {'type':'line','start':11,'end':12}], [16, {'type':'line','start':12,'end':9}]]
    snap['next_entity']=16
    sketches['Sketch62']['entity_id_high_water']=16
    ear_sketch=sketches['Sketch62']
    ear_sketch['basis']['origin'][1]=165.65
    datum=next(d for d in candidate['datum_planes'] if d['datum_id']==ear_sketch['plane']['datum_id'])
    datum['basis']['origin'][1]=165.65
    datum['source']['distance']=-165.65
    cut=next(e for e in candidate['extrudes'] if e['feature_id']==183)
    cut['extent']['distance']=3.0
    names={131:'Servo clearance bay - 41.3 by 20.4; 42.3 axial span',
           183:'Servo locating ears - 56.4 outer span; 20.4 capture; 3.0 axial slot'}
    for e in candidate['extrudes']:
        if e['feature_id'] in names:
            e['name']=names[e['feature_id']]
    for f in candidate['document']['history']['features']:
        if f['id'] in names:
            f['name']=names[f['id']]
    candidate['document']['name']='Garden auger - snug servo nest TEST ARTICLE'
    with CadClient(stderr_path=BUILD/'engine-stderr.log') as c:
        engine = {'path':str(c.executable),'sha256':digest(c.executable)}
        c.call('cad_load_project_model', {'model_json':json.dumps(original)})
        old_scene=c.call('solid_scene')
        cache=BUILD/'old-movement.json'
        cache_key={'engine':engine['sha256'],'source':digest(SOURCE),'review_version':2}
        cached=json.loads(cache.read_text()) if cache.exists() else {}
        old_movement=cached['result'] if cached.get('key')==cache_key else movement_review(c)
        cache.write_text(json.dumps({'key':cache_key,'result':old_movement}),encoding='utf-8')
        print('Previous nest contact brackets complete',flush=True)
        c.call('cad_load_project_model', {'model_json':json.dumps(candidate)})
        scene=c.call('solid_scene')
        assert not scene['errors'], scene['errors']
        bodies={b['id']:b for b in scene['bodies']}
        for bid in [15,90,216,221]:
            assert bodies[bid]['mesh']==next(b['mesh'] for b in old_scene['bodies'] if b['id']==bid)
        assert candidate['body_appearances']==original['body_appearances']
        cache=BUILD/'new-movement.json'
        cache_key={'engine':engine['sha256'],'model':__import__('hashlib').sha256(json.dumps(candidate).encode()).hexdigest(),'review_version':2}
        cached=json.loads(cache.read_text()) if cache.exists() else {}
        new_movement=cached['result'] if cached.get('key')==cache_key else movement_review(c,revised=True)
        cache.write_text(json.dumps({'key':cache_key,'result':new_movement}),encoding='utf-8')
        print('Snug nest contact brackets complete',flush=True)
        c.call('cad_load_project_model', {'model_json':json.dumps(candidate)})
        scene=c.call('solid_scene')
        bodies={b['id']:b for b in scene['bodies']}
        measures={}
        for bid in [26,46]:
            measures[str(bid)]={'rear':native_plane(bodies[bid],1,194),
                'ear_front':native_plane(bodies[bid],1,162.65),
                'ear_rear':native_plane(bodies[bid],1,165.65),
                'left_ear_tip':native_plane(bodies[bid],0,-38.2),
                'right_ear_tip':native_plane(bodies[bid],0,18.2),
                'capture':native_plane(bodies[bid],2,10.2 if bid==26 else -10.2),
                'exterior_bed':native_plane(bodies[bid],2,20.6 if bid==26 else -20.6)}
        dimensions={
            'square':{'peg_left':native_plane(bodies[216],0,-7),'peg_right':native_plane(bodies[216],0,7),
                      'socket_left':native_plane(bodies[15],0,-7.2),'socket_right':native_plane(bodies[15],0,7.2),
                      'peg_radius':native_cylinder(bodies[216],1),'socket_radius':native_cylinder(bodies[15],1.2),
                      'tip':native_plane(bodies[216],1,129.5),'root':native_plane(bodies[216],1,141.1),
                      'mouth':native_plane(bodies[15],1,139.5),'bottom':native_plane(bodies[15],1,127.5)},
            'bearing':{'journal':native_cylinder(bodies[15],14), 'sleeve_bore':native_cylinder(bodies[221],14.3),
                       'sleeve_outer':native_cylinder(bodies[221],17),'sleeve_front':native_plane(bodies[221],1,120.6),
                       'sleeve_rear':native_plane(bodies[221],1,131),
                       'housing_sleeve_chamber':native_cylinder(bodies[46],17.8),
                       'housing_stop_front':native_plane(bodies[46],1,120.3),
                       'housing_stop_rear':native_plane(bodies[46],1,131.2),
                       'collar_front':native_plane(bodies[15],1,114),'collar_rear':native_plane(bodies[15],1,117),
                       'housing_collar_front':native_plane(bodies[46],1,113.7),
                       'housing_collar_rear':native_plane(bodies[46],1,117.3)},
            'adapter':{'pilot':native_cylinder(bodies[216],2.85), 'boss':native_cylinder(bodies[216],12),
                       'flange':native_cylinder(bodies[216],14),'shaft_seat':native_plane(bodies[216],1,148.7),
                       'boss_end':native_plane(bodies[216],1,152.4),'head_seat':native_plane(bodies[216],1,146.1),
                       'head_access':native_cylinder(bodies[216],3.2),'screw_passage':native_cylinder(bodies[216],1.7)},
            'inserts': [native_cylinder(bodies[46],2,axis=2,location={'x':x,'y':y})
                        for x,y in [(-27,118.5),(27,118.5),(-36,196.8),(16,196.8)]]}
        for insert in dimensions['inserts']:
            levels=sorted({e['circle']['center']['z'] for e in insert['native_boundary_circles']})
            assert levels==[-6.7,0.0], levels
            insert['native_trimmed_depth_mm']=levels[1]-levels[0]
        nominal=c.call('assembly_interference_check', {'clearance_threshold_mm':2})
        assert nominal['exact'] and not any(p['interfering'] for p in nominal['pairs'])
        motion=[]
        # Common shaft displacement: move servo, adapter and auger together.
        for shift in [(0,0,0)]+list(itertools.product([-.19,.19],[-.14,.14],[-.19,.19])):
            for oid in [8,14]:
                set_pose(c,oid,shift)
            c.call('assembly_set_occurrence_pose', {'occurrence_id':3,'local_pose':{
                'translation':[shift[0],148.7+shift[1],shift[2]],
                'rotation':[math.sqrt(.5),0,0,math.sqrt(.5)]}})
            result=c.call('assembly_interference_check', {'clearance_threshold_mm':2})
            assert result['exact'] and not any(p['interfering'] for p in result['pairs']), (shift,result)
            motion.append({'common_drive_translation_mm':list(shift),'result':result})
        print('Nine coupled assembly poses clear',flush=True)
        c.call('cad_load_project_model', {'model_json':json.dumps(candidate)})
        angular=angular_review(c)
        c.call('cad_load_project_model', {'model_json':json.dumps(candidate)})
        auger=[]
        for angle in range(0,360,30):
            for axial in [-.29,.29]:
                set_pose(c,8,(0,axial,0),axis=1,degrees=angle)
                result=c.call('assembly_interference_check', {
                    'occurrence_ids':[6,7,8,16], 'clearance_threshold_mm':2})
                ps=pairs(result,{15,90},{26,46,221})
                assert ps and not any(p['interfering'] for p in ps), (angle,axial,ps)
                auger.append({'angle_deg':angle,'axial_mm':axial,'pairs':ps})
        c.call('cad_load_project_model', {'model_json':json.dumps(candidate)})
        sections=[]
        for tag,bid,plane,offset,probe in [
            ('ear-nest',46,'xy',-.1,164.15),('servo-floor',46,'xz',180,-10),
            ('rear-wall',46,'xy',-5,193),('square-socket',15,'xz',134,0),
            ('adapter-seat',216,'xy',0,149),('pla-bushing',221,'xz',125,0)]:
            sec=c.call('solid_section_review', {'body_id':bid,'plane':plane,'offset_mm':offset,
                'probe_mm':probe,'deflection_mm':.01})
            (BUILD/f'{tag}.json').write_text(json.dumps(sec,indent=2),encoding='utf-8')
            sections.append({'name':tag,'body_id':bid,'plane':plane,'offset_mm':offset,'result':sec})
        assembled_preflight=c.call('solid_export_preflight', {'body_ids':[26,46,15,90,216,221]})
        assert assembled_preflight['ok'] and not assembled_preflight['timeline_errors'],assembled_preflight
        # Assembly locations are not bed locations. Check a matching one-half
        # presentation placement natively; do not accept assembled bed warnings.
        preflight=print_review(c)
        save_project(c,CAD)
        export=c.call('solid_export_3mf', {'body_ids':[46],'scope':'definition',
            'linear_deflection':.08,'angular_deflection':.2,'slicer_target':'standard'})
        packaging=package_test(base64.b64decode(export['bytes_base64']),output=PRINT,note=(
            'SNUG SERVO NEST TEST ARTICLE. Ear slots 3.00, outer-tip span 56.40, '
            'case/ear capture width 20.40 mm. Rear wall retained at Y194 for owner 27 mm reading. '
            'Drawing ear span/thickness/width and shaft offsets require physical fit confirmation. '
            'One lower half only; upper half must use the same revision for capture. '
            'Saved process/object settings preserved; fresh slice required.'))
        bambu_inspection=c.call('bambu_template_inspect', {
            'template_base64':base64.b64encode(PRINT.read_bytes()).decode()})
    assert all(digest(ROOT/p)==h for p,h in preserved.items())
    report={'status':'Native CAD reviewed; snug test article, physical fit unqualified',
        'native_engine':engine,'source_sha256':digest(SOURCE),
        'cad':str(CAD.relative_to(ROOT)),'cad_sha256':digest(CAD),'print':PRINT.name,'print_checks':packaging,
        'readings':readings,'previous_movement':old_movement,'revised_movement':new_movement,
        'native_nest_faces':measures,'native_component_dimensions':dimensions,
        'designed_nominal_mm':{'ear_slot':3.,'ear_span_capture':56.4,'case_and_ear_width_capture':20.4,
            'total_ear_axial_movement':.3,'total_lateral_movement':.4,'total_clamshell_capture_movement':.4,
            'rear_stop_to_wall':28.35,'rear_room_with_27mm_at_stop':1.35,
            'conservative_case_plan_clearance_bay':41.3,'body_space_excess_for_measured_38_case':3.3,
            'square_peg':14,'square_socket':14.4,'square_nominal_engagement':10,
            'square_nominal_tip_gap':2,'square_nominal_flange_gap':1.6,
            'journal':28,'sleeve_bore':28.6,'sleeve_outer':34,'sleeve_capture_diameter':35.6,
            'collar_nominal_axial_float':.6,'sleeve_nominal_axial_float':.5,
            'insert_pilot_diameter':4,'insert_pilot_depth':6.7,
            'adapter_pilot_diameter_trial':5.7,'adapter_pilot_depth_reference':3.7,
            'adapter_head_seat_to_shaft_seat':2.6,'adapter_source_case_gap':.3},
        'native_nominal_assembly':nominal,'native_coupled_assembly_samples':motion,
        'native_auger_rotation_axial_samples':auger,'native_sections':sections,
        'native_preflight':preflight,'assembled_geometry_preflight':assembled_preflight,
        'native_bambu_project_inspection':bambu_inspection,
        'native_servo_angular_samples':angular,
        'angular_scope':'For each principal axis about the ear-centre pivot, +/-0.1 degree clears and +/-1 degree is blocked. Other motions are zero. These discrete samples do not establish maximum angular play or a simultaneous six-DOF contact envelope.',
        'unchanged_nonhousing_body_meshes':[15,90,216,221],
        'additional_geometry_features':0,'materials_and_colors_preserved':True,
        'preserved_files_sha256':preserved,'temporary_probes_saved_or_exported':False,
        'locating_scheme':'Ear axial faces own Y, ear outer tips own X, case/ear capture faces own Z. The larger case plan bay and rear bay provide clearance, not location. Close matching halves to capture Z; no separate servo retaining hardware.',
        'limitations':[
            'Only 27 mm ear-to-rear and 38 mm case plan length are user measurements; uncertainty not supplied.',
            'Ear span 56, thickness 2.7, width 20 and shaft-relative offsets remain source dimensions. The conservative reference is not a fully measured servo.',
            '0.15/0.20 mm per-side locating clearances are test design values, not measured printer capability or guaranteed zero play.',
            'Six independent translation contact brackets and sampled coupled poses do not prove angular play or every combined translation/rotation or continuous collision-free motion.',
            'Native section spans are sampled material intervals, not global minimum thickness, GD&T certification, torque, creep or strength simulation.',
            'Actual adapter shaft seating, factory screw length/usable thread depth, cable boot and physical printed fit remain unqualified.',
            'Production models were not replaced; test both matching revised housing halves before a complete release.']}
    REPORT.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    for section in sections:
        (ROOT/f"renders/servo-snug-{section['name']}.svg").write_text(section['result']['svg'],encoding='utf-8')
    print(json.dumps({'cad':report['cad'],'print':PRINT.name,'native_review_report':REPORT.name,
        'clear_coupled_poses':len(motion),'clear_auger_samples':len(auger),'production_preserved':True}),flush=True)


if __name__=='__main__':
    main()
