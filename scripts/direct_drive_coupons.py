"""Four round-pilot PETG fit coupons; metal servo splines form engagement."""
import base64
import json
from pathlib import Path
from cad_client import CadClient
from cad_build import Builder, save_project
from direct_drive_parameters import PILOT_TRIAL_DIAMETERS, PILOT_DEPTH, BOSS_DIAMETER, pilot_profile

ROOT=Path(__file__).resolve().parents[1]

def main():
    bodies=[]
    with CadClient() as c:
        c.call('cad_new_project',{})
        for i,diameter in enumerate(PILOT_TRIAL_DIAMETERS):
            name=f'Round press fit {chr(65+i)} - bore {diameter:.2f} mm'
            height=2.6+PILOT_DEPTH
            body=Builder(c).revolve(name,[(0,1.7),(height,1.7),
                (height,BOSS_DIAMETER/2),(0,BOSS_DIAMETER/2)],'new_body',[])['created_body_id']
            Builder(c).revolve(name+' plain pilot',pilot_profile(diameter,height-PILOT_DEPTH),'cut',[body])
            c.call('solid_move_copy',{'body_ids':[body],'translation':{'x':i*30,'y':0,'z':0},
                'pivot':{'x':0,'y':0,'z':0},'copy':False})
            c.call('set_body_appearance',{'body_id':body,'material_name':'PETG','filament_type':'PETG',
                'color_name':'Adapter gray','color':{'r':190,'g':195,'b':202,'a':255}})
            bodies.append({'body':body,'label':chr(65+i),'round_bore_diameter_mm':diameter,
                'pilot_depth_mm':PILOT_DEPTH})
        m=c.call('cad_project_model');m=json.loads(m) if isinstance(m,str) else m
        m['document']['name']='Round pilot PETG press-fit coupons A B C D - unqualified'
        m['visibility']['hidden_sketch_names']=[s['name'] for s in m['sketches']]
        m['visibility']['hidden_datum_plane_ids']=[p['datum_id'] for p in m['datum_planes']]
        c.call('cad_load_project_model',{'model_json':json.dumps(m)})
        assert c.call('solid_export_preflight')['ok']
        save_project(c,ROOT/'garden-auger-press-fit.nbcad')
        r=c.call('solid_export_3mf',{'body_ids':[b['body'] for b in bodies],'scope':'definition',
            'linear_deflection':.08,'angular_deflection':.2,'slicer_target':'bambu_studio'})
        (ROOT/'.build/direct-drive/coupons-raw.3mf').write_bytes(base64.b64decode(r['bytes_base64']))
        (ROOT/'.build/direct-drive/coupons.json').write_text(json.dumps(bodies,indent=2))
        print('Round press-fit coupons A/B/C/D saved; start with D, the largest bore',flush=True)

if __name__=='__main__':main()
