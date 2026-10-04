"""Compare actual old/new housing CAD and their axial cutting profiles."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageDraw
from render_common import framed, triangles, font
from cad_client import CadClient
from native_render_source import native_render_source

ROOT = Path(__file__).resolve().parents[1]


def main():
    proof = json.loads((ROOT / 'housing-nesting-verification.json').read_text())
    source = (ROOT / proof['source_project']).read_bytes()
    prior = subprocess.check_output(['git', 'show',
        f"{proof['reference_commit']}:{proof['source_project']}"], cwd=ROOT)
    assert hashlib.sha256(source).hexdigest() == proof['source_project_sha256']
    assert hashlib.sha256(prior).hexdigest() == proof['reference_project_sha256']
    with CadClient() as client:
        old_model, before = native_render_source(client, prior)
        new_model, after = native_render_source(client, source)
    sheet = Image.new('RGB', (1600, 1120), '#11151B')
    d = ImageDraw.Draw(sheet)
    d.text((30, 20), 'Clamshell | Two nesting seats, fewer grooves', font=font(34, True), fill='#EFF5FA')
    d.text((30, 72), 'Actual CAD comparison | Lower housing inside | PETG | Same auger, adapter and PLA sleeve',
           font=font(23), fill='#B8C8D8')
    with tempfile.TemporaryDirectory() as folder:
        for scene, x, name in [(before, 24, 'Before'), (after, 812, 'After')]:
            body = next(b for b in scene['bodies'] if b['id'] == 46)
            path = Path(folder) / (name + '.png')
            framed([((229, 174, 60), triangles(body))], (760, 490), path,
                   margin=24, direction=(.9, -1.3, 1.9))
            sheet.paste(Image.open(path), (x, 154))
            d.text((x + 20, 120), name, font=font(26, True), fill='#EFF5FA')
    d.line((30, 660, 1570, 660), fill='#384552', width=2)
    d.text((30, 680), 'Removed: front counterbore, two tapered throat segments and deep connector pocket',
           font=font(25, True), fill='#EFF5FA')
    def points(model):
        s = next(s for s in model['sketches'] if s['name'] == 'Chassis integral thrust stops and journal seat')
        return [(e['position']['x'], e['position']['y'])
                for _, e in s['snapshot']['entities'] if e['type'] == 'point']
    def project(p):
        return (45 + (p[0] - 107.8) * 1500 / (153 - 107.8), 935 - p[1] * 10)
    old, new = points(old_model), points(new_model)
    d.polygon([project(p) for p in new], fill='#568EAC', outline='#BDD8E8', width=3)
    d.line([project(p) for p in old + [old[0]]], fill='#F0A979', width=3)
    d.text((30, 722), 'Blue: new cut profile    Orange outline: previous profile', font=font(20), fill='#B8C8D8')
    for y, label in [(107.8, 'Plain throat'), (114.5, 'Collar capture'), (123, 'Loose PLA sleeve'), (140, 'Journal / adapter')]:
        x, _ = project((y, 0))
        d.text((x, 949), label, font=font(20), fill='#B8C8D8')
    d.text((30, 1002), 'Both collar stops retained | 0.60 mm nominal auger end float | 0.50 mm sleeve end float',
           font=font(23, True), fill='#83D2C3')
    d.text((30, 1045), 'One cable channel in the split seam; keep the plug outside. Pins, screw seats and insert pilots remain.',
           font=font(22), fill='#B8C8D8')
    d.text((30, 1082), 'Native checks pass: rotation, both collar stops, sleeve capture, shaft offset and adapter clearance.',
           font=font(20), fill='#B8C8D8')
    path = ROOT / 'renders/clamshell-nested.png'
    sheet.save(path)
    provenance = {'image': path.name, 'method': 'Raster rendering of native CAD meshes and actual axial sketches',
        'source_project': proof['source_project'],
        'source_project_sha256': hashlib.sha256(source).hexdigest(),
        'before_project_sha256': proof['reference_project_sha256'], 'reference_commit': proof['reference_commit'],
        'verification': 'housing-nesting-verification.json'}
    (ROOT / 'renders/clamshell-nested-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print('Before/after native housing and actual cutting profiles rendered', flush=True)


if __name__ == '__main__':
    main()
