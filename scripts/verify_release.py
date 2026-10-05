"""Check current release hashes, archive integrity and local documentation links.

Read-only; no CAD rebuild, slicer launch or printer commands.
"""

import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT/name).read_text(encoding='utf-8'))


def checked_path(name):
    path=(ROOT/name).resolve()
    assert path.is_relative_to(ROOT.resolve()), f'Path leaves repository: {name}'
    assert path.is_file(), f'Missing release file: {name}'
    return path


def main():
    expected=dict(read('direct-drive-verification.json')['artifact_sha256'])
    nesting=read('housing-nesting-verification.json')
    expected.update(nesting['updated_housing_stl_sha256'])
    expected.update(nesting['unchanged_other_stl_sha256'])
    bambu=read('bambu-latest-verification.json')
    expected[bambu['project']]=bambu['sha256']
    native_review=read('cad-tool-validation.json')
    assert expected[native_review['source_project']]==native_review['source_project_sha256']
    expected.update(native_review['artifact_sha256'])
    for report in ('adapter-housing-verification.json','housing-nesting-verification.json',
                   'preprint-review.json','servo-fit-verification.json','bambu-slice-verification.json'):
        proof=read(report)
        assert expected[proof['source_project']]==proof['source_project_sha256'], report
    for report in ('renders/housing-preprint-provenance.json',
                   'renders/clamshell-nested-provenance.json',
                   'renders/bambu-print-layout-provenance.json'):
        proof=read(report)
        assert expected[proof['source_project']]==proof['source_project_sha256'],report
        checked_path(f"renders/{proof['image']}")
    for name,proof in read('source/references/provenance.json').items():
        expected[f'source/references/{name}']=proof['sha256']
    captures=read('renders/cad-depth/provenance.json')
    expected.update({f'renders/cad-depth/{name}':digest
                     for name,digest in captures['captures_sha256'].items()})
    expected[f"renders/cad-depth/{captures['composite']}"]=captures['composite_sha256']
    for name,digest in expected.items():
        assert hashlib.sha256(checked_path(name).read_bytes()).hexdigest()==digest, f'Hash mismatch: {name}'
    archives=0
    for name in expected:
        if Path(name).suffix.lower() in ('.nbcad','.limo','.3mf'):
            with zipfile.ZipFile(checked_path(name)) as archive:
                assert archive.testzip() is None, name
                if Path(name).suffix.lower() in ('.nbcad','.limo'):
                    assert 'model.json' in archive.namelist(), name
                else:
                    assert '3D/3dmodel.model' in archive.namelist(), name
            archives+=1
    links=0
    for document in [ROOT/'README.md',*(ROOT/'docs').glob('*.md')]:
        for target in re.findall(r'\]\(([^)]+)\)',document.read_text(encoding='utf-8')):
            target=target.split('#',1)[0].strip('<>')
            if not target or re.match(r'^[a-zA-Z]+:',target):continue
            assert (document.parent/target).exists(), f'Broken local link: {document.name}: {target}'
            links+=1
    with zipfile.ZipFile(ROOT/'garden-auger-direct-drive.nbcad') as archive:
        model=json.loads(archive.read('model.json'))
    features=model['document']['history']['features']
    assert len(features)==read('preprint-review.json')['current_feature_count']
    assert all(not f['suppressed'] and f['status']['state']=='ok' for f in features)
    assert read('direct-drive-verification.json')['shaft_reference_only']['dimensioned_tip_to_case_stack_user_confirmed']
    assert read('bambu-slice-verification.json')['all_four_plates_have_gcode']
    assert read('servo-fit-verification.json')['old_reference_produced_false_clearance_pass']
    print(json.dumps({'verified_file_hashes':len(expected),'intact_release_archives':archives,
                      'valid_local_documentation_links':links,'active_cad_features':len(features),
                      'bambu_project_sha256':bambu['sha256']},indent=2))


if __name__=='__main__':main()
