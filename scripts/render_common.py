"""Show every print part and the actual slide-on sleeve assembly meshes."""
import json
import math
from pathlib import Path
import sys
import tempfile
from PIL import Image, ImageDraw, ImageFont
from raster_render import render
ROOT = Path(__file__).resolve().parents[1]

def triangles(body, pose=None):
    mesh = body['mesh']
    vertices = [tuple(mesh['positions'][i:i + 3]) for i in range(0, len(mesh['positions']), 3)]
    if pose:
        vertices = [pose(p) for p in vertices]
    return [tuple((vertices[i] for i in mesh['indices'][k:k + 3])) for k in range(0, len(mesh['indices']), 3)]

def camera(meshes, size, margin=30, direction=(1.2, -1.7, 1.2)):
    points = [p for _, tris in meshes for tri in tris for p in tri]
    bounds = [(min((p[k] for p in points)), max((p[k] for p in points))) for k in range(3)]
    target = tuple(((a + b) / 2 for a, b in bounds))
    span = max((b - a for a, b in bounds))
    eye = tuple((target[k] + direction[k] * max(span, 10) * 2 for k in range(3)))

    def unit(v):
        length = math.sqrt(sum((n * n for n in v)))
        return tuple((n / length for n in v))
    forward = unit(tuple((target[k] - eye[k] for k in range(3))))
    right = unit((forward[1], -forward[0], 0))
    up = (right[1] * forward[2] - right[2] * forward[1], right[2] * forward[0] - right[0] * forward[2], right[0] * forward[1] - right[1] * forward[0])

    def project(p):
        offset = tuple((p[k] - eye[k] for k in range(3)))
        depth = sum((offset[k] * forward[k] for k in range(3)))
        return (sum((offset[k] * right[k] for k in range(3))) / depth, sum((offset[k] * up[k] for k in range(3))) / depth)
    projected = [project(p) for p in points]
    scale = min((size[0] / 2 - margin) / max((abs(p[0]) for p in projected)), (size[1] / 2 - margin) / max((abs(p[1]) for p in projected)))
    return (eye, target, scale)

def framed(meshes, size, path, margin=30, direction=(1.2, -1.7, 1.2)):
    eye, target, scale = camera(meshes, size, margin, direction)
    render(meshes, eye=eye, target=target, up=(0, 0, 1), size=size, path=path, scale=scale)

def shifted(mesh, offset):
    color, tris = mesh
    return (color, [tuple((tuple((p[k] + offset[k] for k in range(3))) for p in tri)) for tri in tris])

def font(size, bold=False):
    return ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf' if bold else 'C:/Windows/Fonts/segoeui.ttf', size)

def banner(path, title, subtitle):
    source = Image.open(path).convert('RGB')
    out = Image.new('RGB', (source.width, source.height + 110), (24, 28, 34))
    out.paste(source, (0, 110))
    d = ImageDraw.Draw(out)
    d.text((32, 18), title, font=font(30, True), fill=(243, 247, 250))
    d.text((32, 63), subtitle, font=font(19), fill=(175, 188, 202))
    out.save(path)

def parts_sheet(meshes, parts, path, captured=False):
    direct=parts.get('direct_drive',False)
    sheet = Image.new('RGB', (1600, 1600), (17, 21, 27))
    d = ImageDraw.Draw(sheet)
    d.text((36, 24), 'Garden auger | All parts', font=font(39, True), fill=(242, 246, 250))
    d.text((36, 80), '5 printed parts: PLA wear sleeve + 4 PETG parts', font=font(25), fill=(175, 190, 204))
    cards = [((30, 130, 755, 405), '1  Upper cover + handle', 'PETG', [(meshes[26][0], [tuple(((-p[0], p[1], -p[2]) for p in tri)) for tri in meshes[26][1]])], (1.2, -1.7, 1.2)), ((815, 130, 755, 405), '2  Lower housing + handle', 'PETG', [meshes[46]], (1.2, -1.7, 1.2)), ((30, 555, 1540, 280), '3  One-piece auger', 'PETG', [meshes[15], meshes[90]], (1.8, 0.1, 0.65)), ((30, 855, 500, 345), '4  Plain loose sleeve', 'PLA', [meshes[parts['sleeve']]], (1.3, 1.8, 1.2)), ((550, 855, 500, 345), '5  Large square adapter', 'PETG', [meshes[216]], (1.2, -1.7, 1.2)), ((1070, 855, 500, 345), 'Servo', 'PURCHASED', [meshes[1]], (1.2, -1.7, 1.2))]
    with tempfile.TemporaryDirectory() as folder:
        for i, (box, title, material, geometry, direction) in enumerate(cards):
            x, y, w, h = box
            d.rounded_rectangle((x, y, x + w, y + h), radius=15, fill=(24, 28, 34), outline=(44, 53, 64), width=2)
            part = Path(folder) / f'{i}.png'
            framed(geometry, (w - 28, h - 92), part, margin=22, direction=direction)
            sheet.paste(Image.open(part), (x + 14, y + 78))
            d.text((x + 20, y + 14), title, font=font(25, True), fill=(238, 244, 249))
            accent = (70, 192, 178) if material == 'PLA' else (229, 174, 60) if material == 'PETG' else (168, 188, 212)
            d.text((x + 20, y + 49), material, font=font(18, True), fill=accent)
    d.rounded_rectangle((550, 1220, 1570, 1485), radius=15, fill=(24, 28, 34), outline=(44, 53, 64), width=2)
    d.rounded_rectangle((30, 1220, 530, 1485), radius=15, fill=(24, 28, 34), outline=(44, 53, 64), width=2)
    d.text((50, 1240), 'Chassis-only capture', font=font(27, True), fill=(238, 244, 249))
    for i, text in enumerate(['Integral auger thrust shoulder', 'No ring lock or retaining clip', '28 mm hub / 14 mm square',
                              'Round press fit + square drive' if direct else '4-part ring-free variant available']):
        d.text((50, 1290 + i * 39), text, font=font(21), fill=(186, 200, 215))
    d.text((575, 1240), 'Purchased hardware', font=font(27, True), fill=(238, 244, 249))
    hardware=(['INJORA INJS035-360 servo', 'One factory-compatible M3 center screw',
               '2 x M3 x 12 front / 2 x M3 x 18 rear', '4 x ruthex RX-M3x5.7 brass inserts'] if direct else
              ['Metal 25T horn: goBILDA 1906-0025-0032', '4 x M4 x 6 horn screws + M3 x 6 center screw',
               '2 x M3 x 12 front / 2 x M3 x 18 rear', '4 x ruthex RX-M3x5.7 brass inserts'])
    for i, text in enumerate(hardware):
        d.text((575, 1290 + i * 39), text, font=font(21), fill=(186, 200, 215))
    if parts.get('horn') in meshes:
        with tempfile.TemporaryDirectory() as folder:
            thumb=Path(folder)/'horn.png'
            framed([meshes[parts['horn']]],(260,180),thumb,margin=20)
            sheet.paste(Image.open(thumb),(1290,1268))
        d.text((1300, 1452), 'Metal 25T horn', font=font(18,True), fill=(186,200,215))
    assembly=('Assembly: fit adapter to servo + center screw -> sleeve + auger -> close clamshell' if direct else
              'Assembly: slide sleeve on -> fit horn / servo -> drop into chassis -> close cover')
    d.text((36, 1522), assembly, font=font(23, True), fill=(230, 237, 244))
    d.text((36, 1560), 'Parts shown at different scales. The plain PLA sleeve is loose; chassis shoulders retain the auger.', font=font(18), fill=(153, 171, 189))
    sheet.save(path)
