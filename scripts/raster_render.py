"""Small triangle rasterizer for native CAD preview images."""
import math
import struct
import zlib
from pathlib import Path

def normal(tri):
    (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = tri
    nx = (y1 - y0) * (z2 - z0) - (z1 - z0) * (y2 - y0)
    ny = (z1 - z0) * (x2 - x0) - (x1 - x0) * (z2 - z0)
    nz = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return (nx / length, ny / length, nz / length)


def shade(tri, rgb, light):
    n = normal(tri)
    ndot = 0.42 + 0.58 * max(0.0, n[0] * light[0] + n[1] * light[1] + n[2] * light[2])
    return tuple(min(255, int(c * ndot)) for c in rgb)


def render(meshes, eye, target, up, size, path: Path, scale=900.0):
    width, height = size
    fx = target[0] - eye[0]
    fy = target[1] - eye[1]
    fz = target[2] - eye[2]
    fl = math.sqrt(fx * fx + fy * fy + fz * fz)
    fx, fy, fz = fx / fl, fy / fl, fz / fl
    rx = fy * up[2] - fz * up[1]
    ry = fz * up[0] - fx * up[2]
    rz = fx * up[1] - fy * up[0]
    rl = math.sqrt(rx * rx + ry * ry + rz * rz)
    rx, ry, rz = rx / rl, ry / rl, rz / rl
    ux = ry * fz - rz * fy
    uy = rz * fx - rx * fz
    uz = rx * fy - ry * fx

    def project(p):
        dx, dy, dz = p[0] - eye[0], p[1] - eye[1], p[2] - eye[2]
        z = dx * fx + dy * fy + dz * fz
        x = dx * rx + dy * ry + dz * rz
        y = dx * ux + dy * uy + dz * uz
        s = scale / max(z, 1.0)
        return (width / 2 + x * s, height / 2 - y * s, z)

    buf = bytearray([24, 28, 34]) * (width * height)
    depth = [1e9] * (width * height)
    light = (0.45, 0.55, 0.7)
    ll = math.sqrt(sum(c * c for c in light))
    light = tuple(c / ll for c in light)

    for color, tris in meshes:
        for tri in tris:
            pts = [project(v) for v in tri]
            if min(p[2] for p in pts) < 1:
                continue
            rgb = shade(tri, color, light)
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            minx = max(0, int(min(xs)))
            maxx = min(width - 1, int(max(xs)) + 1)
            miny = max(0, int(min(ys)))
            maxy = min(height - 1, int(max(ys)) + 1)
            if minx > maxx or miny > maxy:
                continue
            (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = pts
            denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(denom) < 1e-8:
                continue
            for y in range(miny, maxy + 1):
                for x in range(minx, maxx + 1):
                    w0 = ((y1 - y2) * (x - x2) + (x2 - x1) * (y - y2)) / denom
                    w1 = ((y2 - y0) * (x - x2) + (x0 - x2) * (y - y2)) / denom
                    w2 = 1 - w0 - w1
                    if w0 < -0.001 or w1 < -0.001 or w2 < -0.001:
                        continue
                    z = w0 * z0 + w1 * z1 + w2 * z2
                    idx = y * width + x
                    if z < depth[idx]:
                        depth[idx] = z
                        o = idx * 3
                        buf[o : o + 3] = bytes(rgb)

    raw = b"".join(b"\x00" + bytes(buf[y * width * 3 : (y + 1) * width * 3]) for y in range(height))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)
    print(path, path.stat().st_size)
