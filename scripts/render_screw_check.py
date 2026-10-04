"""Actual native adapter/screw section with an explicitly unverified shaft proxy."""
import json
from pathlib import Path
from PIL import Image,ImageDraw
from render_common import font
from direct_drive_parameters import HEAD_SEAT_Y,SHAFT_TIP_SEAT_Y,PILOT_REAR_Y

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=json.loads((ROOT/'.build/direct-drive/screw-projections.json').read_text())
    image=Image.new('RGB',(1600,1160),(17,21,27));d=ImageDraw.Draw(image)
    ink=(231,240,248);muted=(172,191,208);accent=(231,184,95)
    d.text((35,20),'Center screw | Actual CAD section and conditional shaft stack',font=font(31,True),fill=ink)
    d.text((35,68),'Adapter + M3 x 6 envelope are native geometry. Shaft and thread-bottom illustration are reference assumptions.',font=font(21),fill=muted)
    panel=Image.new('RGB',(1110,635),(24,28,34));q=ImageDraw.Draw(panel)
    scale=72;left=140.0;center=310
    def tr(point):return((point[0]-left)*scale+50,center-point[1]*scale)
    def poly(points,color,width=3):q.line([tr(v) for v in points],fill=color,width=width)
    # The section is intentionally cropped to the screw-bearing web; the
    # external 28 mm flange / 14 mm square are outside this close-up.
    for key,color in [('adapter',(195,201,208)),('screw',(88,177,225))]:
        for c in p[key]['section']:poly(c['points'],color,4)
    def dashed(a,b,color,width=2):
        aa=tr(a);bb=tr(b)
        length=((bb[0]-aa[0])**2+(bb[1]-aa[1])**2)**.5
        steps=max(1,int(length/12))
        for i in range(steps):
            t0=i/steps;t1=min((i+.6)/steps,1)
            q.line([(aa[0]+(bb[0]-aa[0])*t0,aa[1]+(bb[1]-aa[1])*t0),
                    (aa[0]+(bb[0]-aa[0])*t1,aa[1]+(bb[1]-aa[1])*t1)],fill=color,width=width)
    for a,b in [((148.7,2.95),(152.7,2.95)),((148.7,-2.95),(152.7,-2.95)),
                ((148.7,2.95),(148.7,-2.95)),((152.7,2.95),(152.7,-2.95))]:
        dashed(a,b,accent)
    dashed((140,0),(154,0),(86,106,123),1)
    # This marks the front surface of the existing reference servo nose,
    # not a qualified manufacturer shaft shoulder or threaded cavity.
    dashed((150.7,-4.5),(150.7,4.5),(94,118,143),2)
    def dim(a,b,z,label):
        ax,ay=tr((a,z));bx,by=tr((b,z))
        q.line([(ax,ay),(bx,by)],fill=muted,width=2)
        for xx,sign in [(ax,1),(bx,-1)]:
            q.line([(xx,ay-10),(xx,ay+10)],fill=muted,width=2)
            q.polygon([(xx,ay),(xx+sign*9,ay-4),(xx+sign*9,ay+4)],fill=muted)
        width=q.textlength(label,font=font(20,True))
        x=(ax+bx-width)/2
        q.rectangle((x-6,ay-37,x+width+6,ay-10),fill=(24,28,34))
        q.text((x,ay-36),label,font=font(20,True),fill=ink)
    dim(HEAD_SEAT_Y,SHAFT_TIP_SEAT_Y,3.75,'2.60 seat stack')
    dim(HEAD_SEAT_Y,HEAD_SEAT_Y+6,-3.6,'6.00 under-head length')
    dim(SHAFT_TIP_SEAT_Y,HEAD_SEAT_Y+6,-2.05,'3.40 insertion')
    q.text((26,586),'Light gray: PETG section    Blue: screw envelope    Dashed gold: hypothetical shaft / 4.00 mm usable depth',font=font(18),fill=muted)
    image.paste(panel,(30,130))
    d.text((1170,145),'CAD checks passed',font=font(24,True),fill=ink)
    notes=['Open axial passage','Head: 5.5 x 3.0 mm','Head access: 6.40 mm','Shaft passage: 3.40 mm','Neck relief: 4.0 x 0.3','No printed-part overlap']
    for i,note in enumerate(notes):d.text((1170,195+i*47),note,font=font(22),fill=muted)
    d.text((1170,518),'Positive axial stop',font=font(24,True),fill=ink)
    d.text((1170,562),'Shaft tip on bore floor',font=font(20),fill=muted)
    d.text((1170,601),'Nose gap: 0.30 mm',font=font(20),fill=muted)
    d.text((1170,637),'Reference dimensions',font=font(19),fill=accent)
    d.line((35,794,1565,794),fill=(56,70,84),width=2)
    d.text((40,825),'M3 x 6 is a trial length. These incoming inspections are required:',font=font(25,True),fill=ink)
    for i,note in enumerate(['Measured under-head length: 5.90-6.10 mm; measured seat-to-shaft-tip stack: 2.40-2.80 mm.',
        'Screw insertion: 3.10-3.70 mm. Require >=4.00 mm safe usable hole depth to leave >=0.30 mm tip room.',
        'Confirm full-thread engagement and the factory thread/pitch. INJORA does not publish the usable hole depth.',
        'The drawing does not confirm the actual thread bottom; the dashed shaft and hole depth are illustrative.']):
        d.text((40,880+i*44),note,font=font(23),fill=muted if i<3 else accent)
    d.text((40,1083),'Screw seats on PETG; PETG seats on the rotating shaft tip. Keep the adapter clear of the stationary nose.',font=font(23,True),fill=ink)
    image.save(ROOT/'renders/direct-drive-screw-check.png')
    print('Native screw section rendered; physical thread depth explicitly unverified',flush=True)

if __name__=='__main__':main()
