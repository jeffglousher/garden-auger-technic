"""Label/crop actual noBS CAD screenshots; never synthesize part geometry."""
from pathlib import Path
import hashlib
import json
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'renders/cad-mating'
INK='#203244'
MUTED='#53677A'
ACCENT='#167C88'
FONT=Path('C:/Windows/Fonts/arial.ttf')
BOLD=Path('C:/Windows/Fonts/arialbd.ttf')

def font(size,bold=False):
    return ImageFont.truetype(str(BOLD if bold else FONT),size)

def marker(draw,transform,number,label_point,face_point):
    x,y=transform(*label_point);tx,ty=transform(*face_point)
    draw.line((x,y,tx,ty),fill=ACCENT,width=3)
    draw.ellipse((tx-4,ty-4,tx+4,ty+4),fill=ACCENT)
    draw.ellipse((x-15,y-15,x+15,y+15),fill=ACCENT,outline='white',width=2)
    draw.text((x,y),str(number),font=font(19,True),anchor='mm',fill='white')

def card(canvas,x,title,name,crop,lines,markers=()):
    draw=ImageDraw.Draw(canvas)
    draw.rounded_rectangle((x,105,x+752,941),radius=12,fill='white',outline='#CFD8E0',width=2)
    draw.text((x+22,125),title,font=font(26,True),fill=INK)
    source=Image.open(OUT/f'{name}-native.png').convert('RGB').crop(crop)
    scale=min(704/source.width,566/source.height)
    size=(round(source.width*scale),round(source.height*scale))
    source=source.resize(size,Image.Resampling.LANCZOS)
    ix=x+24+(704-size[0])//2;iy=178+(566-size[1])//2
    canvas.paste(source,(ix,iy))
    transform=lambda px,py:(ix+(px-crop[0])*scale,iy+(py-crop[1])*scale)
    for item in markers:marker(draw,transform,*item)
    draw.line((x+22,766,x+730,766),fill='#DCE3E9',width=2)
    for index,line in enumerate(lines):
        draw.text((x+22,787+index*33),line,font=font(22),fill=INK if index<3 else MUTED)

PLATES=[
    ('01-square-drive','Square drive | the two mating parts and assembled clearances',[
        ('Socket and square peg','square',(400,195,1185,760),[
            '1  Auger socket: 14.40 / R1.20, 12.00 deep',
            '2  Adapter peg: 14.00 / R1.00, 11.60 long',
            '0.20 nominal clearance per square flat',
            'Orange PETG auger / gray PETG adapter'],[
                (1,(427,428),(525,462)),(2,(1125,520),(1033,603))]),
        ('Square joint in its nominal assembled pose','drive',(565,255,1040,740),[
            '1  Square engagement: 10.00 nominal',
            '2  Peg-tip to socket-floor gap: 2.00 nominal',
            '3  Hub to adapter-flange gap: 1.60 nominal',
            'Axial section; orange socket wraps the gray peg'],[
                (1,(767,305),(785,393)),(2,(570,424),(678,424)),
                (3,(1000,310),(853,328))]),
    ],'Actual CAD surfaces. All dimensions in mm; nominal assembled pose before end float.'),
    ('02-servo-and-screw','Servo connection | press-fit bore and screw clamp seats',[
        ('Adapter rear face and shaft-tip seat','pilot',(545,185,1025,790),[
            '1  Plain round pilot: Ø5.70 ×1.70 deep (trial)',
            '2  Annular floor seats on the rotating shaft tip',
            '3  Nominal Ø5.90 shaft envelope shown in blue',
            'Spline teeth and internal thread omitted in reference'],[
                (1,(579,371),(690,414)),(2,(578,474),(718,435)),
                (3,(970,710),(865,722))]),
        ('Center screw and annular clamp web','screw',(570,235,1075,755),[
            '1  Head seat; Ø6.40 screw-head access',
            '2  Shaft-tip seat; 2.60 between clamp seats',
            'Ø3.40 passage; Ø4.00 ×0.30 neck relief',
            'Blue M3×6 envelope gives 3.40 nominal insertion'],[
                (1,(1018,401),(886,460)),(2,(1022,577),(928,533))]),
    ],'Physical pilot fit, shaft exposure and screw bottom clearance require actual-servo inspection.'),
    ('03-bearing-and-capture','Auger support | journal, loose sleeve and collar capture',[
        ('PETG journal and full PLA wear sleeve','sleeve',(455,195,1135,790),[
            '1  Auger cylindrical journal: Ø28.00',
            '2  PLA running bore: Ø28.60; radial gap 0.30',
            'Sleeve outside: Ø34.00; length 10.40',
            'Orange PETG / teal PLA; sleeve has no lock'],[
                (1,(561,231),(725,378)),(2,(1095,470),(855,583))]),
        ('Clamshell, collar and sleeve axial section','capture',(570,215,1045,780),[
            '1  Collar: Ø34 ×3.00; stop span 3.60',
            '2  Sleeve cavity: Ø35.60; outside gap 0.80 radial',
            '3  Sleeve bore/journal: 0.30 nominal radial gap',
            'Collar end float 0.60; combined sleeve float 1.10'],[
                (1,(591,298),(687,337)),(2,(1007,283),(810,320)),
                (3,(1009,404),(810,353))]),
    ],'Yellow PETG chassis alone traps the collar. Display crops and half-sections expose the contacts.'),
    ('04-clamshell-and-inserts','Chassis contacts | split faces, bearing pockets and fastener holes',[
        ('Both bearing regions, opened for inspection','shells',(505,270,1110,750),[
            '1  Flat clamshell split faces meet on closure',
            '2  Cylindrical sleeve pocket: Ø35.60',
            '3  Collar thrust stops: 3.60 axial span',
            'Bare journal seats: Ø29.60; bearing regions cropped'],[
                (1,(1039,405),(1004,537)),(2,(725,286),(676,393)),
                (3,(513,410),(610,448))]),
        ('Full inner faces and servo cradle','chassis',(395,210,1220,755),[
            '1  Lower insert pilots: 4 × Ø4.00, 6.70 deep',
            '2  Upper M3 screw-clearance passages: Ø3.40',
            '3  Servo cradle and ear-capture faces',
            'RX-M3×5.7 inserts; upper half flipped open'],[
                (1,(434,348),(477,410)),(2,(615,641),(684,537)),
                (3,(998,361),(914,498))]),
    ],'Both yellow halves are PETG. M3×12 front / M3×18 rear; inserts seat flush at the split face.'),
]

def main():
    for filename,title,cards,note in PLATES:
        canvas=Image.new('RGB',(1600,1000),'#F0F4F7');draw=ImageDraw.Draw(canvas)
        draw.rectangle((0,0,1600,84),fill=INK)
        draw.text((30,17),title,font=font(32,True),fill='white')
        draw.text((31,55),'noBS CAD 0.2.2 • actual native viewport captures • direct press-fit prototype',
            font=font(17),fill='#CCD8E3')
        for x,item in zip((32,816),cards):card(canvas,x,*item)
        draw.text((32,964),note,font=font(20),fill=MUTED)
        canvas.save(OUT/f'{filename}.png')
    files=sorted(OUT.glob('*-native.png'))
    manifest={'application':'noBS CAD 0.2.2','source_project':'garden-auger-direct-drive.nbcad',
        'method':'Analytic STEP exports imported into temporary native CAD review documents; desktop screenshots cropped and labeled.',
        'canonical_project_changed':False,
        'display_only_operations':['Exploded poses','Bearing-region crops','Axial half-sections','Raise review geometry above viewport floor grid'],
        'reference_geometry':'Blue Ø5.9 shaft envelope and blue M3x6 screw omit teeth and threads. Actual supplier shaft exposure and thread cavity are unverified.',
        'captures':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in files},
        'plates':[p[0]+'.png' for p in PLATES]}
    (OUT/'provenance.json').write_text(json.dumps(manifest,indent=2))
    print('Four labeled plates generated from eight native CAD screenshots.')

if __name__=='__main__':main()
