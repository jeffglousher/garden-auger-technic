"""Native mesh label crops, with recess bottoms shaded for legibility."""
import json
from pathlib import Path
from render_clamshell_detail import crop
from render_common import framed

ROOT=Path(__file__).resolve().parents[1]
scene=json.loads((ROOT/'.build/clamshell-detail/current-assembly/labeled/scene.json').read_text())
bodies={v['id']:v for v in scene['bodies']}
for bid,label,lo,hi in [(46,'lower',[-28,165,-11],[7,192,-9.8]),(26,'upper',[-29,173,9.8],[7,192,11])]:
    color,tris=crop(bodies[bid],lo,hi)
    if bid==26:tris=[tuple((-p[0],p[1],-p[2]) for p in t) for t in tris]
    recess=[];surface=[]
    for tri in tris:
        (recess if all(abs(p[2]+10.6)<1e-4 for p in tri) else surface).append(tri)
    assert recess
    framed([(color,surface),((95,65,24),recess)],(1000,740),ROOT/f'renders/labeled/{label}-label-closeup.png',margin=45,direction=(.1,-.9,2.4))
