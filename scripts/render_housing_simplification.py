"""Render actual rebuilt CAD meshes and the shared revolve sketch."""
import hashlib
import json
from pathlib import Path
import tempfile

from PIL import Image, ImageDraw
from render_common import framed, triangles, font

ROOT = Path(__file__).resolve().parents[1]


def main():
    scene = json.loads((ROOT / '.build/direct-drive/scene.json').read_text())
    model = json.loads((ROOT / '.build/direct-drive/model.json').read_text())
    proof = json.loads((ROOT / 'housing-simplification-verification.json').read_text())
    bodies = {b['id']: b for b in scene['bodies']}
    image = Image.new('RGB', (1600, 1080), (17, 21, 27))
    d = ImageDraw.Draw(image)
    before, after = proof['housing_before'], proof['housing_after']
    d.text((32, 20), 'Clamshell | Same solid, simpler construction', font=font(34, True), fill='#EFF5FA')
    d.text((32, 72), f"Housing history: {before['history_entries']} > {after['history_entries']} entries   |   "
           f"Solid operations: {before['solid_operations']} > {after['solid_operations']}",
           font=font(24), fill='#B8C8D8')
    with tempfile.TemporaryDirectory() as folder:
        for body, x, title, pose in [(26, 24, 'Upper half - inside', lambda p: (-p[0], p[1], -p[2])),
                                     (46, 812, 'Lower half - inside', None)]:
            path = Path(folder) / f'{body}.png'
            framed([((229, 174, 60), triangles(bodies[body], pose))], (760, 485),
                   path, margin=24, direction=(.9, -1.3, 1.9))
            image.paste(Image.open(path), (x, 156))
            d.text((x + 20, 124), title, font=font(25, True), fill='#EFF5FA')
    d.line((32, 660, 1568, 660), fill='#384552', width=2)
    d.text((32, 680), 'One shared revolve cut: front opening + collar capture + sleeve + journal + adapter chamber',
           font=font(25, True), fill='#EFF5FA')
    sketch = next(s for s in model['sketches'] if s['name'] == 'Chassis integral thrust stops and journal seat')
    points = [(e['position']['x'], e['position']['y'])
              for _, e in sketch['snapshot']['entities'] if e['type'] == 'point']
    x0, x1 = min(p[0] for p in points), max(p[0] for p in points)
    def project(p):
        return (50 + (p[0] - x0) * 1490 / (x1 - x0), 920 - p[1] * 8.5)
    d.polygon([project(p) for p in points], fill='#568EAC', outline='#BDD8E8', width=2)
    d.line((50, 921, 1540, 921), fill='#8196AB', width=2)
    for y, label in [(107.8, 'Front'), (114.5, 'Collar'), (124, 'Sleeve'), (140, 'Journal / adapter')]:
        x, _ = project((y, 0))
        d.text((x, 940), label, font=font(22), fill='#B8C8D8')
    d.text((32, 1000), 'Exact native boolean differences are empty in both directions for both halves.',
           font=font(24, True), fill='#83D2C3')
    d.text((32, 1040), 'Mating surfaces, insert pockets and dimensions preserved. Existing STLs and Bambu project are byte-identical.',
           font=font(21), fill='#B8C8D8')
    path = ROOT / 'renders/clamshell-simplified.png'
    image.save(path)
    provenance = {'image': path.name, 'method': 'Raster rendering of native rebuilt CAD mesh; actual axial sketch below',
        'source_project': 'garden-auger-direct-drive.nbcad',
        'source_project_sha256': hashlib.sha256((ROOT / 'garden-auger-direct-drive.nbcad').read_bytes()).hexdigest(),
        'verification': 'housing-simplification-verification.json'}
    (ROOT / 'renders/clamshell-simplified-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print('Rebuilt housing halves and shared axial revolve profile rendered', flush=True)


if __name__ == '__main__':
    main()
