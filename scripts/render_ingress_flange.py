"""Native entrance closeup and dimensioned axial half-section of the flange."""
import json
from pathlib import Path

from cad_client import CadClient
from build_servo_rear_fit_test import read_model,digest
from render_clamshell_detail import crop
from render_common import framed,banner


def main(build,cad,out):
    out.mkdir(parents=True,exist_ok=True)
    scene=json.loads((build/'scene.json').read_text())
    bodies={b['id']:b for b in scene['bodies']}
    p=out/'entrance-closeup.png'
    framed([crop(bodies[i],[-35,92,-25],[35,122,25]) for i in [26,46,15,90]],
        (1100,760),p,margin=60,direction=(1.3,-1.8,1.1))
    banner(p,'Rotating flange ahead of the housing lip',
        'Native geometry crop | orange auger shield / yellow fixed lip | normal closure retained')
    with CadClient() as c:
        c.call('cad_load_project_model',{'model_json':json.dumps(read_model(cad))})
        sections={str(bid):c.call('solid_section_review',{'body_id':bid,'plane':'yz',
            'offset_mm':0,'deflection_mm':.01}) for bid in [26,46,90,15]}
        engine=digest(c.executable)
    (build/'entrance-sections.json').write_text(json.dumps(sections))
    x=lambda y:38+(y-94)*17
    y=lambda z:52+(26-z)*17
    paths=[]
    for bid,color in [(26,'#e5ae3c'),(46,'#e5ae3c'),(90,'#d57e37'),(15,'#d57e37')]:
        # Display native edge chains directly, without inventing connecting
        # segments or inferring filled regions from open section curves.
        d=' '.join('M'+' L'.join(f'{x(a):.4f},{y(b):.4f}' for a,b in edge['points'])
            for edge in sections[str(bid)]['section'] if len(edge['points'])>1)
        paths.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.4"/>')
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 620">
<rect width="560" height="620" fill="#181c22"/>
<style>text{{font-family:Segoe UI,sans-serif;fill:#edf2f7}}.small{{font-size:13px}}.dim{{stroke:#ecf0f4;stroke-width:1.2;fill:none}}</style>
<text x="24" y="25" font-size="18" font-weight="600">Auger entrance · native axial half-section</text>
<defs><clipPath id="window"><rect x="38" y="52" width="476" height="442"/></clipPath></defs>
<g clip-path="url(#window)">{''.join(paths)}</g>
<path d="M38,{y(0)} H514" stroke="#afbdca" stroke-dasharray="6 5"/>
<text x="38" y="520" class="small">Auger centerline · forward is left</text>
<path class="dim" d="M{x(102.3)},{y(24.6)} V{y(25.6)} H{x(103.9)} V{y(24.6)} M{x(103.1)},{y(25.6)} L290,48 H515"/>
<text x="295" y="43" class="small">1.6 mm nominal rear gap</text>
<path class="dim" d="M{x(98.1)},{y(20.6)} H{x(97.2)} V{y(24)} H{x(98.1)}"/>
<text x="28" y="88" class="small">3.4 mm</text><text x="28" y="105" class="small">overhang</text>
<text x="246" y="117" class="small">Fixed yellow lip</text>
<path class="dim" d="M245,121 L{x(105.5)},{y(20.6)}"/>
<text x="40" y="250" class="small">Rotating</text><text x="40" y="267" class="small">orange flange</text>
<path class="dim" d="M132,255 L{x(100.3)},{y(15)}"/>
<text x="24" y="558" font-size="15">Ø48 flange · 3.3 mm broad web · beveled edge</text>
<text x="24" y="582" class="small">Native section at X0, 0.01 mm deflection. No contact seal.</text>
<text x="24" y="603" class="small">Gap is 1.1 mm with the existing +0.5 mm axial allowance.</text>
</svg>'''
    (out/'entrance-section.svg').write_text(svg,encoding='utf-8')
    (out/'provenance.json').write_text(json.dumps({'cad':str(cad),'cad_sha256':digest(cad),
        'engine_sha256':engine,'section_plane':'YZ at X0','section_deflection_mm':.01,
        'view':'Actual native section, positive-Z half; centerline at bottom. Closeup is a mesh crop.',
        'section_data_sha256':digest(build/'entrance-sections.json')},indent=2)+'\n')
    print('Native entrance closeup and axial half-section saved',flush=True)
