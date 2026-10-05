"""Native CAD helpers and structural baseline preparation.

Uses the installed noBS CAD kernel through its documented stdio operations.
The previous editable project is retained as the construction baseline.
"""

from __future__ import annotations

import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'source/auger-construction.nbcad'


def profile(sketch: dict, points: list[tuple[float, float]], arcs: dict | None = None):
    """Replace a closed sketch loop, retaining its editable native feature."""
    arcs = arcs or {}
    entities = [[i + 1, {'type': 'point', 'position': {'x': x, 'y': y}}]
                for i, (x, y) in enumerate(points)]
    n = len(points)
    for i in range(n):
        entity = {'type': 'line', 'start': i + 1, 'end': (i + 1) % n + 1}
        if i in arcs:
            center, radius, start, end = arcs[i]
            entity = {'type': 'arc', 'center': {'x': center[0], 'y': center[1]},
                      'radius': radius, 'start_angle': start, 'end_angle': end}
        entities.append([n + i + 1, entity])
    snap = sketch['snapshot']
    snap.update(entities=entities, constraints=[], generated_points=[], fix_targets={},
                dim_params={}, dim_placements={}, dim_modes={}, next_entity=2*n,
                next_constraint=0)
    sketch['entity_id_high_water'] = 2*n
    sketch['profile_identities'] = {'next': 0, 'records': []}


def prepare_baseline():
    with zipfile.ZipFile(BASELINE) as z:
        return json.loads(z.read('model.json'))


class Builder:
    def __init__(self, client):
        self.client = client

    def call(self, operation_name, **arguments):
        return self.client.call(operation_name, arguments)

    def poly(self, name, points, plane='yz'):
        self.call('sketch_begin', name=name, plane={'type':'origin_plane', 'plane':plane})
        self.call('sketch_set_grid_snap', enabled=False)
        for p, q in zip(points, points[1:] + points[:1]):
            self.client.call('sketch_add_line', {'from':{'x':p[0],'y':p[1]}, 'to_raw':{'x':q[0],'y':q[1]},'ctrl_held':True})
        self.call('sketch_finish')

    def revolve(self, name, points, operation, targets):
        previous_ids = {b['id'] for b in self.call('solid_scene')['bodies']}
        self.poly(name, points)
        r = self.call('solid_revolve', sketch_name=name, profile_indices=[0],
            axis_origin={'x':0,'y':0}, axis_direction={'x':1,'y':0}, angle_deg=360,
            flip=False, operation=operation, target_body_ids=targets)
        scene = self.call('solid_scene')
        assert not scene['errors'], scene['errors']
        if operation == 'new_body':
            created = [b['id'] for b in scene['bodies'] if b['id'] not in previous_ids]
            assert len(created) == 1, (created, r['document']['features'][-3:])
            r['created_body_id'] = created[0]
        print(name, 'OK', flush=True)
        return r

    def box(self, name, bounds, operation, targets):
        previous_ids = {b['id'] for b in self.call('solid_scene')['bodies']}
        x0,y0,x1,y1,z0,z1 = bounds
        self.call('sketch_begin', name=name, plane={'type':'origin_plane','plane':'xy'})
        self.call('sketch_set_grid_snap', enabled=False)
        self.call('sketch_add_rectangle_locked', mode='two_point',
            anchor={'x':x0,'y':y0},corner_hint={'x':x1,'y':y1},
            width_mm=x1-x0,height_mm=y1-y0,ctrl_held=True)
        self.call('sketch_finish')
        # A box whose lower face is above/below the sketch plane uses a native
        # extrude plus move, so all manufacturing geometry remains editable.
        r = self.call('solid_extrude', sketch_name=name, profile_indices=[0],
            operation='new_body', extent={'type':'distance','distance':z1-z0},
            taper_angle_deg=0,flip=False,target_body_ids=[])
        scene = self.call('solid_scene')
        body = next(b['id'] for b in scene['bodies'] if b['id'] not in previous_ids)
        if z0:
            self.call('solid_move_copy',body_ids=[body],translation={'x':0,'y':0,'z':z0},
                pivot={'x':0,'y':0,'z':0},copy=False)
        for target in targets:
            self.call('solid_combine',target_body_id=target,tool_body_ids=[body],
                operation=operation,keep_tools=target!=targets[-1])
        print(name, 'OK', flush=True)



def save_project(client, target):
    result = client.call('cad_project_model')
    raw = result if isinstance(result,str) else json.dumps(result)
    model = json.loads(raw)
    if 'model_json' in model:
        raw = model['model_json']
        model = json.loads(raw)
    with zipfile.ZipFile(BASELINE) as z:
        manifest = json.loads(z.read('manifest.json'))
    manifest['model_schema_version'] = model['schema_version']
    manifest['saved_at'] = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json', json.dumps(manifest))
        z.writestr('model.json', raw)
    return model
