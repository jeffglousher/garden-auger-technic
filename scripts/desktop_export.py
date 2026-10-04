"""Verify and save files with the installed schema-7 desktop's own reader."""
import json
import sys
import zipfile
from pathlib import Path
from cad_client import CadClient
from cad_build import save_project

ROOT=Path(__file__).resolve().parents[1]

def read(path):
    with zipfile.ZipFile(path) as z:return json.loads(z.read('model.json'))

def main():
    proof=[]
    direct='--direct' in sys.argv
    reader_only='--reader-only' in sys.argv
    reader=Path(sys.argv[sys.argv.index('--reader')+1]) if '--reader' in sys.argv else None
    names=(['garden-auger-direct-drive.nbcad','garden-auger-press-fit.nbcad'] if direct else
           ['garden-auger-drive.nbcad','garden-auger-no-ring.nbcad','garden-auger-fit-check.nbcad'])
    launch_path=ROOT/('.build/direct-drive/cad-launch.json' if direct else '.build/cad-launch.json')
    with CadClient(reader) as desktop:
        if not reader_only:
            launch=json.loads(launch_path.read_text())
            desktop.call('cad_attach',{'document_id':launch['document_id']} if launch.get('document_id') else {'session_id':launch['session_id']})
            current=next(w for w in desktop.call('cad_list_sessions')['windows']
                         if w['active_document_id']==launch.get('document_id') or w['active_session_id']==launch['session_id'])
            doc=current['active_document_id'];launch['document_id']=doc
            launch_path.write_text(json.dumps(launch))
        for name in names:
            m=read(ROOT/name)
            for s in m['sketches']:
                assert not s.get('support_boundary')
                assert not s['snapshot'].get('reference_edges')
                # Schema 7 treats generated circle-center points as authored
                # points. They already exist in the entity list; bake ownership
                # explicitly rather than relying on a reader to discard it.
                entities=dict(s['snapshot']['entities'])
                assert all(entities[i]['type']=='point' for i in s['snapshot'].get('generated_points',[]))
                s['snapshot']['generated_points']=[]
            with CadClient() as reference:
                reference.call('cad_load_project_model',{'model_json':json.dumps(m)})
                expected=reference.call('solid_scene')
            m['schema_version']=7
            if not reader_only:desktop.call('cad_attach',{'document_id':doc})
            desktop.call('cad_load_project_model',{'model_json':json.dumps(m)})
            actual=desktop.call('solid_scene');assert not actual['errors'],actual['errors']
            assert len(actual['bodies'])==len(expected['bodies'])
            for body in expected['bodies']:
                live=next(b for b in actual['bodies'] if b['id']==body['id'])
                assert body['mesh']['positions']==live['mesh']['positions'],(name,body['id'],'vertices')
                assert body['mesh']['indices']==live['mesh']['indices'],(name,body['id'],'triangles')
            # The newer MCP serializer always raises the schema header. Write
            # the explicitly baked legacy payload only after the old desktop
            # has recomputed exactly the same complete geometry.
            for sketch in m['sketches']:
                for key in ['support_boundary','profile_identities','entity_id_high_water']:
                    sketch.pop(key,None)
            with zipfile.ZipFile(ROOT/name) as z:entries={key:z.read(key) for key in z.namelist()}
            entries['model.json']=json.dumps(m,separators=(',',':')).encode()
            if 'manifest.json' in entries:
                manifest=json.loads(entries['manifest.json']);manifest['model_schema_version']=7
                entries['manifest.json']=json.dumps(manifest).encode()
            with zipfile.ZipFile(ROOT/name,'w',zipfile.ZIP_DEFLATED) as z:
                for key,data in entries.items():z.writestr(key,data)
            saved=read(ROOT/name);assert saved['schema_version']==7
            assert saved['body_appearances']==m['body_appearances']
            assert len(saved['drawings']['sheets'])==len(m['drawings']['sheets'])
            proof.append({'file':name,'desktop_schema':7,'all_mesh_vertices_and_triangles_identical':True,
                          'materials_preserved':True,'drawing_sheets':len(saved['drawings']['sheets']),
                          'reader_mode':'isolated desktop executable headless' if reader_only else 'attached desktop'})
            print(name,'desktop round-trip exact',flush=True)
        if not reader_only:
            desktop.call('cad_attach',{'document_id':doc})
            desktop.call('cad_load_project_model',{'model_json':json.dumps(read(ROOT/names[0]))})
            desktop.call('cad_interface',{'action':'view','view':'isometric','fit':True,'duration_ms':0})
    output=ROOT/('.build/direct-drive/desktop-compatibility.json' if direct else '.build/desktop-compatibility.json')
    output.write_text(json.dumps(proof,indent=2))

if __name__=='__main__':main()
