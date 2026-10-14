"""Render actual native revision meshes, with explicitly labeled section crops."""
import json
from pathlib import Path
import tempfile
import numpy as np
import trimesh
from PIL import Image, ImageDraw
from render_common import triangles, framed, shifted, banner, font

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'renders/clamshell-detail'
COLORS={26:(229,174,60),46:(229,174,60),15:(213,126,55),90:(213,126,55),
        216:(190,195,202),221:(55,170,161),1:(70,80,90)}


def crop(body, lo, hi):
    m=body['mesh']
    mesh=trimesh.Trimesh(np.array(m['positions']).reshape(-1,3),
                        np.array(m['indices']).reshape(-1,3),process=True)
    box=trimesh.creation.box(extents=np.array(hi)-lo)
    box.apply_translation((np.array(hi)+lo)/2)
    result=trimesh.boolean.intersection([mesh,box],engine='manifold')
    return (COLORS[body['id']],result.triangles.tolist())


def picture(name, geometry, title, subtitle, size=(1400,900),direction=(1.2,-1.7,1.2)):
    path=OUT/f'{name}.png'
    framed(geometry,size,path,margin=65,direction=direction)
    banner(path,title,subtitle)
    return path


def main(scene_path=ROOT/'.build/clamshell-detail/scene.json', out=OUT,
         revision_name='Clamshell detail revision',
         side_relief_description='Side relief widens at 45 degrees toward retained bed floors; bearing cavities remain fixed'):
    global OUT
    OUT=out
    OUT.mkdir(parents=True,exist_ok=True)
    bodies={b['id']:b for b in json.loads(scene_path.read_text())['bodies']}
    meshes={bid:(COLORS[bid],triangles(bodies[bid],
        (lambda p:(p[0],148.7-p[2],p[1])) if bid==1 else None)) for bid in COLORS}
    picture('assembled',list(meshes.values()),revision_name+' | assembled',
            'Actual native CAD meshes | fitted internal dimensions retained | physical revision trial pending')
    offsets={26:(0,0,45),46:(0,0,-30),15:(0,-30,0),90:(0,-30,0),
             216:(0,25,10),221:(0,0,16),1:(0,25,0)}
    picture('exploded',[shifted(meshes[k],offsets[k]) for k in meshes],
            'Exploded assembly | five printed parts + purchased servo',
            'Yellow PETG halves / orange PETG auger / gray PETG adapter / teal PLA sleeve',direction=(1.4,-.9,1.1))
    sheet=Image.new('RGB',(1600,1410),(17,21,27));d=ImageDraw.Draw(sheet)
    d.text((30,20),'Individual pieces | actual revision geometry',font=font(34,True),fill='white')
    cards=[('Upper housing - PETG',[shifted(meshes[26],(0,0,0))],True),
           ('Lower housing - PETG',[meshes[46]],False),
           ('One-piece auger - PETG',[meshes[15],meshes[90]],False),
           ('Square adapter - PETG',[meshes[216]],False),
           ('Loose wear sleeve - PLA',[meshes[221]],False),
           ('Servo - purchased reference envelope',[meshes[1]],False)]
    with tempfile.TemporaryDirectory() as temp:
        for i,(title,geometry,flip) in enumerate(cards):
            if flip:geometry=[(color,[tuple((-p[0],p[1],-p[2]) for p in tri) for tri in tris]) for color,tris in geometry]
            x=20+(i%2)*800;y=90+(i//2)*420
            p=Path(temp)/f'{i}.png'
            framed(geometry,(760,350),p,margin=40)
            sheet.paste(Image.open(p),(x,y+42))
            d.text((x+10,y),title,font=font(23,True),fill='white')
    d.text((30,1360),'Four M3 x 18 housing screws + four RX-M3x5.7 inserts; factory servo center screw remains separate.',font=font(22),fill=(180,194,207))
    sheet.save(OUT/'individual-pieces.png')
    for name,ids,lo,hi,title,subtitle in [
        ('locators',[26,46],[46,182,-21],[96,205,21],'Two locators per handle | alternating ownership',
         '7.00 mm pins / 7.30 mm straight sockets / 2.8 mm projection / chamfered entries; printed fit pending'),
        ('screw-stack',[26,46],[23,113,-21],[27,124,21],'Common housing screw stack | front section',
         'M3 x 18: seat Z14, tip Z-4 | four identical lower insert pilots | hardware shown as nominal envelopes'),
        ('auger-entry',[26,46,15,90],[0,101,-21],[22,122,21],'Auger entrance | cutaway of external deflector',
         'Fixed projecting lip, 18.8 mm inner radius | original entrance and thrust stops retained | noncontact'),
        ('sculpted-shoulders',[26,46],[-40,125,-21],[35,145,21],'Bearing shoulders | exterior material removed',
         side_relief_description)]:
        geometry=[crop(bodies[i],lo,hi) for i in ids]
        if name=='locators':geometry=[shifted(g,(0,0,12 if i==26 else -5)) for i,g in zip(ids,geometry)]
        if name=='screw-stack':
            for radius,height,z,color in [(1.5,18,5,(160,170,184)),(2.75,3,15.5,(160,170,184)),(2.3,5.7,-2.85,(182,132,57))]:
                hw=trimesh.creation.cylinder(radius,height,sections=40)
                hw.apply_translation([27,118.5,z])
                geometry.append((color,hw.triangles.tolist()))
        picture(name,geometry,title,subtitle,direction=(1.4,-1.7,1.3))
    print('Native mesh renderings saved:',OUT,flush=True)


if __name__=='__main__':main()
