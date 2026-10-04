"""Present captured native CAD views; annotations do not modify geometry."""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw
from render_common import font

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'renders/cad-depth'


def main():
    report = json.loads((ROOT / 'direct-drive-verification.json').read_text())
    dims = report['adapter_dimensions_mm']
    canvas = Image.new('RGB', (1600, 1000), (24, 28, 34))
    draw = ImageDraw.Draw(canvas)
    ink, muted, accent = (240, 245, 250), (180, 198, 213), (238, 188, 96)
    draw.text((35, 20), 'Revised servo adapter | Native CAD views', font=font(32, True), fill=ink)
    draw.text((35, 70), 'PETG  |  Deeper round socket, larger boss and broad flange transition', font=font(24), fill=muted)
    crops = {
        'adapter-rear.png': (500, 280, 1040, 770),
        'adapter-section.jpg': (565, 245, 1065, 750),
    }
    draw.text((35, 126), 'Servo-facing socket', font=font(28, True), fill=ink)
    draw.text((835, 126), 'Axial half-section', font=font(28, True), fill=ink)
    for filename, offset in [('adapter-rear.png', (35, 180)), ('adapter-section.jpg', (835, 180))]:
        crop = Image.open(OUT / filename).convert('RGB').crop(crops[filename])
        crop.thumbnail((730, 650), Image.Resampling.LANCZOS)
        # The captures are enlarged uniformly, preserving native proportions.
        scale = min(730 / crop.width, 650 / crop.height)
        crop = crop.resize((round(crop.width * scale), round(crop.height * scale)), Image.Resampling.LANCZOS)
        canvas.paste(crop, offset)
    draw.text((35, 845), f"Boss: OD {dims['spline_boss_diameter']:.0f} mm (was 16 mm)", font=font(26, True), fill=ink)
    draw.text((35, 887), f"Straight bore wall: {dims['straight_bore_radial_wall']:.2f} mm radial", font=font(24), fill=muted)
    draw.text((835, 845), f"Socket: {dims['press_fit_pilot_depth']:.2f} mm deep (was 1.70 mm)", font=font(26, True), fill=ink)
    draw.text((835, 887), 'Square and M3 screw-seat positions preserved', font=font(24), fill=muted)
    draw.text((35, 952), 'Hitec H25T depth reference; actual INJORA shaft requires >=4.00 mm exposure. Physical fit/load unqualified.', font=font(22), fill=accent)
    canvas.save(OUT / 'adapter-revision.png')
    captures = ['adapter-front.png', 'adapter-rear.png', 'adapter-section.jpg']
    proof = {
        'application': 'noBS CAD native desktop',
        'source_project': 'garden-auger-direct-drive.nbcad',
        'source_project_sha256': hashlib.sha256((ROOT / 'garden-auger-direct-drive.nbcad').read_bytes()).hexdigest(),
        'method': 'Native CAD project loaded into an isolated inspection document; captured desktop views.',
        'inspection_script': 'scripts/adapter_revision_views.py',
        'canonical_project_changed_by_inspection': False,
        'display_only_operations': ['Hide other bodies and all sketches/datums', 'Raise adapter above grid',
                                    'Rotate for rear view', 'Cut axial half-section in temporary document'],
        'composite': 'adapter-revision.png',
        'composite_method': 'Crop and uniformly scale rear/section captures; add captions from verified dimensions.',
        'composite_crop_rectangles': crops,
        'captures_sha256': {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest() for name in captures},
        'composite_sha256': hashlib.sha256((OUT / 'adapter-revision.png').read_bytes()).hexdigest(),
        'physical_interface_scope': 'Manufacturer family depth reference; real INJORA shaft/nose and thread depth require inspection.',
    }
    (OUT / 'provenance.json').write_text(json.dumps(proof, indent=2) + '\n')
    print('Native CAD revision views presented and provenance recorded')


if __name__ == '__main__':
    main()
