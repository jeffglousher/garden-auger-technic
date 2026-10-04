"""Show the corrected housing using saved native CAD and actual sketch sizes."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageDraw

from cad_client import CadClient
from native_render_source import native_render_source
from render_common import framed, triangles, font

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = '940e024634e4a6526b57c2783ebf87731270294d'


def main():
    source = ROOT / 'garden-auger-direct-drive.nbcad'
    current = source.read_bytes()
    previous = subprocess.check_output(['git', 'show', f'{REFERENCE}:{source.name}'], cwd=ROOT)
    with CadClient() as client:
        old_model, old_scene = native_render_source(client, previous)
        model, scene = native_render_source(client, current)
    sheet = Image.new('RGB', (1600, 1190), '#11151B')
    draw = ImageDraw.Draw(sheet)
    draw.text((30, 20), 'Housing review | Corrected before the next print', font=font(34, True), fill='#EFF5FA')
    draw.text((30, 72), 'Actual saved CAD | Existing auger, adapter and sleeve preserved | Same 81 history entries', font=font(23), fill='#B8C8D8')
    with tempfile.TemporaryDirectory() as folder:
        for x, title, native in [(25, 'Previous housing', old_scene), (815, 'Corrected housing', scene)]:
            body = next(b for b in native['bodies'] if b['id'] == 46)
            path = Path(folder) / f'{x}.png'
            framed([((229, 174, 60), triangles(body))], (755, 470), path,
                   margin=25, direction=(.9, -1.3, 1.9))
            sheet.paste(Image.open(path), (x, 157))
            draw.text((x+20, 120), title, font=font(26, True), fill='#EFF5FA')
    draw.line((30, 646, 1570, 646), fill='#384552', width=2)
    draw.text((30, 673), 'Entrance: clear the last flight; retain the thrust stop', font=font(25, True), fill='#EFF5FA')
    def entry_points(m):
        sketch = next(s for s in m['sketches'] if s['name'] == 'Chassis integral thrust stops and journal seat')
        pts = [(e['position']['x'], e['position']['y']) for _, e in sketch['snapshot']['entities'] if e['type'] == 'point']
        return pts[1:4]
    def project(p):
        return (55+(p[0]-107.8)*104, 940-(p[1]-14)*50)
    for m, color in [(old_model, '#F0A979'), (model, '#83D2C3')]:
        draw.line([project(p) for p in entry_points(m)], fill=color, width=5)
    draw.text((30, 713), 'Orange: previous cut   Teal: corrected cut', font=font(21), fill='#B8C8D8')
    draw.text((40, 961), 'Y107.8: diameter 33.2', font=font(22), fill='#83D2C3')
    draw.text((385, 961), 'Y113.7: diameter 31.2', font=font(22), fill='#B8C8D8')
    draw.text((40, 1000), 'One taper replaces a straight segment; no added grooves.', font=font(21), fill='#B8C8D8')
    draw.text((850, 673), 'Servo ears: restored pocket and less axial play', font=font(25, True), fill='#EFF5FA')
    def slot(m):
        sketch = next(s for s in m['sketches'] if s['name'] == 'Sketch62')
        rear = sketch['basis']['origin'][1]
        depth = next(e['extent']['distance'] for e in m['extrudes'] if e['feature_id'] == 183)
        return rear-depth, rear
    def ear_x(y):
        return 870+(y-164.6)*139
    for m, color, height in [(old_model, '#F0A979', 168), (model, '#83D2C3', 130)]:
        front, rear = slot(m)
        draw.rectangle((ear_x(front), 829-height/2, ear_x(rear), 829+height/2), outline=color, width=4)
    draw.rectangle((ear_x(165.5), 787, ear_x(168.2), 871), fill='#586D7F', outline='#B8C8D8', width=2)
    draw.text((925, 802), 'Reference ear: 2.7 mm', font=font(22), fill='#EFF5FA')
    draw.text((860, 939), 'Slot: 4.5 -> 3.1 mm   |   Nominal float: 1.8 -> 0.4', font=font(22), fill='#83D2C3')
    draw.text((860, 979), 'Existing ear cut moved after extensions; no extra cut.', font=font(21), fill='#B8C8D8')
    draw.line((30, 1046, 1570, 1046), fill='#384552', width=2)
    draw.text((30, 1070), 'Housing print: 6 walls, 30% gyroid, 6 top/bottom layers. Four RX-M3x5.7 inserts remain.', font=font(24, True), fill='#EFF5FA')
    draw.text((30, 1115), 'Before assembly: check printed fits, cable routing and installed adapter position. Torque remains unqualified.', font=font(22), fill='#B8C8D8')
    draw.text((30, 1151), 'Panels show native geometry; dimensions are millimeters. Servo dimensions follow the user-confirmed accurate diagram.', font=font(19), fill='#9BAEBF')
    output = ROOT / 'renders/housing-preprint-review.png'
    sheet.save(output)
    (ROOT / 'renders/housing-preprint-provenance.json').write_text(json.dumps({
        'image': output.name, 'method': 'Native CAD mesh render plus actual entrance/ear sketch coordinates',
        'source_project': source.name, 'source_project_sha256': hashlib.sha256(current).hexdigest(),
        'reference_commit': REFERENCE, 'reference_project_sha256': hashlib.sha256(previous).hexdigest()}, indent=2)+'\n')
    print('Saved native housing review image', flush=True)


if __name__ == '__main__':
    main()
