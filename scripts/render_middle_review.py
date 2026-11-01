"""Read-only current-CAD sections and individual pieces for design inspection."""
import json
from pathlib import Path

import numpy as np
import trimesh

from build_servo_rear_fit_test import read_model, digest
from cad_client import CadClient
from render_common import framed, triangles, shifted
from render_clamshell_detail import COLORS

ROOT = Path(__file__).resolve().parents[1]
CAD = ROOT / 'experiments/garden-auger-simple-print.limo'
OUT = ROOT / 'renders/middle-review'
BUILD = ROOT / '.build/clamshell-detail/current-assembly/disc38'
IDS = [26, 46, 15, 90, 216, 221, 1]


def section_svg(sections, filename, bounds, title, axes, transform=None):
    """Draw native edge chains without inventing connections or material fills."""
    left, bottom, right, top = bounds
    width, height = 1100, 530
    scale = min(980 / (right-left), 370 / (top-bottom))
    ox = (width - (right-left)*scale)/2
    oy = 65 + (370-(top-bottom)*scale)/2
    xy = lambda a,b: (ox+(a-left)*scale, oy+(top-b)*scale)
    paths = []
    for bid in IDS:
        color = '#8a96a6' if bid == 1 else '#%02x%02x%02x' % COLORS[bid]
        for edge in sections[str(bid)]['section']:
            points = edge['points']
            if bid == 1 and transform:
                points = [transform(a,b) for a,b in points]
            if len(points) > 1:
                coords = ' '.join(f'{x:.4f},{y:.4f}' for x,y in [xy(a,b) for a,b in points])
                paths.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2"/>')
    bar = 10 * scale
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">
<rect width="1100" height="530" fill="#181c22"/>
<style>text{{font-family:Segoe UI,sans-serif;fill:#e7edf4}}</style>
<text x="30" y="32" font-size="22">{title}</text>
<defs><clipPath id="window"><rect x="45" y="52" width="1010" height="392"/></clipPath></defs>
<g clip-path="url(#window)">{''.join(paths)}</g>
<path d="M50,470 h{bar}" stroke="#e7edf4" stroke-width="3"/>
<text x="50" y="495" font-size="16">10 mm</text>
<text x="250" y="485" font-size="17">{axes}</text>
<text x="30" y="520" font-size="14">Native CAD section edges, 0.01 mm deflection. Lines mark material boundaries; no slicer infill shown.</text>
</svg>'''
    (OUT / filename).write_text(svg, encoding='utf-8')


def main():
    OUT.mkdir(exist_ok=True, parents=True)
    original = digest(CAD)
    validation = json.loads((ROOT/'simple-print-validation.json').read_text())
    assert validation['cad_sha256'] == original
    sections = {}
    with CadClient() as c:
        assert digest(c.executable) == validation['engine_sha256']
        c.call('cad_load_project_model', {'model_json': json.dumps(read_model(CAD))})
        scene = c.call('solid_scene')
        for name, plane, offset in [('axial','yz',0),('bearing','xz',125.75),('servo','xz',175)]:
            section = {}
            for bid in IDS:
                # Servo body is stored locally: assembly (x,y,z)=(x,148.7-z,y).
                p, o = ('xy',148.7-offset) if bid == 1 and plane == 'xz' else (plane,offset)
                section[str(bid)] = c.call('solid_section_review', {'body_id':bid,
                    'plane':p,'offset_mm':o,'deflection_mm':.01})
            sections[name] = section
        engine = digest(c.executable)
    (BUILD/'middle-sections.json').write_text(json.dumps(sections))
    section_svg(sections['axial'],'axial.svg',(96,-24,210,24),
        'A | Lengthwise center section - X = 0 mm', 'Left: auger / shield     Right: servo / rear wall',lambda a,b:(148.7-b,a))
    section_svg(sections['bearing'],'bearing.svg',(-35,-24,35,24),
        'B | Across the bushing - Y = 125.75 mm', 'Horizontal: X     Vertical: Z     Upper / lower seam: Z = 0')
    section_svg(sections['servo'],'servo.svg',(-45,-24,35,24),
        'C | Across the servo case - Y = 175 mm', 'Horizontal: X     Vertical: Z     Gray: purchased servo envelope')
    bodies = {b['id']:b for b in scene['bodies']}
    meshes = {bid:(COLORS[bid], triangles(bodies[bid],
        (lambda p:(p[0],148.7-p[2],p[1])) if bid == 1 else None)) for bid in IDS}
    parts = [('upper',[26],(1.2,-1.7,1.2)),('lower',[46],(1.2,-1.7,1.2)),
        ('auger',[15,90],(1.8,.1,.65)),('adapter',[216],(1.2,-1.7,1.2)),
        ('adapter-back',[216],(1.2,1.7,1.2)),('bushing',[221],(1.3,1.8,1.2)),
        ('servo-reference',[1],(1.2,-1.7,1.2))]
    for name, ids, direction in parts:
        geometry = [meshes[i] for i in ids]
        if name == 'upper':
            geometry = [(color,[tuple((-p[0],p[1],-p[2]) for p in t) for t in tris]) for color,tris in geometry]
        framed(geometry,(1100,650),OUT/f'{name}.png',margin=45,direction=direction)
    offsets={26:(0,0,48),46:(0,0,-30),15:(0,-35,0),90:(0,-35,0),
             216:(0,23,12),221:(0,0,22),1:(0,32,0)}
    framed([shifted(meshes[i],offsets[i]) for i in IDS],(1200,900),OUT/'exploded.png',
        margin=50,direction=(1.5,-.7,1.3))
    # Capped half-model view: actual native tessellations, no altered source CAD.
    clip = trimesh.creation.box(extents=[100,125,80])
    clip.apply_translation([-50,152.5,0])
    cut = []
    for bid, (color, tris) in meshes.items():
        arr = np.array(tris)
        mesh = trimesh.Trimesh(arr.reshape(-1,3),np.arange(arr.size//3).reshape(-1,3),process=True)
        cropped = trimesh.boolean.intersection([mesh,clip],engine='manifold')
        if len(cropped.faces):
            cut.append((color,cropped.triangles.tolist()))
    framed(cut,(1200,720),OUT/'cutaway.png',margin=50,direction=(2.5,-.65,1.2))
    assert digest(CAD) == original
    provenance = {'cad':str(CAD.relative_to(ROOT)), 'cad_sha256':original,
        'engine_sha256':engine,'native_sections_sha256':digest(BUILD/'middle-sections.json'),
        'native_sections':{'axial':'YZ X0, cropped display Y96..210', 'bearing':'XZ Y125.75','servo':'XZ Y175'},
        'cutaway':'Native tessellated solids clipped/capped at X0; retain X<=0 and Y90..215. Presentation only.',
        'servo':'Purchased reference envelope; no internal servo mechanisms modeled.',
        'individual_parts':'Different image scales; core15 and flight90 together are one printed auger.',
        'geometry_modified':False,'printer_command_sent':False,
        'images':{p.name:digest(p) for p in OUT.iterdir() if p.suffix in ['.png','.svg']}}
    (OUT/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print('Review complete; source CAD unchanged.',flush=True)


if __name__ == '__main__':
    main()
