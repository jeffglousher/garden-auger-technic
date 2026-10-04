"""Display an unsaved native CAD inspection pose; capture via Computer Use."""
import argparse
import copy
import json
import zipfile
from pathlib import Path
from cad_client import CadClient
from cad_build import Builder

ROOT=Path(__file__).resolve().parents[1]
def read(path):
    with zipfile.ZipFile(path) as z:return json.loads(z.read('model.json'))
def main():
    parser=argparse.ArgumentParser();parser.add_argument('view',choices=['assembled','opened','exploded','section']);mode=parser.parse_args().view
    m=read(ROOT/('garden-auger-fit-check.nbcad' if mode=='section' else 'garden-auger-drive.nbcad'))
    if mode=='opened':
        m['visibility']['hidden_body_ids']=[26]
        for o in m['assembly']['component_structure']['occurrences']:
            if o['component_id']==6:o['visible']=False
    if mode=='exploded':
        defs=m['assembly']['component_structure']['definitions']
        horn=next(d['id'] for d in defs if '1906-0025-0032' in d['name'])
        ring=next(d['id'] for d in defs if 221 in d['body_ids'])
        upper=next(d['id'] for d in defs if 26 in d['body_ids'])
        lower=next(d['id'] for d in defs if 46 in d['body_ids'])
        shifts={upper:[0,0,65],lower:[0,0,-40],14:[0,50,0],horn:[0,80,0],ring:[-45,0,0]}
        for o in m['assembly']['component_structure']['occurrences']:
            if o['component_id'] in shifts:o['local_pose']['translation']=shifts[o['component_id']]
            if o['component_id']==3:o['local_pose']['translation'][1]+=110
    with CadClient() as c:
        c.call('cad_attach',{'document_id':json.loads((ROOT/'.build/cad-launch.json').read_text())['document_id']})
        c.call('cad_load_project_model',{'model_json':json.dumps(m)})
        if mode=='section':
            horn=json.loads((ROOT/'.build/parts.json').read_text())['horn']
            Builder(c).box('Temporary CAD inspection section',(0,100,100,160,-50,50),'cut',[26,46,15,216,221,horn])
        c.call('construction_set_visibility',{'visible':False})
        result=c.call('cad_interface',{'action':'view','view':'right' if mode=='section' else 'isometric','fit':True,'duration_ms':0})
        assert result['status']=='applied',result
    print(mode,'native CAD view ready; no inspection pose saved',flush=True)
if __name__=='__main__':main()
