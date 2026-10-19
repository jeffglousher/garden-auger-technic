"""Closed reverse/underside and print-face views of the actual D-grip CAD."""
import hashlib
import json
from pathlib import Path

import numpy as np
import trimesh
from render_common import triangles,framed,banner
from render_clamshell_detail import COLORS
from print_packer import component_count

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'.build/clamshell-detail/current-assembly/d-grip'
OUT=ROOT/'renders/d-grip'


def main(build=BUILD,out=OUT,solid_frame=False):
    out.mkdir(parents=True,exist_ok=True)
    scene=json.loads((build/'scene.json').read_text())
    bodies={b['id']:b for b in scene['bodies']}
    meshes={bid:(COLORS[bid],triangles(bodies[bid],(lambda p:(p[0],148.7-p[2],p[1])) if bid==1 else None)) for bid in COLORS}
    for name,direction in [('closed-reverse',(-1.2,1.7,1.2)),('closed-front',(1.2,-1.7,1.1)),('closed-underside',(-1.2,1.7,-1.2))]:
        p=out/(name+'.png');framed(list(meshes.values()),(1400,900),p,margin=65,direction=direction)
        banner(p,('Closed solid-frame assembly' if solid_frame else 'Closed D-grip assembly')+' | '+name.removeprefix('closed-'),
               'Continuous frame | exterior corner rounds | lower D grips' if solid_frame else '24 mm rounded width | 18.6 mm grip height | complete grips on lower half')
    for bid,label in [(46,'lower-print-face'),(26,'upper-print-face')]:
        transform=(lambda p:(-p[0],p[1],-p[2])) if bid==26 else None
        p=out/(label+'.png');framed([(COLORS[bid],triangles(bodies[bid],transform))],(1400,800),p,margin=65)
        banner(p,'Lower housing and complete D grips' if bid==46 else 'Upper cover | central mechanism only',
               'Flat bed faces retained | four small locating pins on lower | rear cable cheek retained')
    if solid_frame:
        # Grip geometry is unchanged; preserve the existing sample and its hash.
        (build/'comfort-sample.json').write_text((BUILD/'comfort-sample.json').read_text())
        print('Closed solid-frame and print-face views saved; existing comfort sample retained',flush=True)
        return
    # Optional comfort sample uses the actual native outer-left-grip mesh.
    raw=bodies[46]['mesh']
    lower=trimesh.Trimesh(np.array(raw['positions']).reshape(-1,3),np.array(raw['indices']).reshape(-1,3),process=True)
    box=trimesh.creation.box(extents=[55,26,21]);box.apply_translation([-70.5,193.75,-11])
    sample=trimesh.boolean.intersection([lower,box],engine='manifold')
    assert sample.is_watertight and sample.is_volume and component_count(sample)==1
    sample.vertices-=sample.bounds[0]
    sample_path=ROOT/'print-parts/grip-comfort-sample.stl';sample.export(sample_path)
    (BUILD/'comfort-sample.json').write_text(json.dumps({'file':str(sample_path.relative_to(ROOT)),
        'sha256':hashlib.sha256(sample_path.read_bytes()).hexdigest(),'bounds_mm':sample.bounds.tolist(),
        'method':'Native lower housing mesh intersected with 55 mm outer grip segment; translated onto its flat bed land.',
        'included_in_complete_project':False,'purpose':'Optional hand comfort check before printing the full housing; not a load test.'},indent=2)+'\n')
    print('Closed reverse/underside views, print faces and optional comfort sample saved',flush=True)


if __name__=='__main__':main()
