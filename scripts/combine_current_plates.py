"""Place unchanged current parts on two plates and qualify native sequencing.

Reuses the project-owned review lane; 150 MiB additional output budget. Preserve
models, user templates and the four-plate fallback. Never sends printer commands.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import prepare_bambu_latest as b

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / '.build/clamshell-detail/current-assembly/sequential'
SOURCE = ROOT / 'garden-auger-current-assembly.3mf'
CANONICAL = BUILD.parent / 'five-current-parts.3mf'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_zip(path, entries):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items(): z.writestr(name, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', default='two-object-probe')
    parser.add_argument('--housing-sequence', choices=['by object','by layer'], default='by object')
    parser.add_argument('--parts-sequence', choices=['by object','by layer'], default='by object')
    parser.add_argument('--no-tower', action='store_true')
    parser.add_argument('--stagger-housings', action='store_true')
    parser.add_argument('--thermal-order', action='store_true')
    parser.add_argument('--adaptive-bed', action='store_true')
    parser.add_argument('--canonical', type=Path, default=CANONICAL)
    parser.add_argument('--refresh-geometry', action='store_true')
    parser.add_argument('--build-root', type=Path, default=BUILD)
    parser.add_argument('--d-grip-layout', action='store_true')
    parser.add_argument('--cad-source')
    parser.add_argument('--slice', type=int, default=0)
    args = parser.parse_args()
    lane = args.build_root.resolve() / args.name
    lane.mkdir(parents=True, exist_ok=True)
    if (lane/'result.json').exists() or (lane/'sliced.3mf').exists():
        raise FileExistsError('Use a new --name to preserve previous native evidence and avoid overwrite prompts.')
    target = lane/'input.3mf'
    before = sha(SOURCE)
    proof = json.loads((ROOT/'current-assembly-verification.json').read_text())
    assert before == proof['project_sha256']
    entries = b.read_zip(SOURCE)
    model, config, parts = b.project_parts(entries)
    b.CANONICAL = args.canonical.resolve()
    b.EXPECTED_FILAMENT['PLA - Constraint-fit bushing'] = b.EXPECTED_FILAMENT.pop('PLA - Full wear sleeve')
    if args.refresh_geometry:
        overrides={o.get('id'):b.metadata(o) for o in config.findall('object')}
        b.refresh_geometry(entries,config,parts)
        # Geometry refresh must not reset the reviewed process overrides.
        for obj in config.findall('object'):
            for node in obj.findall('metadata'):
                key=node.get('key')
                if key in overrides[obj.get('id')]:node.set('value',overrides[obj.get('id')][key])
    if args.cad_source:
        for node in config.findall('object/part/metadata'):
            if node.get('key')=='source_file':node.set('value',args.cad_source)
    mesh_checks = b.geometry_checks(parts)
    settings = json.loads(entries['Metadata/project_settings.config'])
    settings['print_sequence'] = 'by object'
    settings['enable_wrapping_detection'] = '0'
    if args.adaptive_bed:
        assert args.thermal_order
        assert settings['curr_bed_type']=='Textured PEI Plate'
        pla_bed=int(settings['textured_plate_temp_initial_layer'][3])
        assert not settings['printing_by_object_gcode'].strip()
        settings['bed_temperature_formula']='by_first_filament'
        settings['printing_by_object_gcode']=(
            '; Combined plate: wait for the saved PLA bed temperature before the final bushing\n'
            '{if current_object_idx == 2}\n'+f'M190 S{pla_bed}\n'+'{endif}\n')
    if args.no_tower: settings['enable_prime_tower'] = '0'
    settings['wipe_tower_x'] = ['180','85']
    settings['wipe_tower_y'] = ['115','205']
    layouts = [
        ('Matching housing halves', args.housing_sequence, [
            ('PETG - Housing upper', b.UPPER, (28.,6.)),
            ('PETG - Housing lower', b.I, (28.,147.)),
        ]),
        ('Bushing, adapter, auger', args.parts_sequence, [
            ('PLA - Constraint-fit bushing', b.UPRIGHT, (25.,24.)),
            ('PETG - Square adapter', b.UPRIGHT, (25.,135.)),
            ('PETG - One-piece auger', b.I, (160.,55.)),
        ]),
    ]
    if args.stagger_housings:
        layouts[0][2][:] = [
            ('PETG - Housing upper', np.diag([1.,-1.,-1.]), (5.,5.)),
            ('PETG - Housing lower', b.I, (51.,148.4)),
        ]
    elif args.housing_sequence == 'by layer':
        layouts[0][2][:] = [
            ('PETG - Housing upper', b.UPPER, (28.,24.)),
            ('PETG - Housing lower', b.I, (28.,138.)),
        ]
        settings['wipe_tower_y'][0] = '142'
    if args.d_grip_layout:
        layouts[0][2][:] = [
            ('PETG - Housing upper', b.UPPER, (173.,75.)),
            ('PETG - Housing lower', np.array([[0.,-1.,0.],[1.,0.,0.],[0.,0.,1.]]), (8.,34.5)),
        ]
    if args.thermal_order:
        # Keep the tall auger at the back, beyond the rod envelope of either
        # short front part, so actual native ordering remains collision-safe.
        layouts[1][2][:] = [
            ('PETG - Square adapter', b.UPRIGHT, (25.,25.)),
            ('PETG - One-piece auger', np.array([[0.,-1.,0.],[1.,0.,0.],[0.,0.,1.]]), (55.,185.)),
            ('PLA - Constraint-fit bushing', b.UPRIGHT, (160.,25.)),
        ]
    for old in config.findall('plate'): config.remove(old)
    build = model.find('{*}build')
    items = {n.get('objectid'): n for n in build}
    build.clear()
    placements = []
    for i,(label,sequence,definitions) in enumerate(layouts):
        plate = ET.SubElement(config,'plate')
        for key,value in {'plater_id':i+1,'plater_name':label,'locked':'false',
                          'print_sequence':sequence,'filament_map_mode':'Auto For Flush',
                          'filament_maps':'1 1 1 1','filament_volume_maps':'0 0 0 0'}.items():
            b.add_metadata(plate,key,value)
        origin = np.array([i*307.2,0.,0.])
        records=[]
        for name,rotation,xy in definitions:
            part = parts[name]
            posed = part['vertices'] @ rotation.T
            shift = origin + np.array([*xy,0.]) - posed.min(0)
            item = items[part['object_id']]
            item.set('transform',b.transform_text(rotation,shift))
            build.append(item)
            instance=ET.SubElement(plate,'model_instance')
            for key,value in {'object_id':part['object_id'],'instance_id':0,
                              'identify_id':100+int(part['object_id'])}.items():
                b.add_metadata(instance,key,value)
            bounds=np.array([posed.min(0),posed.max(0)])+shift-origin
            assert np.all(bounds[0]>=-1e-6) and np.all(bounds[1]<=[256,256,261])
            assert abs(bounds[0,2])<1e-6
            records.append({'name':name,'bounds_mm':bounds.tolist()})
        placements.append({'plate':i+1,'sequence':sequence,'parts':records})
    if args.thermal_order:
        order = [parts[name]['object_id'] for _,_,defs in layouts for name,_,_ in defs]
        remap = {old:str(2*(i+1)) for i,old in enumerate(order)}
        resources=model.find('{*}resources')
        wrappers={o.get('id'):o for o in resources.findall('{*}object')}
        for o in wrappers.values(): resources.remove(o)
        configs={o.get('id'):o for o in config.findall('object')}
        for o in configs.values(): config.remove(o)
        for i,old in enumerate(order):
            wrappers[old].set('id',remap[old]);resources.append(wrappers[old])
            configs[old].set('id',remap[old]);config.insert(i,configs[old])
        for item in build: item.set('objectid',remap[item.get('objectid')])
        for node in config.findall('plate/model_instance/metadata'):
            if node.get('key')=='object_id': node.set('value',remap[node.get('value')])
    entries['3D/3dmodel.model']=ET.tostring(model,encoding='utf-8',xml_declaration=True)
    entries['Metadata/model_settings.config']=ET.tostring(config,encoding='utf-8',xml_declaration=True)
    entries['Metadata/project_settings.config']=json.dumps(settings,indent=2).encode()
    entries={n:d for n,d in entries.items() if not re.match(r'Metadata/(?:plate(?:_no_light)?_|top_|pick_)\d+',n)
             and not n.endswith('.gcode')}
    entries['Metadata/filament_sequence.json']=json.dumps({f'plate_{i+1}':{
        'nozzle_sequence':[],'optimal_assignment':[],'sequence':[]} for i in range(2)}).encode()
    old_slice=ET.fromstring(entries['Metadata/slice_info.config'])
    for node in list(old_slice):
        if node.tag!='header': old_slice.remove(node)
    entries['Metadata/slice_info.config']=ET.tostring(old_slice,encoding='utf-8',xml_declaration=True)
    ET.register_namespace('','http://schemas.openxmlformats.org/package/2006/relationships')
    for name,data in list(entries.items()):
        if name.endswith('.rels'):
            rels=ET.fromstring(data)
            for rel in list(rels):
                if rel.get('Target','').lstrip('/') not in entries and rel.get('TargetMode')!='External': rels.remove(rel)
            entries[name]=ET.tostring(rels,encoding='utf-8',xml_declaration=True)
    write_zip(target,entries)
    record={'source':SOURCE.name,'source_sha256':before,'candidate_sha256':sha(target),
            'placements':placements,'mesh_checks':mesh_checks,'tower_enabled':settings['enable_prime_tower'],
            'clearances':{k:v for k,v in settings.items() if k.startswith('extruder_clearance')},
            'geometry_refreshed_from_canonical':args.refresh_geometry,'printer_command_sent':False}
    (lane/'layout.json').write_text(json.dumps(record,indent=2)+'\n')
    print('Slicing',args.name,flush=True)
    with (lane/'native.log').open('w') as log:
        process=subprocess.run([r'C:/Program Files/Bambu Studio/bambu-studio.exe','--slice',str(args.slice),
            '--export-3mf','sliced.3mf','--outputdir',str(lane),str(target)],
            stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW,timeout=600)
    record['exit_code']=process.returncode
    if (lane/'result.json').exists(): record['native_result']=json.loads((lane/'result.json').read_text())
    (lane/'probe.json').write_text(json.dumps(record,indent=2)+'\n')
    native=record.get('native_result',{})
    print(json.dumps({'exit':process.returncode,'error':native.get('error_string'),
        'plates':[{'id':p['id'],'seconds':p['total_predication'],'grams':sum(f['total_used_g'] for f in p['filaments']),
                   'warning':p['warning_message']} for p in native.get('sliced_plates',[])]},indent=2),flush=True)
    assert sha(SOURCE)==before


if __name__=='__main__': main()
