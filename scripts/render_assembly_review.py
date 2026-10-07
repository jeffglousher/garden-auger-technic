"""Capture presentation offsets in native CAD; encode the captures as a GIF.

Run against an owned desktop with garden-auger-fit-inspection.limo open:
  uv run --no-project --with pillow python scripts/render_assembly_review.py --session UUID
The review copy preserves mechanical geometry and occurrence placements. The
animated offsets illustrate relationships; they are not a collision study or
qualified assembly procedure. GIF encoding is external to CAD.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import time
import zipfile

from PIL import Image, ImageDraw, ImageFont
from cad_client import CadClient

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'garden-auger-fit-inspection.limo'
REVIEW = ROOT / 'experiments/garden-auger-assembly-review.limo'
BUILD = ROOT / '.build/assembly-review'
BODY_IDS = [1, 15, 26, 46, 90, 216, 221]
EXPLODED = {6: [-45, -60, 130], 8: [0, -35, 55],
            16: [0, 25, 55], 14: [0, 60, 55], 3: [0, 95, 55]}
GUTS = [8, 16, 14, 3]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_model(path):
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read('model.json'))


def font(size):
    return ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', size)


def decorate(path, label):
    # Fixed crop of the observed native viewport. Never redraw CAD geometry.
    native = Image.open(path).convert('RGB').crop((520, 240, 1120, 710))
    out = Image.new('RGB', (600, 566), (27, 31, 38))
    out.paste(native, (0, 52))
    draw = ImageDraw.Draw(out)
    draw.text((16, 7), 'Garden auger | exploded to assembled', font=font(21), fill='#edf1f5')
    draw.text((16, 32), label, font=font(14), fill='#c5d0dd')
    draw.text((16, 524), 'Gold: housing   Orange: auger   Teal: PLA sleeve', font=font(14), fill='#edf1f5')
    draw.text((16, 546), 'Silver: adapter   Blue gray: servo | Native CAD captures', font=font(13), fill='#c5d0dd')
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', required=True)
    parser.add_argument('--frames-per-stage', type=int, default=8)
    args = parser.parse_args()
    assert 3 <= args.frames_per_stage <= 30
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / 'frames').mkdir(exist_ok=True)
    REVIEW.parent.mkdir(exist_ok=True)
    source_hash = digest(SOURCE)
    production_hash = digest(ROOT / 'garden-auger-direct-drive.nbcad')
    before = read_model(SOURCE)
    frames, receipts = [], []

    with CadClient() as client:
        client.call('cad_attach', {'session_id': args.session})
        current = client.call('cad_project_model')
        if isinstance(current, str):
            current = json.loads(current)
        # Reject a different design or a desktop with mechanical edits.
        for key in before:
            if key not in ('views', 'visibility', 'document', 'preferences'):
                assert current[key] == before[key], f'Desktop differs from source: {key}'
        assert current['document']['history'] == before['document']['history']

        def interface(**kwargs):
            result = client.call('cad_interface', {'session_id': args.session, **kwargs})
            assert result.get('status') != 'failed', result.get('error', result)
            if 'status' in result:
                assert result['status'] == 'applied', result
            return result['value'] if isinstance(result.get('value'), dict) else result

        def execute(operation, arguments):
            return interface(action='execute', group='document/appearance',
                             operation=operation, arguments=arguments)

        # Observed empty grid in this desktop layout; clear selection highlights.
        interface(action='viewport', canvas='viewport', gesture='click',
                  point=[300, 600], button='left')
        camera = interface(action='view', view='current', duration_ms=0)['camera']
        camera = {key: camera[key] for key in ('position', 'target', 'up')}

        def offsets(values):
            return [{'occurrence_id': oid, 'translation': vector}
                    for oid, vector in values.items()]

        def upsert(name, values, visible=BODY_IDS):
            execute('upsert_named_view', {'name': name, 'camera': camera,
                    'visible_body_ids': visible, 'occurrence_offsets': offsets(values)})

        def recall(name):
            execute('recall_named_view', {'name': name})

        # Fit the actual exploded solution natively, independent of the camera
        # the user had selected before running this script.
        upsert('Assembly - exploded', EXPLODED)
        recall('Assembly - exploded')
        fitted = interface(action='view', view='isometric', fit=True, duration_ms=0)['camera']
        camera = {key: fitted[key] for key in ('position', 'target', 'up')}

        for name, values, visible in [
            ('Assembly - exploded', EXPLODED, BODY_IDS),
            ('Assembly - open housing', {}, [x for x in BODY_IDS if x != 26]),
            ('Assembly - assembled', {}, BODY_IDS),
        ]:
            upsert(name, values, visible)

        def capture(values, label):
            index = len(frames)
            upsert('__Assembly preview frame', values)
            recall('__Assembly preview frame')
            solution = execute('named_view_solution', {'name': '__Assembly preview frame'})
            assert solution['solved']
            original = {o['id']: o['local_pose'] for o in before['assembly']['component_structure']['occurrences']}
            for pose in solution['occurrence_poses']:
                oid = pose['occurrence_id']
                expected = [a + b for a, b in zip(original[oid]['translation'], values.get(oid, [0, 0, 0]))]
                assert all(abs(a - b) < 1e-8 for a, b in zip(pose['translation'], expected))
            time.sleep(0.22)
            path = BUILD / f'frames/frame-{index:03d}.png'
            receipt = interface(action='capture', path=str(path), overwrite=True)
            assert receipt.get('source') == 'bevy_window', receipt
            receipts.append({'index': index, 'label': label, 'native_capture_sha256': digest(path),
                             'offsets': offsets(values), 'capture_source': receipt['source']})
            frames.append(decorate(path, label))

        values = copy.deepcopy(EXPLODED)
        capture(values, 'Exploded: five printed parts + servo')
        frames[0].save(ROOT / 'renders/cad-assembly-exploded.png')

        def stage(targets, label):
            start = copy.deepcopy(values)
            for index in range(1, args.frames_per_stage + 1):
                t = index / args.frames_per_stage
                t = t * t * (3 - 2 * t)
                for oid, end in targets.items():
                    values[oid] = [a + (b - a) * t for a, b in zip(start[oid], end)]
                capture(values, label)
            print(label, flush=True)

        stage({16: [0, -35, 55]}, 'PLA sleeve slides onto the auger journal')
        stage({14: [0, 95, 55]}, 'Square adapter meets the servo shaft')
        stage({14: [0, -35, 55], 3: [0, -35, 55]}, 'Square adapter engages the auger socket')
        stage({oid: [0, 0, 55] for oid in GUTS}, 'Complete drive aligned above the lower housing')
        stage({oid: [0, 0, 0] for oid in GUTS}, 'Drive and loose sleeve nest in the lower housing')

        # Native interior still, so the mating arrangement remains visible.
        recall('Assembly - open housing')
        time.sleep(0.22)
        path = BUILD / 'open-housing.png'
        receipt = interface(action='capture', path=str(path), overwrite=True)
        assert receipt.get('source') == 'bevy_window'
        decorate(path, 'Assembled drive | upper half hidden').save(ROOT / 'renders/cad-assembly-open.png')

        stage({6: [0, 0, 0]}, 'Upper clamshell closes around the nested components')
        frames[-1].save(ROOT / 'renders/cad-assembly-assembled.png')
        execute('delete_named_view', {'name': '__Assembly preview frame'})
        recall('Assembly - exploded')
        client.call('cad_set_document_name', {'name': 'Garden auger - assembly presentation - not a print layout'})
        interface(action='file', command='save', path=str(REVIEW), overwrite=True)

    after = read_model(REVIEW)
    checked = []
    for key in before:
        if key not in ('views', 'visibility', 'document', 'preferences'):
            assert after[key] == before[key], f'Review changed mechanical model: {key}'
            checked.append(key)
    assert after['document']['history'] == before['document']['history']
    assert digest(SOURCE) == source_hash
    assert digest(ROOT / 'garden-auger-direct-drive.nbcad') == production_hash
    assert len({r['native_capture_sha256'] for r in receipts}) == len(receipts), 'Duplicate/stale captures'
    durations = [100] * len(frames)
    durations[0] = durations[-1] = 1400
    gif = ROOT / 'renders/cad-assembly-animation.gif'
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=durations,
                   loop=0, disposal=2, optimize=False)
    with Image.open(gif) as check:
        assert check.n_frames == len(frames)
        for index in range(check.n_frames):
            check.seek(index)
            check.load()
    report = {
        'source': SOURCE.relative_to(ROOT).as_posix(), 'source_sha256': source_hash,
        'production_sha256': production_hash, 'review': REVIEW.relative_to(ROOT).as_posix(),
        'review_sha256': digest(REVIEW), 'native_capture_source': 'bevy_window',
        'frames': len(frames), 'native_fields_unchanged': checked,
        'feature_history_unchanged': True, 'authored_occurrence_poses_unchanged': True,
        'native_named_view_poses_checked_each_frame': True,
        'source_and_production_files_unchanged': True,
        'gif_encoding': 'Pillow outside CAD; fixed crop and labels, no geometry redraw',
        'limitations': ['Illustrative presentation offsets, not a joint-driven motion study.',
                        'No collision or physical assembly-path qualification claimed.',
                        'Fasteners and flexible cable are not modeled in this presentation.',
                        'Installed cad_interface did not apply requested named-view camera; native camera kept fixed.'],
        'artifact_sha256': {p.relative_to(ROOT).as_posix(): digest(p) for p in [gif,
            ROOT / 'renders/cad-assembly-exploded.png', ROOT / 'renders/cad-assembly-open.png',
            ROOT / 'renders/cad-assembly-assembled.png']},
        'captures': receipts,
    }
    (ROOT / 'assembly-presentation-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'frames': len(frames), 'gif': str(gif), 'review': str(REVIEW),
                      'mechanical_model_unchanged': True}), flush=True)


if __name__ == '__main__':
    main()
