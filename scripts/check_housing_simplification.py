"""Repeat the historical history-only comparison, before the nesting revision."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

from cad_client import CadClient
from housing_simplification import housing_counts, verify_housing

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '1bbea83dbba876a7f3629b148710857aaf4017f0'
REFACTORED = '50f789bd5b35e472b28f56a7ee5f9c3b94a52469'


def model(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return json.loads(archive.read('model.json'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-commit', default=BASELINE)
    parser.add_argument('--project-commit', default=REFACTORED)
    args = parser.parse_args()
    name = 'garden-auger-direct-drive.nbcad'
    previous = subprocess.check_output(['git', 'show', f'{args.reference_commit}:{name}'], cwd=ROOT)
    current = subprocess.check_output(['git', 'show', f'{args.project_commit}:{name}'], cwd=ROOT)
    before, after = model(previous), model(current)
    with CadClient() as client:
        checks = verify_housing(client, before, after)
        preflight = client.call('solid_export_preflight')
        assert preflight['ok'] and not preflight['timeline_errors'], preflight
    prints = [ROOT / 'garden-auger-bambu-latest.3mf', ROOT / 'garden-auger-direct-drive.3mf',
              *sorted((ROOT / 'print-parts/direct-drive').glob('*.stl'))]
    retained = {}
    for path in prints:
        relative = path.relative_to(ROOT).as_posix()
        old = subprocess.check_output(['git', 'show', f'{args.reference_commit}:{relative}'], cwd=ROOT)
        compared = subprocess.check_output(['git', 'show', f'{args.project_commit}:{relative}'], cwd=ROOT)
        assert old == compared, f'Print artifact changed: {relative}'
        retained[relative] = hashlib.sha256(old).hexdigest()
    report = {'reference_commit': args.reference_commit,
        'compared_project_commit': args.project_commit,
        'scope': 'Historical history-only refactor; the later nesting revision intentionally changes housing solids.',
        'reference_project_sha256': hashlib.sha256(previous).hexdigest(),
        'current_project_sha256': hashlib.sha256(current).hexdigest(),
        'housing_before': housing_counts(before), 'housing_after': housing_counts(after),
        'whole_project_history_before': len(before['document']['history']['features']),
        'whole_project_history_after': len(after['document']['history']['features']),
        'geometry_verification': checks, 'preflight': preflight,
        'existing_print_artifacts_byte_identical': True, 'retained_print_artifact_sha256': retained}
    (ROOT / 'housing-simplification-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('housing_before', 'housing_after',
        'existing_print_artifacts_byte_identical')}), flush=True)


if __name__ == '__main__':
    main()
