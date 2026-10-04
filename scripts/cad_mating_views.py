"""Temporary native CAD inspection models made from the actual exported solids.

Main design and print files are never edited. Display crops/poses are isolated
in .build/mating-views. A smooth shaft cylinder is a labeled nominal envelope,
not a claimed model of the supplier spline or its internal thread geometry.
"""
import argparse
import base64
import json
from pathlib import Path
import zipfile
from cad_client import CadClient
from cad_build import Builder

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.build/mating-views'
EXE=Path('C:/Users/jeffg/Downloads/noBS-CAD-0.2.2-windows-x64/noBS-CAD-0.2.2-windows-x64/noBS-CAD.exe')
PALETTE={15:(213,126,55),216:(190,195,202),221:(55,170,161),26:(229,174,60),46:(229,174,60)}


def val(c):
    m=c.call('cad_project_model')
    return json.loads(m) if isinstance(m,str) else m


def import_part(c,source,label):
    old={b['id'] for b in c.call('solid_scene')['bodies']}
    c.call('solid_import_step',{'file_name':label+'.STEP',
        'data_base64':base64.b64encode((OUT/f'{source}.STEP').read_bytes()).decode()})
    body=next(b['id'] for b in c.call('solid_scene')['bodies'] if b['id'] not in old)
    color=PALETTE[source]
    c.call('set_body_appearance',{'body_id':body,'color':dict(zip(('r','g','b','a'),[*color,255])),
        'material_name':'PLA' if source==221 else 'PETG','filament_type':'PLA' if source==221 else 'PETG'})
    c.call('assembly_create_component',{'name':label,'body_ids':[body],'absorb_promoted_bodies':True})
    return body


def move(c,body,x=0,y=0,z=0,flip_x=False,flip_y=False):
    c.call('solid_move_copy',{'body_ids':[body],
        'translation':{'x':x,'y':y,'z':z},'pivot':{'x':0,'y':130,'z':0},
        'rotation':[1,0,0,0] if flip_x else [0,1,0,0] if flip_y else [0,0,0,1],
        'copy':False})


def crop(c,targets,bounds,label):
    Builder(c).box(label,bounds,'intersect',targets)


def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(ROOT/'garden-auger-direct-drive.nbcad') as z:canonical=json.loads(z.read('model.json'))
    # STEP exports retain the native analytic faces, radii and bores.
    with CadClient() as source:
        source.call('cad_load_project_model',{'model_json':json.dumps(canonical)})
        for body in PALETTE:
            r=source.call('solid_export_step',{'body_ids':[body]})
            (OUT/f'{body}.STEP').write_bytes(base64.b64decode(r['bytes_base64']))
    views={
        'square':('Square drive - socket and peg','isometric'),
        'pilot':('Servo press-fit pilot and rotating-shaft tip seat','isometric'),
        'screw':('Section - M3 head seat, neck relief and shaft-tip seat','right'),
        'sleeve':('Running surfaces - auger journal and loose PLA sleeve','isometric'),
        'shells':('Clamshell split faces, bearing cavity and thrust stops','isometric'),
        'capture':('Section - collar capture, sleeve float and journal surfaces','right'),
    }
    with CadClient(EXE,['--headless']) as c:
        for name,(title,orientation) in views.items():
            c.call('cad_new_project',{})
            if name=='square':
                auger=import_part(c,15,'Actual auger socket - 14.4 R1.2')
                crop(c,[auger],(-35,110,35,140,-35,35),'Display crop of auger drive end')
                adapter=import_part(c,216,'Actual adapter square - 14 R1')
                move(c,auger,x=-24,flip_x=True);move(c,adapter,x=24)
            elif name=='pilot':
                adapter=import_part(c,216,'Actual round pilot and annular shaft-tip seat')
                move(c,adapter,x=-15,flip_x=True)
                shaft=Builder(c).revolve('Nominal shaft envelope - diameter 5.9, length assumed 2.0',
                    [(148.7,1.5),(150.7,1.5),(150.7,2.95),(148.7,2.95)],'new_body',[])['created_body_id']
                c.call('set_body_appearance',{'body_id':shaft,'material_name':'REFERENCE ONLY - tooth and thread form omitted',
                    'color':{'r':75,'g':145,'b':196,'a':255},'filament_type':'OTHER'})
                move(c,shaft,x=18,y=-18,flip_x=True)
            elif name=='screw':
                adapter=import_part(c,216,'Actual adapter - axial section')
                Builder(c).box('Temporary half-section of adapter',(0,120,40,155,-40,40),'cut',[adapter])
                screw=Builder(c).revolve('Nominal M3x6 clearance envelope - threads omitted',
                    [(143.1,0),(143.1,2.75),(146.1,2.75),(146.1,1.8),
                     (146.4,1.5),(152.1,1.5),(152.1,0)],'new_body',[])['created_body_id']
                c.call('set_body_appearance',{'body_id':screw,'material_name':'REFERENCE M3x6 envelope',
                    'color':{'r':75,'g':145,'b':196,'a':255},'filament_type':'OTHER'})
                Builder(c).box('Temporary half-section of screw',(0,120,40,155,-40,40),'cut',[screw])
            elif name=='sleeve':
                auger=import_part(c,15,'Actual journal - diameter 28')
                crop(c,[auger],(-35,110,35,140,-35,35),'Display crop of auger journal')
                sleeve=import_part(c,221,'Actual loose PLA sleeve - bore 28.6, OD34')
                move(c,auger,x=-25,flip_x=True);move(c,sleeve,x=25)
            elif name=='shells':
                upper=import_part(c,26,'Actual upper clamshell mating region')
                lower=import_part(c,46,'Actual lower clamshell mating region')
                crop(c,[upper,lower],(-24,108,24,141,-25,25),'Display crop of clamshell bearing region')
                move(c,lower,x=-28);move(c,upper,x=28,flip_y=True)
            elif name=='capture':
                upper=import_part(c,26,'Actual upper clamshell')
                lower=import_part(c,46,'Actual lower clamshell')
                auger=import_part(c,15,'Actual integral auger collar and journal')
                sleeve=import_part(c,221,'Actual full loose PLA sleeve')
                crop(c,[upper,lower,auger,sleeve],(-25,110,25,140,-25,25),
                    'Display crop of assembled bearing region')
                Builder(c).box('Temporary axial half-section',(0,100,50,150,-40,40),
                    'cut',[upper,lower,auger,sleeve])
            m=val(c);m['document']['name']=title
            m['visibility']['hidden_sketch_names']=[s['name'] for s in m['sketches']]
            m['visibility']['hidden_datum_plane_ids']=[p['datum_id'] for p in m['datum_planes']]
            assert not c.call('solid_scene')['errors']
            (OUT/f'{name}.json').write_text(json.dumps(m))
            print(name,'native review geometry ready',flush=True)
    (OUT/'views.json').write_text(json.dumps(views))


def show(name):
    launch=json.loads((OUT/'desktop.json').read_text())
    views=json.loads((OUT/'views.json').read_text())
    with CadClient(EXE,['--headless']) as c:
        c.call('cad_attach',{'document_id':launch['document_id']})
        c.call('cad_load_project_model',{'model_json':(OUT/f'{name}.json').read_text()})
        # Lift the temporary review solids above the CAD floor grid. This keeps
        # the grid from crossing the small sockets in the native viewport.
        bodies=[b['id'] for b in c.call('solid_scene')['bodies']]
        c.call('solid_move_copy',{'body_ids':bodies,
            'translation':{'x':0,'y':0,'z':45},
            'pivot':{'x':0,'y':0,'z':0},'rotation':[0,0,0,1],'copy':False})
        c.call('construction_set_visibility',{'visible':False})
        r=c.call('cad_interface',{'action':'view','view':views[name][1],'fit':True,'duration_ms':0})
        assert r.get('status')=='applied',r
        print(name,'shown in CAD; main design file unchanged',flush=True)


def prepare_extra():
    views=json.loads((OUT/'views.json').read_text())
    with CadClient(EXE,['--headless']) as c:
        for name,title,orientation in [
            ('drive','Section - assembled square drive and end clearances','right'),
            ('chassis','Full clamshell inner faces, servo cradle and insert mouths','isometric')]:
            c.call('cad_new_project',{})
            if name=='drive':
                auger=import_part(c,15,'Actual auger socket in assembly')
                crop(c,[auger],(-20,123,20,153,-20,20),'Display crop of auger drive end')
                adapter=import_part(c,216,'Actual square adapter in assembly')
                Builder(c).box('Temporary axial half-section',(0,120,40,155,-40,40),
                    'cut',[auger,adapter])
            else:
                upper=import_part(c,26,'Actual full upper clamshell inner face')
                lower=import_part(c,46,'Actual full lower clamshell inner face')
                move(c,lower,x=-50);move(c,upper,x=50,flip_y=True)
            m=val(c);m['document']['name']=title
            m['visibility']['hidden_sketch_names']=[s['name'] for s in m['sketches']]
            m['visibility']['hidden_datum_plane_ids']=[p['datum_id'] for p in m['datum_planes']]
            assert not c.call('solid_scene')['errors']
            (OUT/f'{name}.json').write_text(json.dumps(m))
            views[name]=[title,orientation]
            print(name,'native review geometry ready',flush=True)
    (OUT/'views.json').write_text(json.dumps(views))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','prepare-extra','square','pilot','screw','sleeve','shells','capture','drive','chassis'])
    args=p.parse_args()
    prepare() if args.action=='prepare' else prepare_extra() if args.action=='prepare-extra' else show(args.action)
