"""Export reviewed geometry, build two plates and verify actual native G-code.

The delivered 3MF remains editable and contains no machine program. Native
evidence lives in the existing garden-auger-owned 150 MiB additional-output lane.
"""
import base64
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

from cad_client import CadClient
from build_servo_rear_fit_test import read_model
from review_snug_servo_nest import native_cylinder
from print_packer import pack
from render_clamshell_detail import main as render
import prepare_bambu_latest as b
from combine_current_plates import write_zip

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'.build/clamshell-detail/current-assembly/geometry-refinement'
CAD=ROOT/'experiments/garden-auger-relieved-housing.limo'
TARGET=ROOT/'garden-auger-two-plate-assembly.3mf'
REPORT=ROOT/'two-plate-assembly-verification.json'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    global BUILD,CAD,TARGET,REPORT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--d-grips',action='store_true')
    parser.add_argument('--solid-frame',action='store_true')
    parser.add_argument('--outer-envelope',action='store_true')
    parser.add_argument('--chamfer-envelope',action='store_true')
    parser.add_argument('--ingress-flange',action='store_true')
    parser.add_argument('--simple-print',action='store_true')
    args=parser.parse_args()
    if args.simple_print:args.ingress_flange=True
    if args.ingress_flange:args.chamfer_envelope=True
    if args.chamfer_envelope:args.outer_envelope=True
    if args.solid_frame or args.outer_envelope:args.d_grips=True
    review_path=ROOT/('d-grip-geometry-review.json' if args.d_grips else 'geometry-refinement-review.json')
    validation_path=ROOT/'d-grip-validation.json'
    if args.d_grips:
        BUILD=ROOT/'.build/clamshell-detail/current-assembly/d-grip'
        CAD=ROOT/'experiments/garden-auger-child-d-grips.limo'
        TARGET=ROOT/'garden-auger-child-d-grip-assembly.3mf'
        REPORT=ROOT/'d-grip-print-verification.json'
        if args.solid_frame:
            BUILD=BUILD/'solid-frame'
            CAD=ROOT/'experiments/garden-auger-solid-frame.limo'
            TARGET=ROOT/'garden-auger-solid-frame-assembly.3mf'
            REPORT=ROOT/'solid-frame-print-verification.json'
            review_path=ROOT/'solid-frame-geometry-review.json'
            validation_path=ROOT/'solid-frame-validation.json'
        if args.outer_envelope:
            BUILD=ROOT/'.build/clamshell-detail/current-assembly/outer-envelope'
            CAD=ROOT/'experiments/garden-auger-rounded-envelope.limo'
            TARGET=ROOT/'garden-auger-rounded-envelope-assembly.3mf'
            REPORT=ROOT/'outer-envelope-print-verification.json'
            review_path=ROOT/'outer-envelope-geometry-review.json'
            validation_path=ROOT/'outer-envelope-validation.json'
        if args.chamfer_envelope:
            BUILD=ROOT/'.build/clamshell-detail/current-assembly/chamfer-envelope'
            CAD=ROOT/'experiments/garden-auger-chamfer-envelope.limo'
            TARGET=ROOT/'garden-auger-chamfer-envelope-assembly.3mf'
            REPORT=ROOT/'chamfer-envelope-print-verification.json'
            review_path=ROOT/'chamfer-envelope-geometry-review.json'
            validation_path=ROOT/'chamfer-envelope-validation.json'
        if args.ingress_flange:
            BUILD=ROOT/'.build/clamshell-detail/current-assembly/ingress-flange'
            CAD=ROOT/'experiments/garden-auger-ingress-flange.limo'
            TARGET=ROOT/'garden-auger-ingress-flange-assembly.3mf'
            REPORT=ROOT/'ingress-flange-print-verification.json'
            review_path=ROOT/'ingress-flange-geometry-review.json'
            validation_path=ROOT/'ingress-flange-validation.json'
        if args.simple_print:
            BUILD=ROOT/'.build/clamshell-detail/current-assembly/simple-print'
            CAD=ROOT/'experiments/garden-auger-simple-print.limo'
            TARGET=ROOT/'garden-auger-simple-print-assembly.3mf'
            REPORT=ROOT/'simple-print-verification.json'
            review_path=ROOT/'simple-print-geometry-review.json'
            validation_path=ROOT/'simple-print-validation.json'
        validation=json.loads(validation_path.read_text())
        assert validation['cad_sha256']==sha(CAD)
        if args.outer_envelope:
            wall_path=ROOT/('simple-print-wall-review.json' if args.simple_print else 'ingress-flange-wall-review.json' if args.ingress_flange else 'chamfer-envelope-wall-review.json' if args.chamfer_envelope else 'outer-envelope-wall-review.json')
            assert json.loads(wall_path.read_text())['cad_sha256']==sha(CAD)
    parts_dir='print-parts/d-grip-assembly' if args.d_grips else 'print-parts/relieved-assembly'
    renders_dir='renders/d-grip' if args.d_grips else 'renders/relieved-assembly'
    if args.solid_frame:
        parts_dir='print-parts/solid-frame-assembly'
        renders_dir='renders/solid-frame'
    if args.outer_envelope:
        parts_dir='print-parts/rounded-envelope-assembly'
        renders_dir='renders/rounded-envelope'
    if args.chamfer_envelope:
        parts_dir='print-parts/chamfer-envelope-assembly'
        renders_dir='renders/chamfer-envelope'
    if args.ingress_flange:
        parts_dir='print-parts/ingress-flange-assembly'
        renders_dir='renders/ingress-flange'
    if args.simple_print:
        parts_dir='print-parts/simple-print-assembly'
        renders_dir='renders/simple-print'
    review=json.loads(review_path.read_text())
    assert sha(CAD)==review['cad_sha256']
    preserved={str(p.relative_to(ROOT)):sha(p) for p in [CAD,ROOT/'garden-auger-current-assembly.3mf',
        ROOT/'garden-auger-upper-servo-sparse-test.3mf',ROOT/'garden-auger-bambu-latest.3mf']}
    if args.d_grips:
        for p in [ROOT/'garden-auger-two-plate-assembly.3mf',ROOT/'experiments/garden-auger-relieved-housing.limo']:
            preserved[str(p.relative_to(ROOT))]=sha(p)
    if args.solid_frame:
        for p in [ROOT/'garden-auger-child-d-grip-assembly.3mf',ROOT/'experiments/garden-auger-child-d-grips.limo',ROOT/'print-parts/grip-comfort-sample.stl']:
            preserved[str(p.relative_to(ROOT))]=sha(p)
    if args.outer_envelope:
        for p in [ROOT/'garden-auger-solid-frame-assembly.3mf',ROOT/'experiments/garden-auger-solid-frame.limo',ROOT/'print-parts/grip-comfort-sample.stl']:
            preserved[str(p.relative_to(ROOT))]=sha(p)
    if args.chamfer_envelope:
        for p in [ROOT/'garden-auger-rounded-envelope-assembly.3mf',ROOT/'experiments/garden-auger-rounded-envelope.limo']:
            preserved[str(p.relative_to(ROOT))]=sha(p)
    if args.ingress_flange:
        for p in [ROOT/'garden-auger-chamfer-envelope-assembly.3mf',ROOT/'experiments/garden-auger-chamfer-envelope.limo']:
            preserved[str(p.relative_to(ROOT))]=sha(p)
    if args.simple_print:
        for p in [ROOT/'garden-auger-ingress-flange-assembly.3mf',ROOT/'experiments/garden-auger-ingress-flange.limo']:
            preserved[str(p.relative_to(ROOT))]=sha(p)
    native=BUILD/'native.3mf';canonical=BUILD/'five-refined-parts.3mf'
    with CadClient() as c:
        c.call('cad_load_project_model',{'model_json':json.dumps(read_model(CAD))})
        bodies={b['id']:b for b in c.call('solid_scene')['bodies']}
        stacks=[]
        for x,y in [(-27,118.5),(27,118.5),(-36,196.8),(16,196.8)]:
            head=native_cylinder(bodies[26],3.1,axis=2,location={'x':x,'y':y})
            insert=native_cylinder(bodies[46],2,axis=2,location={'x':x,'y':y})
            levels=lambda w:sorted({e['circle']['center']['z'] for e in w['native_boundary_circles']})
            assert all(abs(a-d)<1e-7 for a,d in zip(levels(head),[14.,20.6])) and len(levels(head))==2
            assert all(abs(a-d)<1e-7 for a,d in zip(levels(insert),[-6.7,0.])) and len(levels(insert))==2
            stacks.append({'xy_mm':[x,y],'head_pocket_mm':6.2,'head_seat_z_mm':14,'insert_pilot_z_mm':[-6.7,0.]})
        pre=c.call('solid_export_preflight',{'body_ids':[26,46,15,90,216,221]})
        assert pre['ok'] and not pre['timeline_errors']
        raw=c.call('solid_export_3mf',{'body_ids':[26,46,15,90,216,221],
            'scope':'definition','linear_deflection':.08,'angular_deflection':.2,'slicer_target':'standard'})
        native.write_bytes(base64.b64decode(raw['bytes_base64']))
    print_notes=('Simple 40mm auger disc, one chamfer, direct housing nose without redundant ring; use matching halves and auger.' if args.simple_print else
                 'Integral rotating auger dirt flange ahead of fixed lip; unchanged chamfered housing and fitted interfaces.' if args.ingress_flange else
                 'Uniform 5mm equal-leg 45 degree housing bevels; blended plan outline, flat bases and fixed fits retained.' if args.chamfer_envelope else
                 'Rounded broad outer faces and slimmer blended side walls; fixed fits and lower D grips retained.' if args.outer_envelope else
                 'Continuous frame with exterior rounds and lower D grips; no cosmetic seam recesses; unchanged drive and constraint-fit bushing.' if args.solid_frame else
                 'Lower-owned complete D grips and central upper cover; relocated case locators; unchanged drive and constraint-fit bushing.'
                 if args.d_grips else 'Relieved current housing; accommodating outer locator sockets; unchanged drive and constraint-fit bushing.')
    parts=pack(native,canonical,print_notes=print_notes,
        individual_dir=parts_dir,auger_anchor=(204,8) if args.ingress_flange else (214,8))
    entries=b.read_zip(canonical);xml=ET.fromstring(entries['3D/3dmodel.model'])
    next(o for o in xml.findall('{*}resources/{*}object') if o.get('name')=='PLA - Full wear sleeve').set('name','PLA - Constraint-fit bushing')
    entries['3D/3dmodel.model']=ET.tostring(xml,encoding='utf-8',xml_declaration=True)
    write_zip(canonical,entries)
    old=ROOT/parts_dir/'pla-full-wear-sleeve.stl'
    old.replace(old.with_name('pla-constraint-fit-bushing.stl'))
    parts[-1]['name']='PLA - Constraint-fit bushing'
    run_name='refined-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    slice_root=BUILD/'slice-runs' if args.d_grips else BUILD.parent/'sequential'
    command=[sys.executable,str(ROOT/'scripts/combine_current_plates.py'),
        '--name',run_name,'--housing-sequence','by object' if args.d_grips else 'by layer',
        '--thermal-order','--adaptive-bed','--canonical',str(canonical),'--refresh-geometry',
        '--build-root',str(slice_root),'--cad-source',str(CAD.relative_to(ROOT))]
    if args.d_grips:command.append('--d-grip-layout')
    subprocess.run(command,check=True)
    lane=slice_root/run_name
    probe=json.loads((lane/'probe.json').read_text());native_result=probe['native_result']
    assert probe['exit_code']==0 and native_result['return_code']==0
    assert len(native_result['sliced_plates'])==2
    assert [len(p['objects']) for p in native_result['sliced_plates']]==[2,3]
    assert not any(p['warning_message'] for p in native_result['sliced_plates'])
    entries=b.read_zip(lane/'input.3mf');sliced=b.read_zip(lane/'sliced.3mf')
    first=sliced['Metadata/plate_1.gcode'].decode();second=sliced['Metadata/plate_2.gcode'].decode()
    assert ('; print_sequence = by object' if args.d_grips else '; print_sequence = by layer') in first
    assert '; print_sequence = by object' in second
    if args.d_grips:
        first_ids=re.findall(r'; start printing object, unique label id: (\d+)',first)
        first_runs=[x for i,x in enumerate(first_ids) if i==0 or x!=first_ids[i-1]]
        assert len(first_runs)==2 and set(first_runs)=={'102','104'},first_runs
        assert not re.search(r'^\s*M190 S55\s*$',first,re.M)
    ids=re.findall(r'; start printing object, unique label id: (\d+)',second)
    runs=[x for i,x in enumerate(ids) if i==0 or x!=ids[i-1]]
    assert runs==['106','108','110'],runs # Auger, adapter, then PLA.
    assert 'M190 S55' in second
    start_bushing=second.index('; start printing object, unique label id: 110')
    wait=second.rindex('M190 S55');assert wait<start_bushing
    assert not re.search(r'^\s*M(?:140|190) S(?:[6-9][0-9]|[1-9][0-9]{2,})',second[start_bushing:],re.M)
    roles=lambda text:set(re.findall(r'^; FEATURE: ([^\r\n]+)',text,re.M))
    assert {'Support','Support interface'}<=roles(first)
    assert ('Prime tower' in roles(first)) != args.d_grips
    assert {'Support','Support interface'}<=roles(second) and 'Prime tower' not in roles(second)
    assert not any('Support' in s or 'Sparse' in s for s in roles(second[start_bushing:]))
    # Emitted order is checked, and the rear auger is separated in Y from both
    # short front parts by more than the saved 33 mm rod distance.
    plate2=probe['placements'][1]['parts'];auger=next(p for p in plate2 if p['name']=='PETG - One-piece auger')
    y_gap=min(auger['bounds_mm'][0][1]-p['bounds_mm'][1][1] for p in plate2 if p is not auger)
    assert y_gap>float(probe['clearances']['extruder_clearance_dist_to_rod'])
    entries.update({n:d for n,d in sliced.items() if re.match(r'Metadata/(?:plate(?:_no_light)?_|top_|pick_)\d+(?:_small)?\.png$',n)})
    entries['Metadata/slice_info.config']=sliced['Metadata/slice_info.config']
    assert not any(n.endswith('.gcode') for n in entries)
    write_zip(TARGET,entries)
    original_entries=b.read_zip(lane/'input.3mf')
    metadata_only=lambda n:n=='Metadata/slice_info.config' or bool(re.match(r'Metadata/(?:plate(?:_no_light)?_|top_|pick_)\d+',n))
    assert {n:d for n,d in entries.items() if not metadata_only(n)}=={n:d for n,d in original_entries.items() if not metadata_only(n)}
    _,config,project_parts=b.project_parts(entries)
    b.CANONICAL=canonical
    b.EXPECTED_FILAMENT['PLA - Constraint-fit bushing']=b.EXPECTED_FILAMENT.pop('PLA - Full wear sleeve')
    mesh_checks=b.geometry_checks(project_parts)
    # Source object settings are retained after geometry refresh.
    _,old_config,_=b.project_parts(b.read_zip(ROOT/'garden-auger-current-assembly.3mf'))
    by_name={b.metadata(o)['name']:b.metadata(o) for o in old_config.findall('object')}
    assert all(b.metadata(o)==by_name[b.metadata(o)['name']] for o in config.findall('object'))
    assert all(sha(ROOT/p)==h for p,h in preserved.items())
    result={'cad':str(CAD.relative_to(ROOT)),'cad_sha256':sha(CAD),
        'geometry_review':review_path.name,'geometry_review_sha256':sha(review_path),
        'project':TARGET.name,'project_sha256':sha(TARGET),'native_engine_sha256':review['engine_sha256'],
        'native_slicer_version':'02.08.02.61','mesh_checks':mesh_checks,'parts':parts,
        'native_equal_screw_stacks':stacks,
        'native_sliced_archive_sha256':sha(lane/'sliced.3mf'),
        'sliced_input_sha256':sha(lane/'input.3mf'),
        'final_geometry_and_process_entries_byte_identical_to_sliced_input':True,
        'gcode_sha256':{f'plate_{i}':hashlib.sha256(sliced[f'Metadata/plate_{i}.gcode']).hexdigest() for i in [1,2]},
        'placements':probe['placements'],'native_slice':native_result,
        'actual_second_plate_order':['PETG - One-piece auger','PETG - Square adapter','PLA - Constraint-fit bushing'],
        'auger_to_front_parts_y_gap_mm':y_gap,'saved_clearances':probe['clearances'],
        'temperature_policy':{'bed_temperature_formula':'by_first_filament','PETG_C':70,'PLA_C':55,'wait_for_PLA_before_final_object':True},
        'prime_tower_actual':{'plate_1':not args.d_grips,'plate_2':False},'object_process_settings_preserved':True,
        'embedded_gcode':False,'printer_command_sent':False,'preserved_files':preserved,
        'time_seconds':sum(p['total_predication'] for p in native_result['sliced_plates']),
        'filament_g':sum(f['total_used_g'] for p in native_result['sliced_plates'] for f in p['filaments']),
        'stls':{str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/parts_dir).glob('*.stl'))},
        'rejected_housing_object_layouts':[] if args.d_grips else ['two-object-probe','stagger-object-probe'],
        'scope':'Digital geometry and native slicing qualification; physical fit, stiffness, wear, loaded torque and dirty trial remain pending.'}
    if args.d_grips:
        result['additional_validation']=validation_path.name
        result['additional_validation_sha256']=sha(validation_path)
        result['actual_first_plate_order']=first_runs
        boxes=[p['bounds_mm'] for p in probe['placements'][0]['parts']]
        x_gap=max(boxes[0][0][0]-boxes[1][1][0],boxes[1][0][0]-boxes[0][1][0])
        assert x_gap>=float(probe['clearances']['extruder_clearance_max_radius'])
        result['housing_x_separation_mm']=x_gap
    if args.outer_envelope:
        result['wall_review']=wall_path.name
        result['wall_review_sha256']=sha(wall_path)
    REPORT.write_text(json.dumps(result,indent=2)+'\n')
    for i in [1,2]:
        out=ROOT/renders_dir/f'plate-{i}.png'
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_bytes(sliced[f'Metadata/plate_{i}.png'])
    if args.d_grips:
        from render_d_grips import main as render_child
        render_child(BUILD,ROOT/renders_dir,solid_frame=args.solid_frame,outer_envelope=args.outer_envelope,chamfer_envelope=args.chamfer_envelope,ingress_flange=args.ingress_flange,simple_print=args.simple_print)
        if args.ingress_flange:
            from render_ingress_flange import main as render_entry
            render_entry(BUILD,CAD,ROOT/renders_dir,simple_print=args.simple_print)
        result['optional_comfort_sample']=json.loads((BUILD/'comfort-sample.json').read_text())
        REPORT.write_text(json.dumps(result,indent=2)+'\n')
    else:
        render(BUILD/'scene.json',ROOT/renders_dir,'Relieved housing | accommodating outer locator sockets',
            'Deeper exterior relief retains fixed servo, drive, cable and continuous outer bed floors',
            locator_description='7.00 mm pins | inner sockets 7.30 mm round | outer sockets 8.10 X by 7.30 Y | printed fit pending')
    print('PASS: final two-plate editable package, actual order, temperature wait and mesh/process preservation',flush=True)


if __name__=='__main__':main()
