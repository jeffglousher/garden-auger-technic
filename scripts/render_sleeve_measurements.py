"""Numbered caliper locations using the native-model nominal sleeve profile."""
from pathlib import Path
from PIL import Image,ImageDraw
from render_common import font
OUT=Path(__file__).resolve().parents[1]/'renders/rounded-housing/sleeve-measurements.png'
OUT.parent.mkdir(parents=True,exist_ok=True)
im=Image.new('RGB',(1400,850),(24,28,34));d=ImageDraw.Draw(im)
d.text((35,24),'PLA wear sleeve | numbered caliper locations',font=font(32,True),fill='white')
d.text((35,73),'Model values only. Measure the printed part; avoid the chamfer when checking the bore.',font=font(21),fill=(180,194,206))
scale=10;cx,cy=350,380
r=17*scale;ri=14.3*scale
d.ellipse((cx-r,cy-r,cx+r,cy+r),fill=(55,170,161));d.ellipse((cx-ri,cy-ri,cx+ri,cy+ri),fill=(24,28,34))
def arrow(a,b,color):
 d.line((a,b),fill=color,width=4)
 for p,q in [(a,b),(b,a)]:
  import math
  t=math.atan2(q[1]-p[1],q[0]-p[0]);length=14
  pts=[p,(p[0]+length*math.cos(t+.45),p[1]+length*math.sin(t+.45)),(p[0]+length*math.cos(t-.45),p[1]+length*math.sin(t-.45))]
  d.polygon(pts,fill=color)
arrow((cx-r,cy-r-30),(cx+r,cy-r-30),(242,191,81))
d.text((160,135),'1  Outside diameter: 34.00 mm',font=font(23,True),fill=(242,191,81))
arrow((cx-ri,cy),(cx+ri,cy),(246,144,103))
d.text((165,575),'2  Straight bore: 28.60 mm',font=font(23,True),fill=(246,144,103))
x0,y0,s=910,220,10
points=[(120.6,15),(121.3,14.3),(130.8,14.3),(131,14.5),(131,17),(120.6,17)]
def pos(p):return (x0+(p[0]-120.6)*s,y0+(17-p[1])*s)
d.polygon([pos(p) for p in points],fill=(55,170,161))
d.polygon([(x,y0+34*s-(y-y0)) for x,y in [pos(p) for p in points]],fill=(55,170,161))
arrow((x0,y0-38),(x0+10.4*s,y0-38),(139,183,237))
d.text((760,140),'3  Overall length: 10.40 mm',font=font(23,True),fill=(139,183,237))
d.text((730,580),'Axial section, one scale; end chamfers shown',font=font(20),fill=(180,194,206))
d.text((730,615),'Front mouth is 30.00 mm; rear mouth 29.00 mm.',font=font(20),fill=(180,194,206))
d.text((730,645),'Those are not the straight bore diameter.',font=font(20),fill=(180,194,206))
d.text((35,700),'Housing seat: 35.60 mm diameter x10.90 mm long | journal: 28.00 mm diameter',font=font(24,True),fill='white')
d.text((35,752),'Expected model clearance: 0.60 mm bore / 1.60 mm outer diameter / 0.50 mm total end float.',font=font(22),fill=(180,194,206))
im.save(OUT)
print(OUT)
