"""Render the actual native direct-drive geometry, including its round pilot."""
import json
from pathlib import Path
import tempfile
from PIL import Image, ImageDraw
from render_common import framed, triangles, shifted, banner, font, parts_sheet

ROOT=Path(__file__).resolve().parents[1]

def main():
    scene=json.loads((ROOT/'.build/direct-drive/scene.json').read_text())
    model=json.loads((ROOT/'.build/direct-drive/model.json').read_text())
    servo_y=next(o['local_pose']['translation'][1] for o in model['assembly']['component_structure']['occurrences'] if o['component_id']==3)
    colors={1:(75,98,119),26:(229,174,60),46:(229,174,60),15:(213,126,55),
            90:(213,126,55),216:(190,195,202),221:(55,170,161)}
    meshes={b['id']:(colors[b['id']],triangles(b,(lambda p:(p[0],-p[2]+servo_y,p[1]))
        if b['id']==1 else None)) for b in scene['bodies']}
    out=ROOT/'renders'
    parts_sheet(meshes,{'sleeve':221,'direct_drive':True},out/'direct-drive-all-parts.png')
    offsets={26:(0,25,75),46:(0,25,-40),15:(0,0,0),90:(0,0,0),221:(0,32,0),216:(0,55,0),1:(0,88,0)}
    framed([shifted(meshes[k],p) for k,p in offsets.items()],(1600,900),out/'direct-drive-exploded.png',margin=50)
    banner(out/'direct-drive-exploded.png','Direct-to-servo drive | Five printed parts',
           'One PETG round press-fit / square adapter + center screw. Loose PLA sleeve; clamshell capture.')
    image=Image.new('RGB',(1600,1190),(17,21,27));d=ImageDraw.Draw(image)
    d.text((32,20),'One printed adapter replaces the metal horn + four M4 screws',font=font(31,True),fill=(239,245,250))
    d.text((32,70),'Actual CAD geometry | PETG gray #BEC3CA | Fit prototype: shaft fit and load capacity unqualified',font=font(22),fill=(179,194,208))
    with tempfile.TemporaryDirectory() as folder:
        for name,x,direction,title,subtitle in [
            ('square',25,(1.2,-1.7,1.2),'Auger side','14 mm square / R1; axial screw access'),
            ('pilot',810,(.5,2.5,.8),'Servo side','Plain round pilot; metal shaft forms engagement')]:
            path=Path(folder)/(name+'.png')
            framed([meshes[216]],(735,590),path,margin=40,direction=direction)
            image.paste(Image.open(path),(x+15,190))
            d.text((x+25,125),title,font=font(28,True),fill=(235,242,249))
            d.text((x+25,162),subtitle,font=font(21),fill=(182,198,211))
    d.line((32,810,1568,810),fill=(56,69,82),width=2)
    d.text((40,836),'Simplified load path',font=font(28,True),fill=(234,242,249))
    d.text((40,880),'Metal servo shaft  >  round PETG press fit  >  14 mm square  >  one-piece auger',font=font(26),fill=(220,232,244))
    d.text((40,924),'Center screw clamps the annular seat onto the rotating shaft tip. No printed spline teeth.',font=font(24),fill=(182,198,211))
    d.text((40,978),'Pilot: 5.70 mm trial bore x 1.70 deep   |   M3 x 6 trial center screw',font=font(24),fill=(220,232,244))
    d.text((40,1020),'Round fit coupons A / B / C / D: 5.60 / 5.70 / 5.80 / 5.90 mm. Start with D.',font=font(24),fill=(182,198,211))
    d.text((40,1060),'Shaft tip is the axial stop; nominal stationary-nose gap 0.30 mm. Measure actual shaft / thread depth.',font=font(23),fill=(182,198,211))
    d.text((40,1124),'At 35 kg.cm stall torque, strength cannot be inferred from a snug fit. Qualify the printed adapter.',font=font(23,True),fill=(238,188,96))
    image.save(out/'direct-drive-adapter.png')
    print('Direct-drive adapter, all parts and exploded CAD geometry rendered',flush=True)

if __name__=='__main__':main()
