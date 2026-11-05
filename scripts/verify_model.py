"""Reopen the named Limo model and check bounds, names and assembly interference."""
import argparse
import json
from pathlib import Path
import re
import zipfile
from cad_client import CadClient

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, help='Optional path to Limo CAD.')
    args = parser.parse_args()
    with zipfile.ZipFile(ROOT/'garden-auger.limo') as z:
        model = json.loads(z.read('model.json'))
    reference = json.loads((ROOT/'docs/validation.json').read_text())
    with CadClient(executable=args.executable) as c:
        c.call('cad_load_project_model', {'model_json': json.dumps(model)})
        document = c.call('cad_document')
        assert len(document['features']) == reference['model']['feature_count']
        assert not any(re.fullmatch(r'(Sketch|Extrude|Revolve|Plane|Fillet|Chamfer|Combine|SplitBody|MoveCopy)\d+', f['name']) for f in document['features'])
        scene = c.call('solid_scene')
        assert not scene['errors'], scene['errors']
        assert {b['id'] for b in scene['bodies']} == {int(k) for k in reference['model']['bounds_mm']}
        for body in scene['bodies']:
            p = body['mesh']['positions']
            bounds = [[min(p[a::3]) for a in range(3)], [max(p[a::3]) for a in range(3)]]
            expected = reference['model']['bounds_mm'][str(body['id'])]
            assert all(abs(v-e) < 1e-5 for row, ref in zip(bounds, expected) for v, e in zip(row, ref)), body['id']
        check = c.call('assembly_interference_check', {'occurrence_ids': [3, 6, 7, 8, 14, 16], 'clearance_threshold_mm': 2})
        assert check['exact'] and not any(p['interfering'] for p in check['pairs']), check
    print('PASS: named model reopens, seven body bounds match, exact nominal assembly has no interference.')


if __name__ == '__main__':
    main()
