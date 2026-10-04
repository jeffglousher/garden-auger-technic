"""Load a saved CAD revision through the isolated native geometry engine."""
import io
import json
import zipfile


def native_render_source(client, project_bytes):
    with zipfile.ZipFile(io.BytesIO(project_bytes)) as archive:
        model = json.loads(archive.read('model.json'))
    client.call('cad_load_project_model', {'model_json': json.dumps(model)})
    scene = client.call('solid_scene')
    assert not scene['errors'], scene['errors']
    return model, scene
