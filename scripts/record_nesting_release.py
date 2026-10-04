"""Tie the tested nesting revision to its saved CAD and print artifacts."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = '50f789bd5b35e472b28f56a7ee5f9c3b94a52469'


def main():
    source = ROOT / 'garden-auger-direct-drive.nbcad'
    with zipfile.ZipFile(source) as z:
        assert z.testzip() is None
        model = json.loads(z.read('model.json'))
    prior = subprocess.check_output(['git', 'show', f'{REFERENCE}:{source.name}'], cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(prior)) as z:
        before = json.loads(z.read('model.json'))
    audit = json.loads((ROOT / 'direct-drive-verification.json').read_text())
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    assert source_hash == audit['artifact_sha256'][source.name]
    assert model['schema_version'] == 7
    assert all(not f['suppressed'] and f['status']['state'] == 'ok'
               for f in model['document']['history']['features'])
    assert audit['preflight']['ok'] and not audit['preflight']['timeline_errors']
    assert model['assembly'] == before['assembly']
    assert model['body_appearances'] == before['body_appearances']
    nesting = audit['nested_housing']
    assert nesting['geometry_verification']['other_body_mesh_arrays_identical']
    assert len(nesting['geometry_verification']['sleeve_capture_and_journal_offset_checks']) == 8
    assert len(audit['assembly_checks']) == 7
    retained, changed = {}, {}
    for path in sorted((ROOT / 'print-parts/direct-drive').glob('*.stl')):
        relative = path.relative_to(ROOT).as_posix()
        old = subprocess.check_output(['git', 'show', f'{REFERENCE}:{relative}'], cwd=ROOT)
        same = old == path.read_bytes()
        housing = path.name in ('petg-housing-upper.stl', 'petg-housing-lower.stl')
        assert same != housing, relative
        (changed if housing else retained)[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = {'source_project': source.name, 'source_project_sha256': source_hash,
        'reference_commit': REFERENCE, 'reference_project_sha256': hashlib.sha256(prior).hexdigest(),
        'revision': 'Finished housing cavities simplified for printed nesting',
        'finished_housing_geometry_changed': True, 'nesting': nesting,
        'native_auger_rotation_and_collar_capture_checks': audit['assembly_checks'],
        'desktop_reader_verification': audit['desktop_compatibility'],
        'updated_housing_stl_sha256': changed, 'unchanged_other_stl_sha256': retained,
        'whole_project_history_before': len(before['document']['history']['features']),
        'whole_project_history_after': len(model['document']['history']['features']),
        'print_progress_known': False,
        'compatibility': 'Existing auger, adapter and sleeve fit both housing revisions. Earlier housings remain usable; new housings provide the simpler cavities.'}
    (ROOT / 'housing-nesting-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    audit['housing_geometry_release_verification'] = 'housing-nesting-verification.json'
    (ROOT / 'direct-drive-verification.json').write_text(json.dumps(audit, indent=2) + '\n')
    print('Saved CAD matches verified build; only two housing STLs changed', flush=True)


if __name__ == '__main__':
    main()
