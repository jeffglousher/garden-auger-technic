"""Remove inactive construction and set explicit printed-part appearances."""

import copy

PRINT_APPEARANCES = {
    15: ('PETG', 'Auger orange', '#D57E37'),
    90: ('PETG', 'Auger orange', '#D57E37'),
    26: ('PETG', 'Chassis yellow', '#E5AE3C'),
    46: ('PETG', 'Chassis yellow', '#E5AE3C'),
    216: ('PETG', 'Adapter gray', '#BEC3CA'),
}


def set_materials(model, sleeve):
    appearances = dict(PRINT_APPEARANCES)
    if sleeve is not None:
        appearances[sleeve] = ('PLA', 'Wear sleeve teal', '#37AAA1')
    metal_horns={b for d in model['assembly']['component_structure']['definitions']
                 if '1906-0025-0032' in d['name'] for b in d['body_ids']}
    for a in model['body_appearances']:
        if a['body_id'] in appearances:
            material, name, hex_color = appearances[a['body_id']]
            a.update(material_name=material, filament_type=material,
                     color_name=name, brand='Generic', diameter_mm=1.75)
            a['color'] = dict(zip(('r', 'g', 'b', 'a'),
                                 [int(hex_color[i:i+2], 16) for i in (1,3,5)] + [255]))
        elif a['body_id'] == 1:
            a.update(material_name='Purchased servo - reference only',
                     filament_type='OTHER', color_name='Servo blue gray')
        elif a['body_id'] in metal_horns:
            a.update(material_name='Aluminum - clear anodized - purchased',
                     filament_type='OTHER',color_name='Anodized aluminum',brand='goBILDA')
    for o in model['assembly']['component_structure']['occurrences']:
        if o['component_id'] == 14:
            o['name'] = 'Large square servo adapter'


def prune(model):
    """Preserve active operations and their sketch/datum dependencies.

    Geometry equality is checked by the caller after rebuilding this model.
    Never remove active solid operations merely because they look redundant.
    """
    model = copy.deepcopy(model)
    history = model['document']['history']['features']
    removed = {f['id'] for f in history if f.get('suppressed')}
    collections = ['extrudes','revolves','sweeps','lofts','ribs','fillets',
                   'chamfers','holes','body_features']
    for key in collections:
        model[key] = [r for r in model[key] if r['feature_id'] not in removed]
    needed_sketches = set()
    def refs(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if 'sketch_name' in key and isinstance(child, str):
                    needed_sketches.add(child)
                refs(child)
        elif isinstance(value, list):
            for child in value: refs(child)
    for key in collections: refs(model[key])
    sketches = [s for s in model['sketches'] if s['name'] in needed_sketches]
    removed.update(s['feature_id'] for s in model['sketches'] if s not in sketches)
    model['sketches'] = sketches
    needed_datums = {s['plane']['datum_id'] for s in sketches
                     if s['plane']['type'] == 'datum_plane'}
    # All baseline planes reference origin planes; keep this assumption explicit.
    assert all(p['source']['reference']['type'] == 'origin_plane'
               for p in model['datum_planes'])
    datums = [p for p in model['datum_planes'] if p['datum_id'] in needed_datums]
    removed.update(p['feature_id'] for p in model['datum_planes'] if p not in datums)
    model['datum_planes'] = datums
    model['document']['history']['features'] = [f for f in history if f['id'] not in removed]
    if 'rollback_index' in model['document']['history']:
        model['document']['history']['rollback_index'] = len(model['document']['history']['features'])
    visible = model['visibility']
    visible['hidden_sketch_names'] = [s['name'] for s in sketches]
    visible['hidden_datum_plane_ids'] = sorted(needed_datums)
    return model, {'features_before':len(history),
                   'features_after':len(model['document']['history']['features']),
                   'removed_inactive_features':len(removed),
                   'suppressed_features_remaining':0}


def geometry_signature(scene):
    assert not scene['errors'], scene['errors']
    return {b['id']: {k: b['mesh'][k] for k in ('positions','indices')}
            for b in scene['bodies']}


def clean_checked(client, model, sleeve):
    set_materials(model, sleeve)
    before = geometry_signature(client.call('solid_scene'))
    cleaned, report = prune(model)
    client.call('cad_load_project_model', {'model_json':__import__('json').dumps(cleaned)})
    assert geometry_signature(client.call('solid_scene')) == before, 'Cleanup changed geometry'
    report['rebuilt_mesh_geometry_identical'] = True
    return cleaned, report
