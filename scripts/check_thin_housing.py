"""Record native CAD evidence for the printable housing and routing revision."""
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import zipfile

from cad_client import CadClient
from nested_housing import verify_nesting

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = 'c969789fe356c292e5040a44f467c2685a2209aa'


def read_model(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return json.loads(z.read('model.json'))


def write_model(path, model):
    with zipfile.ZipFile(path) as z:
        entries = {n:z.read(n) for n in z.namelist()}
    entries['model.json'] = json.dumps(model, separators=(',',':')).encode()
    if 'manifest.json' in entries:
        manifest = json.loads(entries['manifest.json'])
        manifest['model_schema_version'] = model['schema_version']
        entries['manifest.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name,data in entries.items():z.writestr(name,data)


def anchor_at(projection, body_id, point):
    matches = [a for a in projection['anchors'] if a['body_id'] == body_id
        and max(abs(x-y) for x,y in zip(a['model_point'],point)) < 1e-6]
    if not matches:
        raise ValueError(f'No native topology anchor at body {body_id}, {point}')
    a = matches[0]
    return {k:a[k] for k in ('body_id','edge_id','edge_key','endpoint','occurrence_id')} | {
        'fallback_point':a['model_point'], 'circle_center':False,
        'topology_signature':projection['topology_signatures'][str(body_id)]}


def refresh_inspection(client, model):
    inspection = ROOT/'garden-auger-fit-inspection.limo'
    old = read_model(inspection.read_bytes())
    revised = copy.deepcopy(model)
    revised['schema_version'] = old['schema_version']
    revised['drawings'] = old['drawings']
    revised['views'] = old['views']
    revised['document']['name'] = 'Garden auger - side cable route fit inspection'
    for sheet in revised['drawings']['sheets']:
        sheet['title_block']['revision'] = 'PRINT-5'
    # Rebind every dimension to a returned CURRENT topology anchor. Matching
    # coordinates select the intended unchanged mating corner, not a value.
    revised['drawings']['sheets'] = revised['drawings']['sheets'][:2]
    revised['drawings']['active_sheet_id'] = revised['drawings']['sheets'][0]['id']
    client.call('cad_load_project_model', {'model_json':json.dumps(revised)})
    for sheet in revised['drawings']['sheets']:
        for view in sheet['views']:
            projection = client.call('drawing_projection', {
                'body_ids':view['body_ids'], 'scope':view['scope'],
                'direction':view['direction'], 'up':view['up'], 'include_hidden':True})
            for annotation in sheet['annotations']:
                if annotation.get('view_id') != view['id']:continue
                for key in ('first','second'):
                    prior = annotation[key]
                    annotation[key] = anchor_at(projection, prior['body_id'],prior['fallback_point'])
    client.call('cad_load_project_model', {'model_json':json.dumps(revised)})
    sheets = client.call('drawing_create_sheet', {
        'name':'Printable housing - exterior wall measurements', 'format':'a3',
        'orientation':'landscape', 'title_block':{'title':'Exterior stock from current CAD topology',
        'drawing_number':'AU-WALL-20261006','revision':'PRINT-5'},
        'tolerance_note':{'preset':'none','custom':'Nominal dimensions only. No automated wall, GD&T or load qualification.'}})
    sheet_id = max(s['id'] for s in client.call('drawing_document')['sheets'])
    dimensions = []
    definitions = [
        ('Floor - YZ',[1,0,0],[100,140],
         [(-30.9,191.7,-10.4),None],'Floor ',14),
        ('Side walls - XY',[0,0,1],[290,140],
         [(18.5,165.7,0),None],'Right ear wall ',16),
    ]
    for name,direction,position,points,prefix,offset in definitions:
        client.call('drawing_add_view', {'sheet_id':sheet_id,'view':{
            'name':name,'kind':'custom','direction':direction,'up':[0,1,0],
            'position':position,'scale':1.2,'body_ids':[46], 'scope':'assembly',
            'show_hidden_lines':True,'show_tangent_edges':False}})
        view_id = max(v['id'] for s in client.call('drawing_document')['sheets']
                      if s['id']==sheet_id for v in s['views'])
        projection = client.call('drawing_projection', {'body_ids':[46],'scope':'assembly',
            'direction':direction,'up':[0,1,0],'include_hidden':True})
        # Select a CURRENT native edge endpoint on the outer plane. The
        # measured separation comes from CAD, never an entered dimension.
        if name.startswith('Floor'):
            points[1] = next(a['model_point'] for a in projection['anchors']
                if a['body_id']==46 and abs(a['model_point'][2]+20.6)<1e-6
                and 170<a['model_point'][1]<198)
        else:
            points[1] = next(a['model_point'] for a in projection['anchors']
                if a['body_id']==46 and abs(a['model_point'][0]-22.3)<1e-6
                and abs(a['model_point'][2])<1e-6)
        client.call('drawing_add_linear_dimension', {'sheet_id':sheet_id,'view_id':view_id,
            'first':anchor_at(projection,46,points[0]),'second':anchor_at(projection,46,points[1]),
            'mode':'horizontal','offset':offset,'prefix':prefix,'precision':2})
        if name.startswith('Side'):
            client.call('drawing_add_linear_dimension', {'sheet_id':sheet_id,'view_id':view_id,
                'first':anchor_at(projection,46,[-38.5,165.7,0]),
                'second':anchor_at(projection,46,next(a['model_point'] for a in projection['anchors']
                    if a['body_id']==46 and abs(a['model_point'][0]+42.3)<1e-6
                    and abs(a['model_point'][2])<1e-6)),
                'mode':'horizontal','offset':-16,'prefix':'Left ear wall ','precision':2})
    # Serializer is authoritative for IDs/counters allocated by drawing tools.
    saved = client.call('cad_project_model')
    saved = json.loads(saved) if isinstance(saved,str) else saved
    write_model(inspection,saved)
    exports=[]
    for sheet_id,filename in [(1,'cad-fit-dimensions.svg'),(2,'cad-fit-clearances.svg'),
                              (sheet_id,'cad-thin-wall-dimensions.svg')]:
        result=client.call('drawing_export',{'sheet_id':sheet_id,'format':'svg'})
        content=result['content']
        (ROOT/'renders'/filename).write_text(content,encoding='utf-8',newline='\n')
        exports.append({'sheet_id':sheet_id,'file':'renders/'+filename,
            'dimension_text':re.findall(r'<text[^>]*>(.*?)</text>',content)})
    return saved,exports


def main():
    path=ROOT/'garden-auger-direct-drive.nbcad'
    current=path.read_bytes();model=read_model(current)
    previous=subprocess.check_output(['git','show',f'{REFERENCE}:{path.name}'],cwd=ROOT)
    before=read_model(previous)
    with CadClient() as client:
        nesting=verify_nesting(client,before,model)
        nominal=client.call('assembly_interference_check',{'clearance_threshold_mm':2})
        assert nominal['exact'] and not any(p['interfering'] for p in nominal['pairs'])
        preflight=client.call('solid_export_preflight')
        assert preflight['ok'] and not preflight['timeline_errors']
        scene=client.call('solid_scene')
        saved,exports=refresh_inspection(client,model)
        new_scene=client.call('solid_scene')
        assert all(b['mesh']==next(n['mesh'] for n in new_scene['bodies'] if n['id']==b['id'])
                   for b in scene['bodies'])
    report={'source_project':path.name,'source_project_sha256':hashlib.sha256(current).hexdigest(),
        'reference_commit':REFERENCE,'reference_project_sha256':hashlib.sha256(previous).hexdigest(),
        'native_geometry_verification':nesting,'native_nominal_interference':nominal,
        'native_export_preflight':preflight,'native_drawing_exports':exports,
        'inspection_same_native_mesh_arrays':True,
        'method':'Installed Limo CAD exact solid engine, native interference/preflight and associative drawing tools.',
        'limitations':['No automatic minimum-wall or GD&T stack checker is exposed by the CAD tool.',
            'Wall drawing dimensions measure selected nominal planes; they are not a global thickness certification.',
            'Printed fit, cable boot, internal servo thread depth and loaded strength remain physical checks.']}
    (ROOT/'thin-housing-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Native housing checks and three refreshed associative sheets complete',flush=True)


if __name__=='__main__':main()
