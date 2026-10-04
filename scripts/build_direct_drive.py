"""Round pilot press-fit prototype; retain release B as metal-horn fallback.

The metal servo splines form their engagement into an undersized PETG bore.
No tiny spline teeth are printed. Actual shaft and screw fit remain unverified.
"""
import base64
import json
import math
from pathlib import Path

from cad_client import CadClient
from cad_build import Builder, profile, save_project
from build_model import configure, rear_pads
from model_cleanup import clean_checked
from direct_drive_parameters import *

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.build/direct-drive'


def model_value(c):
    m=c.call('cad_project_model')
    return json.loads(m) if isinstance(m,str) else m


def setup():
    m=configure()
    sketches={s['name']:s for s in m['sketches']}
    sketches['Sketch101']['snapshot']['entities'][0][1]['radius']=14.0
    next(e for e in m['extrudes'] if e['feature_id']==293)['extent']['distance']=5.0
    # The 28 mm flange fits within the journal-size rear chamber. No broad
    # metal-horn cavity or four M4 mounting features are needed.
    profile(sketches['Chassis integral thrust stops and journal seat'],
        [(110.9,0),(110.9,14.8),(112.9,14.8),(113.7,15.6),
         (113.7,17.8),(117.3,17.8),(117.3,15.5),(118.5,14.8),
         (120.3,14.8),(120.3,17.8),(131.2,17.8),(131.2,14.8),
         (153,14.8),(153,0)])
    old='Metal horn pilot and center screw head relief'
    new='Direct adapter axial screw access and head seat'
    sketches[old]['name']=new
    profile(sketches[old],[(129.3,0),(129.3,HEAD_ACCESS/2),(HEAD_SEAT_Y,HEAD_ACCESS/2),
        (HEAD_SEAT_Y,UNDERHEAD_RELIEF_DIAMETER/2),
        (HEAD_SEAT_Y+UNDERHEAD_RELIEF_DEPTH,SCREW_CLEARANCE/2),
        (HEAD_SEAT_Y+UNDERHEAD_RELIEF_DEPTH,0)])
    for r in m['revolves']:
        if r['sketch_name']==old:r['sketch_name']=new
    for f in m['document']['history']['features']:
        if f['name']==old:f['name']=new
    m['document']['name']='Garden auger - round pilot direct press-fit prototype'
    # Release B's drawings describe a separate horn and must not accompany
    # this different connection. Its release drawing stays intact.
    m['drawings']['sheets']=[]
    return m


def check_assembly(c,m):
    auger=next(o['id'] for o in m['assembly']['component_structure']['occurrences'] if o['component_id']==8)
    adapter=next(o['id'] for o in m['assembly']['component_structure']['occurrences'] if o['component_id']==14)
    checks=[]
    for shift,angle in [(0,0),(-.3,0),(.3,0),(0,45),(0,90)]:
        q=[0,math.sin(math.radians(angle)/2),0,math.cos(math.radians(angle)/2)]
        for occurrence,dy in [(auger,shift),(adapter,0)]:
            c.call('assembly_set_occurrence_pose',{'occurrence_id':occurrence,
                'local_pose':{'translation':[0,dy,0],'rotation':q}})
        r=c.call('assembly_interference_check',{'clearance_threshold_mm':.05})
        assert r['exact']
        unexpected=[p for p in r['pairs'] if p['interfering'] and {p['body_a'],p['body_b']}!={15,90}]
        assert not unexpected,unexpected
        checks.append({'auger_shift_mm':shift,'common_rotation_deg':angle,'exact':True,'unintended_overlap':False})
    for shift in [-.31,.31]:
        for occurrence,dy in [(auger,shift),(adapter,0)]:
            c.call('assembly_set_occurrence_pose',{'occurrence_id':occurrence,
                'local_pose':{'translation':[0,dy,0],'rotation':[0,0,0,1]}})
        r=c.call('assembly_interference_check',{'clearance_threshold_mm':.05})
        assert r['exact'] and any(p['interfering'] and 15 in {p['body_a'],p['body_b']}
            and bool({26,46}&{p['body_a'],p['body_b']}) for p in r['pairs']),r
        checks.append({'auger_shift_mm':shift,'chassis_blocks_overtravel':True,'exact':True})
    c.call('cad_load_project_model',{'model_json':json.dumps(m)})
    return checks


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with CadClient() as c:
        c.call('cad_load_project_model',{'model_json':json.dumps(setup())})
        rear_pads(c)
        Builder(c).revolve('Direct adapter integral press-fit boss',
            [(146.0,HEAD_ACCESS/2),(HEAD_SEAT_Y,HEAD_ACCESS/2),
             (HEAD_SEAT_Y,UNDERHEAD_RELIEF_DIAMETER/2),
             (HEAD_SEAT_Y+UNDERHEAD_RELIEF_DEPTH,SCREW_CLEARANCE/2),
             (PILOT_REAR_Y,SCREW_CLEARANCE/2),(PILOT_REAR_Y,8),(146.0,8)],'join',[216])
        Builder(c).revolve('Plain round press-fit pilot and shaft-tip seat',pilot_profile(),'cut',[216])
        m=model_value(c)
        m,cleanup=clean_checked(c,m,221)
        for o in m['assembly']['component_structure']['occurrences']:
            if o['component_id']==14:o['name']='Round pilot press-fit square adapter - fit prototype'
        c.call('cad_load_project_model',{'model_json':json.dumps(m)})
        checks=check_assembly(c,m)
        preflight=c.call('solid_export_preflight')
        assert preflight['ok'] and not preflight['timeline_errors'],preflight
        m=save_project(c,ROOT/'garden-auger-direct-drive.nbcad')
        (OUT/'model.json').write_text(json.dumps(m))
        (OUT/'scene.json').write_text(json.dumps(c.call('solid_scene')))
        for ids,name in [([26,46,15,90,216,221],'assembly-raw.3mf'),([216],'adapter-raw.3mf')]:
            r=c.call('solid_export_3mf',{'body_ids':ids,'scope':'definition',
                'linear_deflection':.08,'angular_deflection':.2,'slicer_target':'bambu_studio'})
            (OUT/name).write_bytes(base64.b64decode(r['bytes_base64']))
        report={'status':'round pilot press-fit prototype; physical shaft geometry and torque capacity unqualified',
            'servo':'INJORA INJS035-360, published 5.9 mm / 25T output',
            'removed_hardware':['Separate metal servo horn','4 x M4 horn mounting screws'],
            'remaining_adapter_hardware':'one factory-compatible M3 center screw',
            'interface':'Undersized round PETG pilot; metal splines form engagement; M3 center screw retains axially',
            'adapter_dimensions_mm':{
                'square_peg':14,'peg_corner_radius':1,'peg_length':11.6,
                'flange_diameter':28,'flange_thickness':5,'spline_boss_diameter':16,
                'press_fit_pilot_diameter':PILOT_DIAMETER,'press_fit_pilot_depth':PILOT_DEPTH,
                'straight_pilot_length':PILOT_DEPTH-PILOT_LEAD_IN,'entry_chamfer':PILOT_LEAD_IN,
                'screw_clearance':SCREW_CLEARANCE,'head_access_diameter':HEAD_ACCESS,
                'underhead_relief_diameter':UNDERHEAD_RELIEF_DIAMETER,
                'underhead_relief_depth':UNDERHEAD_RELIEF_DEPTH,
                'seat_to_shaft_tip_annular_web':SHAFT_TIP_SEAT_Y-HEAD_SEAT_Y},
            'shaft_reference_only':{'assumed_tip_y':148.7,'assumed_shoulder_y':150.7,
                'nominal_tip_to_case_body_face_from_supplier_image':4.0,
                'image_derivation':'41.5 mm overall minus 37.5 mm case height; nominal inference, not exposed-spline length',
                'dimensions_image_url':'https://www.injora.com/cdn/shop/files/1_4_2c902b0b-5374-49fa-8a27-c83eb5cfaa5a.jpg?v=1787641003&width=720',
                'nominal_axial_overlap':PILOT_DEPTH,'nominal_straight_engagement':PILOT_DEPTH-PILOT_LEAD_IN,
                'nominal_tip_to_bore_bottom_gap':0,
                'positive_axial_stop':'Rotating shaft tip seats on bore floor annulus surrounding center-screw passage',
                'nominal_boss_to_stationary_nose_gap':150.7-PILOT_REAR_Y,
                'nose_clearance_min_if_exposed_spline_at_least_2_mm_and_print_depth_within_0_1':.2,
                'actual_shaft_tip_contact_verified':False,
                'warning':'Exposed shaft length/shoulder geometry are not specified by INJORA; this is not a verified shaft stack.'},
            'center_screw_inspection':screw_stack(),
            'square_fit_stack':{'required_flange_face_y':[140.95,141.25],
                'required_flange_face_from_front_chassis_thrust_stop':[27.25,27.55],
                'required_drive_axis_offset_max':.5,
                'engagement_min':9.35,'engagement_max':10.85,
                'tip_bottom_gap_min':1.05,'hub_flange_gap_min':.75,
                'note':'Conditional on printed +/-0.10 mm critical limits and measured installed flange location.'},
            'cleanup':cleanup,'preflight':preflight,'assembly_checks':checks,
            'torque':{'published_stall_Nm':35*9.80665*.01,
                'tangential_force_at_5_9_mm_diameter_N':35*9.80665*.01/.00295,
                'printed_adapter_load_rating':'not established; requires bench qualification'},
            'manufacturing_controls':{
                'datum_A':'rotating shaft-tip annular seating plane Y=148.7',
                'datum_B':'round pilot derived axis',
                'square':'14 / R1 BASIC; total surface profile 0.10 to A|B, free clocking',
                'seat':'flatness 0.10; seating-location extrema included in axial inspection',
                'press_fit':'5.70 trial bore; choose from physically tested round-pilot coupons, no certified fit allowance yet'},
            'research_sources':[
                {'url':'https://www.reddit.com/r/3Dprinting/comments/pm04eb',
                 'evidence':'Firsthand maker report: undersized round hole pressed onto metal servo splines; no published torque qualification.'},
                {'url':'https://www.reddit.com/r/robotics/comments/sh8ooa',
                 'evidence':'Maker discussion suggests round press-fit for FDM PETG; low-torque context, not a 35 kg.cm qualification.'},
                {'url':'https://ecer.pria.at/archive/ecer-2026/papers/Replacing_Botball_Kit_Parts_with_3D_Prints.pdf',
                 'evidence':'Primary study reports failure to reproduce functional fine spline engagement in a PLA printed horn; different servo/material.'},
                {'url':'https://www.injora.com/products/injora-injs035-360-35kg-waterproof-digital-servo-360-steering-winch-wheel-for-rc',
                 'evidence':'Manufacturer publishes 5.9 mm /25T, 35 kg.cm at 6V, and M3 spool mounting screw, but no shaft thread depth or screw length.'},
                {'url':'https://in.misumi-ec.com/vona2/detail/110310861029/?HissuCode=E-BOX-GSCB3-10',
                 'evidence':'Manufacturer M3 screw envelope: 5.5 mm head diameter, 3 mm head height, 2.5 mm hex.'}],
            'internal_documentation_checked':['README.md','scripts/audit_dimensions.py',
                'scripts/design_parameters.py','scripts/release_drawings.py','direct-drive-verification.json'],
            'physical_acceptance':['Start with largest round-pilot coupon; select a snug seat without splitting or damaging the servo bearings.',
                'Inspect metal teeth formed into the PETG bore. Do not use the center screw as a press to force an over-tight pilot.',
                'Measure actual exposed spline length and stationary nose clearance; maximize overlap while preserving at least 0.20 mm nose clearance.',
                'Confirm shaft tip bears on the annular seat and the adapter never clamps on the stationary servo nose.',
                'Verify center screw clamps the adapter and does not bottom, then inspect installed flange position and square clearances.',
                'Qualify loaded torque, stall behavior and creep on the completed PETG adapter; CAD clearance is not proof of strength.']}
        (ROOT/'direct-drive-verification.json').write_text(json.dumps(report,indent=2))
        print('Round press-fit prototype saved: positive shaft-tip seat; no printed teeth or M4 pattern',flush=True)


if __name__=='__main__':main()
