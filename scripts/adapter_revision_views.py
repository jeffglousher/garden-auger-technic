"""Show isolated native CAD inspection poses without editing the saved design."""
import argparse
import json
from pathlib import Path
import zipfile
from cad_client import CadClient
from cad_build import Builder

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--document',required=True)
    parser.add_argument('--view',choices=['front','rear','section'],required=True)
    args=parser.parse_args()
    with zipfile.ZipFile(ROOT/'garden-auger-direct-drive.nbcad') as z:
        model=json.loads(z.read('model.json'))
    model['visibility']['hidden_body_ids']=[1,15,90,26,46,221]
    with CadClient() as c:
        c.call('cad_load_project_model',{'model_json':json.dumps(model)})
        if args.view=='section':
            Builder(c).box('Display only axial half section',(0,120,40,155,-40,40),'cut',[216])
            model=c.call('cad_project_model')
            if isinstance(model,str):model=json.loads(model)
        model['visibility']['hidden_sketch_names']=[s['name'] for s in model['sketches']]
        model['visibility']['hidden_datum_plane_ids']=[p['datum_id'] for p in model['datum_planes']]
        adapter=next(o for o in model['assembly']['component_structure']['occurrences']
                     if o['component_id']==14)
        adapter['local_pose']['translation']=[0,0,45]
        if args.view=='rear':adapter['local_pose']['rotation']=[1,0,0,0]
        model['document']['name']=f'Adapter inspection - {args.view} - socket 3.70 / boss 24'
        c.call('cad_attach',{'document_id':args.document})
        c.call('cad_load_project_model',{'model_json':json.dumps(model)})
        result=c.call('cad_interface',{'action':'view','view':'right' if args.view=='section' else 'isometric',
                                     'fit':True,'duration_ms':0})
        assert result.get('status')=='applied',result
    print(args.view,'shown in native CAD; design file unchanged')


if __name__=='__main__':main()
