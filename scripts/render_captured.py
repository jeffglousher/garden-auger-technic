"""Render current parts, chassis capture and the enlarged drive interface."""

import json
from pathlib import Path
import shutil

from render_common import banner,framed,parts_sheet,shifted,triangles
from raster_render import render

ROOT=Path(__file__).resolve().parents[1]


def main():
    scene=json.loads((ROOT/'.build/scene.json').read_text())
    model=json.loads((ROOT/'.build/model.json').read_text())
    parts=json.loads((ROOT/'.build/parts.json').read_text());ring=parts['sleeve']
    servo_y=next(o['local_pose']['translation'][1] for o in model['assembly']['component_structure']['occurrences'] if o['component_id']==3)
    colors={1:(75,98,119),26:(229,174,60),46:(229,174,60),90:(213,126,55),15:(213,126,55),216:(190,195,202),ring:(55,170,161),parts['horn']:(174,184,196)}
    meshes={b['id']:(colors[b['id']],triangles(b,(lambda p:(p[0],-p[2]+servo_y,p[1])) if b['id']==1 else None)) for b in scene['bodies']}
    out=ROOT/'renders';out.mkdir(exist_ok=True)
    parts_sheet(meshes,parts,out/'auger-all-parts.png',captured=True)
    opened=[m for k,m in meshes.items() if k!=26]
    framed(opened,(1500,900),out/'captured-assembly.png',margin=65)
    banner(out/'captured-assembly.png','Chassis-captured auger | Upper cover removed',
           'Plain PLA sleeve. Both faces of the integral collar provide axial retention in the housing.')
    exploded={26:(0,35,85),46:(0,35,-50),15:(0,0,0),90:(0,0,0),ring:(0,40,0),216:(0,65,0),parts['horn']:(0,90,0),1:(0,115,0)}
    framed([shifted(meshes[k],offset) for k,offset in exploded.items()],
        (1600,1000),out/'auger-exploded.png',margin=55)
    banner(out/'auger-exploded.png','Exploded assembly | Chassis-only retention',
           'Auger -> loose PLA sleeve -> square adapter -> metal 25T horn -> servo. Chassis-only retention.')
    render(opened,eye=(80,87,98),target=(0,125,0),up=(0,0,1),size=(1300,820),
           path=out/'captured-seat.png',scale=1150)
    banner(out/'captured-seat.png','Plain sleeve in the clamshell',
           'The chassis retains the auger directly; the sleeve supplies only a replaceable running surface.')
    tail=(meshes[15][0],[t for t in meshes[15][1] if max(p[1] for p in t)>110])
    # Turn the adapter around for inspection so its peg faces the same
    # camera as the auger's socket. This is a display pose only.
    adapter=(meshes[216][0],[tuple((-p[0],272.8-p[1],p[2]) for p in tri) for tri in meshes[216][1]])
    framed([tail,shifted(meshes[ring],(-40,0,0)),shifted(adapter,(40,0,0))],
           (1500,740),out/'captured-drive-detail.png',margin=60,direction=(1.1,1.7,1.2))
    banner(out/'captured-drive-detail.png','Enlarged drive connection | Adapter turned to show its peg',
           'Plain PLA sleeve | 28 mm PETG hub with 14.4 mm square socket | 14 mm square adapter peg.')


if __name__=='__main__':main()
