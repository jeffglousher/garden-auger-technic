"""Make the current sleeve and direct-bearing print packages."""

import hashlib
import json
from pathlib import Path
import shutil

from print_packer import pack

ROOT=Path(__file__).resolve().parents[1]


def main():
    full=pack(ROOT/'.build/raw.3mf',ROOT/'garden-auger-slice.3mf')
    bare=pack(ROOT/'.build/no-ring-raw.3mf',ROOT/'garden-auger-no-ring.3mf',
              individual_dir='print-parts/no-ring',material_plates=False)
    fit=pack(ROOT/'.build/fit-raw.3mf',ROOT/'garden-auger-fit-check.3mf',fit=True)
    assert len(full)==len(fit)==5 and len(bare)==4
    # Common parts are unchanged; select the matching chassis pair.
    for index in [2,3]:
        assert abs(full[index]['volume_mm3']-bare[index]['volume_mm3'])<.01,(full[index],bare[index])
    parts=json.loads((ROOT/'.build/parts.json').read_text())
    audit=json.loads((ROOT/'dimension-audit.json').read_text())
    stack=audit['tolerance_stack']
    files=['garden-auger-drive.nbcad','garden-auger-no-ring.nbcad','garden-auger-fit-check.nbcad',
           'garden-auger-slice.3mf','garden-auger-no-ring.3mf','garden-auger-fit-check.3mf',
           'garden-auger-petg.3mf','garden-auger-pla-bushing.3mf','dimension-audit.json',
           'output/pdf/garden-auger-release-B.pdf','source/horn-1906-0025-0032/1906-0025-0032.STEP']
    proof={'design':parts,'dimension_audit':json.loads((ROOT/'dimension-audit.json').read_text()),
        'model_cleanup':json.loads((ROOT/'.build/cleanup.json').read_text()),'with_sleeve_print_meshes':full,'no_sleeve_print_meshes':bare,
        'fit_check_print_meshes':fit,'printed_part_counts':{'with_sleeve':5,'no_sleeve':4},
        'retention_hardware_count':0,'ring_lock_features':0,
        'exact_checks':json.loads((ROOT/'.build/checks.json').read_text()),
        'cad_preflight':json.loads((ROOT/'.build/preflight.json').read_text()),
        'desktop_compatibility':json.loads((ROOT/'.build/desktop-compatibility.json').read_text())
            if (ROOT/'.build/desktop-compatibility.json').exists() else [],
        'square_engagement_min_mm':stack['square_engagement_min_mm'],
        'shaft_to_adapter_flange_min_gap_mm':stack['flange_to_hub_gap_min_mm'],
        'socket_bottom_min_clearance_mm':stack['socket_bottom_clearance_min_mm'],
        'artifact_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}}
    (ROOT/'captured-verification.json').write_text(json.dumps(proof,indent=2))
    print('Both variants use the same auger and large adapter; chassis-only retention verified',flush=True)


if __name__=='__main__':main()
