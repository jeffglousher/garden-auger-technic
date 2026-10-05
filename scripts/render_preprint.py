"""Render the fit failure and corrected saved housing, with drawing datums.

Native section cuts are made only in an isolated display document. No source
project is saved or modified by this renderer.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageDraw

from cad_build import Builder
from cad_client import CadClient
from native_render_source import native_render_source
from render_common import framed, triangles, font

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = '6816a19f59809b0960d3e3b408ffa8cbd29a3a23'
WHITE = '#EFF5FA'
MUTED = '#B8C8D8'
TEAL = '#83D2C3'
ORANGE = '#F0A979'


def slot(model):
    sketch = next(s for s in model['sketches'] if s['name'] == 'Sketch62')
    rear = sketch['basis']['origin'][1]
    depth = next(e['extent']['distance'] for e in model['extrudes'] if e['feature_id'] == 183)
    return rear-depth, rear


def section(client, data):
    model, _ = native_render_source(client, data)
    Builder(client).box('Display section only - omit front housing',
                        (-100,-100,100,148,-100,100),'cut',[26,46])
    scene = client.call('solid_scene')
    assert not scene['errors'], scene['errors']
    return model, next(b for b in scene['bodies'] if b['id'] == 46)


def main():
    source = ROOT/'garden-auger-direct-drive.nbcad'
    current = source.read_bytes()
    previous = subprocess.check_output(['git','show',f'{REFERENCE}:{source.name}'],cwd=ROOT)
    with CadClient() as client:
        model, scene = native_render_source(client,current)
        servo = next(b for b in scene['bodies'] if b['id'] == 1)
        tip = next(o['local_pose']['translation'][1] for o in
                   model['assembly']['component_structure']['occurrences'] if o['component_id'] == 3)
        old_model, old_housing = section(client,previous)
        _, new_housing = section(client,current)
    sheet = Image.new('RGB',(1600,1300),'#11151B')
    draw = ImageDraw.Draw(sheet)
    draw.text((30,20),'Servo fit correction | The ear datum was wrong',font=font(34,True),fill=WHITE)
    draw.text((30,72),'24.7 mm runs from the UNDERSIDE of the mounting ear to the rear case face.',font=font(25),fill=TEAL)
    with tempfile.TemporaryDirectory() as folder:
        for x,title,housing,offset in [(25,'Previous housing: ears 2.7 mm too far rearward',old_housing,2.7),
                                      (815,'Corrected housing: drawing datums restored',new_housing,0)]:
            path = Path(folder)/f'{x}.png'
            # Same corrected servo in both panels; raised to expose the mating
            # faces. Before panel shows its axial position when seated in old slots.
            meshes = [((229,174,60),triangles(housing)),
                      ((100,125,153),triangles(servo,lambda p:(p[0],tip-p[2]+offset,p[1]+24)))]
            framed(meshes,(755,445),path,margin=25,direction=(.9,-1.3,1.9))
            sheet.paste(Image.open(path),(x,158))
            draw.text((x+15,125),title,font=font(23,True),fill=WHITE)
    draw.text((30,610),'Native CAD rear-bay sections. Servo raised 24 mm to reveal the seats; source parts remain whole.',font=font(22),fill=MUTED)
    draw.line((30,651,1570,651),fill='#384552',width=2)

    def panel(x,title,ear_slot,servo_shift,color):
        draw.text((x,674),title,font=font(26,True),fill=color)
        def pos(y):return x+30+(y-151.0)*16.3
        draw.text((x,720),'Housing case cavity: Y151.7 to Y191.7',font=font(21),fill=MUTED)
        draw.rectangle((pos(151.7),762,pos(191.7),875),outline=color,width=3)
        draw.rectangle((pos(ear_slot[0]),739,pos(ear_slot[1]),895),outline=color,width=4)
        draw.rectangle((pos(152.7+servo_shift),789,pos(190.2+servo_shift),849),fill='#43586E',outline='#B8C8D8',width=2)
        draw.rectangle((pos(162.8+servo_shift),752,pos(165.5+servo_shift),886),fill='#657F98',outline=WHITE,width=2)
        a,b=pos(165.5+servo_shift),pos(190.2+servo_shift)
        draw.line((a,916,b,916),fill=WHITE,width=2)
        for xx in (a,b):draw.line((xx,902,xx,925),fill=WHITE,width=2)
        draw.text(((a+b)/2-122,930),'24.7 from ear underside',font=font(20),fill=WHITE)
        if servo_shift:
            draw.line((pos(191.7),754,pos(191.7),886),fill='#FF877F',width=3)
            draw.text((x,974),'Seated rear: Y192.9 | 1.2 mm interference',font=font(23,True),fill='#FF877F')
        else:
            draw.text((x,974),'Seated rear: Y190.2 | 1.5 mm nominal room',font=font(23,True),fill=TEAL)
        draw.text((x,1013),f'Ear pocket: Y{ear_slot[0]:.1f} to Y{ear_slot[1]:.1f}',font=font(22),fill=MUTED)
    panel(35,'Before: physical servo seated in old pockets',slot(old_model),2.7,ORANGE)
    panel(835,'After: physical servo at the correct datum',slot(model),0,TEAL)
    draw.line((30,1060,1570,1060),fill='#384552',width=2)
    for y,text in [(1080,'Case pocket: 41.3 x 20.8 x 40.0 mm | clears 40.5 x 20.0 x 37.5 mm case envelope'),
                   (1121,'Ear: 2.7 mm | slot: 3.1 mm | ear span: 56 mm | mounting centers corrected to 49 mm'),
                   (1162,'Shaft datum unchanged | rear chamber extended 0.6 mm | auger, adapter and PLA sleeve unchanged'),
                   (1203,'23 fit/end-stop poses + 6 insertion + 5 closure poses passed; only the housing halves need reprinting')]:
        draw.text((30,y),text,font=font(24,True) if y==1203 else font(23),fill=TEAL if y==1203 else WHITE)
    draw.text((30,1250),'All dimensions in mm. Nominal supplier dimensions; printed fits, cable boot and loaded strength require physical verification.',font=font(19),fill=MUTED)
    output=ROOT/'renders/housing-preprint-review.png'
    sheet.save(output)
    (ROOT/'renders/housing-preprint-provenance.json').write_text(json.dumps({
        'image':output.name,'method':'Native CAD rear-bay sections and axial dimension diagram',
        'source_project':source.name,'source_project_sha256':hashlib.sha256(current).hexdigest(),
        'reference_commit':REFERENCE,'reference_project_sha256':hashlib.sha256(previous).hexdigest(),
        'display_only_cut':'Housing material forward of Y148 omitted in isolated unsaved CAD document',
        'servo_display_pose':'Corrected reference raised 24 mm; before-panel seat position +2.7 mm rearward',
        'ear_pocket_y_before':slot(old_model),'ear_pocket_y_after':slot(model)},indent=2)+'\n')
    print('Saved native servo fit correction image',flush=True)


if __name__=='__main__':main()
