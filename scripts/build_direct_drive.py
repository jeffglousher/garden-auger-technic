"""Build the current round pilot press-fit prototype.

The metal servo splines form their engagement into an undersized PETG bore.
No tiny spline teeth are printed. Nominal servo dimensions use the confirmed
diagram; printed fit, internal screw depth and load capacity require inspection.
"""
import base64
import json
import math
from pathlib import Path

from cad_client import CadClient
from cad_build import Builder, save_project
from construction_setup import configure, rear_pads
from model_cleanup import clean_checked
from housing_simplification import simplify_housing, verify_housing
from nested_housing import nest_housing, verify_nesting
from slim_housing import slim_housing
from direct_drive_parameters import *
from design_parameters import square_fit_stack

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.build/direct-drive'


def model_value(c):
    m=c.call('cad_project_model')
    return json.loads(m) if isinstance(m,str) else m


def setup():
    return configure()


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
            [(BOSS_ROOT_Y,HEAD_ACCESS/2),(HEAD_SEAT_Y,HEAD_ACCESS/2),
             (HEAD_SEAT_Y,UNDERHEAD_RELIEF_DIAMETER/2),
             (HEAD_SEAT_Y+UNDERHEAD_RELIEF_DEPTH,SCREW_CLEARANCE/2),
             (PILOT_REAR_Y,SCREW_CLEARANCE/2),(PILOT_REAR_Y,BOSS_DIAMETER/2),
             (BOSS_TRANSITION_END_Y,BOSS_DIAMETER/2),(BOSS_ROOT_Y,14)],'join',[216])
        Builder(c).revolve('Plain round press-fit pilot and shaft-tip seat',pilot_profile(),'cut',[216])
        m=model_value(c)
        m,cleanup=clean_checked(c,m,221)
        simpler,housing_cleanup=simplify_housing(m)
        housing_cleanup['geometry_verification']=verify_housing(c,m,simpler)
        m,nesting=nest_housing(simpler)
        nesting['geometry_verification']=verify_nesting(c,simpler,m)
        slimmer, thinning = slim_housing(m)
        thinning['native_geometry_verification'] = verify_nesting(c,m,slimmer)
        m = slimmer
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
        report={'status':'round pilot press-fit prototype; confirmed nominal servo diagram; printed fit and torque capacity unqualified',
            'servo':'INJORA INJS035-360, published 5.9 mm / 25T output',
            'removed_hardware':['Separate metal servo horn','4 x M4 horn mounting screws'],
            'remaining_adapter_hardware':'one factory-compatible M3 center screw',
            'interface':'Undersized round PETG pilot; metal splines form engagement; M3 center screw retains axially',
            'adapter_dimensions_mm':{
                'square_peg':14,'peg_corner_radius':1,'peg_length':11.6,
                'flange_diameter':28,'flange_thickness':5,'spline_boss_diameter':BOSS_DIAMETER,
                'minimum_bore_radial_wall':(BOSS_DIAMETER-PILOT_DIAMETER-2*PILOT_LEAD_IN)/2,
                'straight_bore_radial_wall':(BOSS_DIAMETER-PILOT_DIAMETER)/2,
                'boss_root_transition':'2 mm axial / 2 mm radial broad taper into the 28 mm flange',
                'press_fit_pilot_diameter':PILOT_DIAMETER,'press_fit_pilot_depth':PILOT_DEPTH,
                'straight_pilot_length':PILOT_DEPTH-PILOT_LEAD_IN,'entry_chamfer':PILOT_LEAD_IN,
                'screw_clearance':SCREW_CLEARANCE,'head_access_diameter':HEAD_ACCESS,
                'underhead_relief_diameter':UNDERHEAD_RELIEF_DIAMETER,
                'underhead_relief_depth':UNDERHEAD_RELIEF_DEPTH,
                'seat_to_shaft_tip_annular_web':SHAFT_TIP_SEAT_Y-HEAD_SEAT_Y},
            'horn_depth_reference':{'family':'Hitec H25T (nominal 6 mm / 25 tooth)',
                'manufacturer_horn_depth_mm':3.70,'source_url':H25T_DEPTH_SOURCE,
                'source_printed_page':75,'scope':'Manufacturer family reference; INJORA publishes diameter/tooth count but not axial spline exposure.'},
            'shaft_reference_only':{'nominal_tip_y':SHAFT_TIP_SEAT_Y,
                'dimensioned_tip_to_case_stack_user_confirmed':True,
                'dimensional_authority':'User-confirmed accurate INJORA dimensioned diagram',
                'local_dimensions_image':'source/references/user-servo-fit-diagram.png',
                'nominal_case_face_y':CASE_FACE_REFERENCE_Y,
                'nominal_tip_to_case_body_face_from_supplier_image':4.0,
                'image_derivation':'41.5 mm tip-to-rear minus 37.5 mm case-face-to-rear = 4.0 mm nominal tip-to-case-face distance',
                'dimensions_image_url':'https://www.injora.com/cdn/shop/files/1_4_2c902b0b-5374-49fa-8a27-c83eb5cfaa5a.jpg?v=1787641003&width=720',
                'nominal_axial_overlap':PILOT_DEPTH,'nominal_straight_engagement':PILOT_DEPTH-PILOT_LEAD_IN,
                'nominal_tip_to_bore_bottom_gap':0,
                'positive_axial_stop':'Rotating shaft tip seats on bore floor annulus surrounding center-screw passage',
                'nominal_boss_to_case_face_gap':CASE_FACE_REFERENCE_Y-PILOT_REAR_Y,
                'required_exposure_to_nearest_stationary_surface_min':REQUIRED_EXPOSED_SHAFT_MIN,
                'stationary_clearance_min_if_exposure_and_print_depth_pass':MIN_STATIONARY_CLEARANCE,
                'unsupported_2_mm_stationary_nose_removed_from_reference':True,
                'purchased_shaft_and_nose_collision_verified':False,
                'actual_shaft_tip_contact_verified':False,
                'scope':'The confirmed diagram controls nominal case/ear and tip-to-case dimensions. The rotating shaft and internal thread are not modeled; inspect printed seating and usable internal screw depth.'},
            'center_screw_inspection':screw_stack(),
            'square_fit_stack':square_fit_stack(),
            'cleanup':cleanup,'housing_simplification':housing_cleanup,
            'nested_housing':nesting,
            'thin_housing':thinning,
            'preflight':preflight,'assembly_checks':checks,
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
            'internal_documentation_checked':['README.md','scripts/geometry_measurements.py',
                'scripts/design_parameters.py','source/references/provenance.json','direct-drive-verification.json'],
            'physical_acceptance':['Start with largest round-pilot coupon; select a snug seat without splitting or damaging the servo bearings.',
                'Inspect metal teeth formed into the PETG bore. Do not use the center screw as a press to force an over-tight pilot.',
                'Use the confirmed 4.00 mm nominal tip-to-case stack; inspect the printed 3.70 +/-0.10 mm socket to retain at least 0.20 mm case-face clearance.',
                'Confirm shaft tip bears on the annular seat and the adapter never clamps on the stationary servo nose.',
                'Verify center screw clamps the adapter and does not bottom, then inspect installed flange position and square clearances.',
                'Qualify loaded torque, stall behavior and creep on the completed PETG adapter; CAD clearance is not proof of strength.']}
        (ROOT/'direct-drive-verification.json').write_text(json.dumps(report,indent=2))
        print('Round press-fit prototype saved: positive shaft-tip seat; no printed teeth or M4 pattern',flush=True)


if __name__=='__main__':main()
