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
    consistency=read('cad-design-audit.json')
    assert expected[consistency['source_project']]==consistency['source_project_sha256']
    assert consistency['inspection_geometry']['same_native_mesh_arrays']
    assert consistency['file_identity'].get('bambu_printer_filament_process_values_preserved',
        consistency['file_identity']['bambu_printer_filament_process_config_identical_to_previous'])
    thin=read('thin-housing-verification.json')
    assert expected[thin['source_project']]==thin['source_project_sha256']
    assert thin['inspection_same_native_mesh_arrays']
    assert thin['native_nominal_interference']['exact']
    assert not any(p['interfering'] for p in thin['native_nominal_interference']['pairs'])
    expected[thin['test_project']]=thin['test_project_sha256']
    cable=read('cable-route-verification.json')
    assert expected[cable['source_project']]==cable['source_project_sha256']
    expected[cable['inspection_artifact']]=cable['inspection_artifact_sha256']
    assert not cable['temporary_probes_in_production_model']
    assert all(p['interfering'] for p in cable['previous_dead_end_reproduced_by_native_tool']['housing_pairs'])
    for test in cable['native_continuous_swept_bundle_checks']:
        assert test['exact']
        assert any(p['interfering'] for p in test['housing_pairs'])==test.get('expected_rejection',False)
    assert cable['native_4mm_minimum_housing_clearance_mm']>=.99
    captures=read('renders/cable-route-provenance.json')
    assert captures['source_project_sha256']==cable['source_project_sha256']
    assert captures['experiment_project_sha256']==cable['inspection_artifact_sha256']
    expected.update(captures['capture_sha256'])
    printing=read('housing-print-verification.json')
    assert expected[printing['source_project']]==printing['source_project_sha256']
    assert expected[printing['test_project']]==printing['test_project_sha256']
    assert expected[printing['full_project']]==printing['full_project_sha256']
    assert printing['probe_meshes_byte_identical_to_release']
    for test in ('single_half_release','automatic_support_lower_probe'):
        assert printing[test]['support_time_seconds']==0
        assert printing[test]['support_gcode_feature_markers']==0
    housing_slice=read('bambu-slice-verification.json')['plates'][0]
    assert housing_slice['native_support_time_seconds']==0
    assert housing_slice['support_gcode_feature_markers']==0
    for check in consistency['current_flight_envelope']['checks']:
        result=check.get('result',check)
        pairs=[p for p in result.get('pairs',result.get('flight_housing_pairs',[])) if 90 in {p['body_a'],p['body_b']}
               and bool({26,46}&{p['body_a'],p['body_b']})]
        assert result['exact'] and len(pairs)==2
        assert all(not p['interfering'] and p['minimum_clearance_mm']>
                   consistency['current_flight_envelope']['check_target_mm'] for p in pairs)
    # Keep the failed negative control; a report that only records passing
    # common-offset poses would silently lose the relative-alignment finding.
    alignment=read('preprint-review.json')['native_coupled_alignment_checks']
    assert any(p['interfering'] and {p['body_a'],p['body_b']}=={15,216}
               for p in alignment['independent_offset_negative_control']['result']['pairs'])
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
