"""Place the current five solids on four Bambu X2D plates grouped by model filament.

Keep the saved Bambu filament and process profiles. Refresh geometry from the
canonical direct-drive export, then verify it before packaging.
Run with: uv run --no-project --with numpy --with trimesh python scripts/prepare_bambu_latest.py
Use --verify-only after saving the project in Bambu Studio.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import trimesh
from print_packer import component_count

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "garden-auger-bambu-latest.3mf"
CANONICAL = ROOT / "garden-auger-direct-drive.3mf"
CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PRODUCTION = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
ET.register_namespace("", CORE)
ET.register_namespace("p", PRODUCTION)
I = np.eye(3)
UPPER = np.diag([-1., 1., -1.])
UPRIGHT = np.array([[1., 0., 0.], [0., 0., 1.], [0., -1., 0.]])
# Bambu uses ceil(sqrt(plate count)) columns, a 20% bed gap, and negative Y rows.
# See src/slic3r/GUI/PartPlate.{cpp,hpp} in the upstream BambuStudio repository.
PLATES = [
    ("PETG - Housing halves", [
        ("PETG - Housing upper", UPPER, (28., 24.)),
        ("PETG - Housing lower", I, (28., 136.)),
    ]),
    ("PETG - One-piece auger", [("PETG - One-piece auger", I, (111., 55.))]),
    ("PETG - Square adapter", [("PETG - Square adapter", UPRIGHT, (114., 114.))]),
    ("PLA - Wear sleeve", [("PLA - Full wear sleeve", UPRIGHT, (110., 110.))]),
]
EXPECTED_FILAMENT = {
    "PETG - Housing upper": 1, "PETG - Housing lower": 1,
    "PETG - One-piece auger": 2, "PETG - Square adapter": 3,
    "PLA - Full wear sleeve": 4,
}


def metadata(node):
    return {m.get("key"): m.get("value") for m in node.findall("metadata") if m.get("key")}


def mesh_arrays(node):
    vertices = np.array([[float(v.get(k)) for k in ("x", "y", "z")]
                         for v in node.findall(".//{*}vertex")])
    faces = np.array([[int(t.get(k)) for k in ("v1", "v2", "v3")]
                      for t in node.findall(".//{*}triangle")])
    return vertices, faces


def project_parts(entries):
    model = ET.fromstring(entries["3D/3dmodel.model"])
    config = ET.fromstring(entries["Metadata/model_settings.config"])
    objects = {o.get("id"): o for o in model.findall("{*}resources/{*}object")}
    parts = {}
    for obj in config.findall("object"):
        info = metadata(obj)
        component = objects[obj.get("id")].find("{*}components/{*}component")
        mesh_path = component.get(f"{{{PRODUCTION}}}path").lstrip("/")
        vertices, faces = mesh_arrays(ET.fromstring(entries[mesh_path]))
        parts[info["name"]] = {
            "object_id": obj.get("id"), "extruder": int(info["extruder"]),
            "mesh_path": mesh_path, "vertices": vertices, "faces": faces,
        }
    return model, config, parts


def read_zip(path):
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None, path
        return {n: z.read(n) for n in z.namelist()}


def geometry_checks(parts):
    canonical = ET.fromstring(read_zip(CANONICAL)["3D/3dmodel.model"])
    expected = {o.get("name"): mesh_arrays(o) for o in canonical.findall("{*}resources/{*}object")}
    assert set(parts) == set(expected) == set(EXPECTED_FILAMENT)
    report = []
    for name, part in parts.items():
        vertices, faces = part["vertices"], part["faces"]
        ref_vertices, ref_faces = expected[name]
        assert np.array_equal(faces, ref_faces), (name, "triangle topology changed")
        # Bambu recenters meshes; compare shape after removing that translation.
        center = (vertices.min(axis=0) + vertices.max(axis=0)) / 2
        ref_center = (ref_vertices.min(axis=0) + ref_vertices.max(axis=0)) / 2
        delta = float(np.max(np.abs((vertices-center) - (ref_vertices-ref_center))))
        assert delta < 0.0001, (name, "geometry changed", delta)
        mesh = trimesh.Trimesh(vertices, faces, process=False)
        assert mesh.is_watertight and mesh.is_volume, name
        assert component_count(mesh) == 1, name
        assert part["extruder"] == EXPECTED_FILAMENT[name]
        report.append({"name": name, "vertices": len(vertices), "triangles": len(faces),
                       "closed_connected_solid": True, "maximum_shape_difference_mm": delta})
    return report


def transform_text(rotation, translation):
    return " ".join(f"{x:.12g}" for x in [*rotation.T.flatten(), *translation])


def add_metadata(parent, key, value):
    ET.SubElement(parent, "metadata", key=key, value=str(value))


def refresh_geometry(entries, config, parts):
    canonical = ET.fromstring(read_zip(CANONICAL)["3D/3dmodel.model"])
    expected = {o.get("name"): mesh_arrays(o) for o in canonical.findall("{*}resources/{*}object")}
    assert set(parts) == set(expected) == set(EXPECTED_FILAMENT)
    for name, part in parts.items():
        vertices, faces = expected[name]
        center = (vertices.min(axis=0) + vertices.max(axis=0)) / 2
        vertices = vertices - center
        model = ET.fromstring(entries[part["mesh_path"]])
        mesh = model.find(".//{*}mesh")
        mesh.clear()
        vertex_node = ET.SubElement(mesh, f"{{{CORE}}}vertices")
        triangle_node = ET.SubElement(mesh, f"{{{CORE}}}triangles")
        for point in vertices:
            ET.SubElement(vertex_node, f"{{{CORE}}}vertex",
                          dict(zip(("x", "y", "z"), (f"{x:.12g}" for x in point))))
        for face in faces:
            ET.SubElement(triangle_node, f"{{{CORE}}}triangle",
                          dict(zip(("v1", "v2", "v3"), (str(int(x)) for x in face))))
        entries[part["mesh_path"]] = ET.tostring(model, encoding="utf-8", xml_declaration=True)
        part.update(vertices=vertices, faces=faces)
        obj = next(o for o in config.findall("object") if o.get("id") == part["object_id"])
        obj.find("metadata[@face_count]").set("face_count", str(len(faces)))
        subpart = obj.find("part")
        subpart.find("mesh_stat").set("face_count", str(len(faces)))
        for axis, value in zip(("x", "y", "z"), center):
            subpart.find(f"metadata[@key='source_offset_{axis}']").set("value", f"{value:.12g}")
        if name == "PETG - Square adapter":
            for key, value in {"wall_loops": 6, "sparse_infill_density": "100%",
                               "sparse_infill_pattern": "zig-zag"}.items():
                node = obj.find(f"metadata[@key='{key}']")
                if node is None:
                    add_metadata(obj, key, value)
                else:
                    node.set("value", str(value))


def build():
    if not TARGET.exists():
        raise FileNotFoundError('Restore garden-auger-bambu-latest.3mf from Git before rebuilding; it holds the saved printer, filament and process profiles.')
    entries = read_zip(TARGET)
    model, config, parts = project_parts(entries)
    refresh_geometry(entries, config, parts)
    geometry_checks(parts)
    settings = json.loads(entries["Metadata/project_settings.config"])
    assert settings["filament_type"] == ["PETG", "PETG", "PETG", "PLA"]
    settings["enable_prime_tower"] = "0"
    # The housing halves share a bed. Complete each layer across both halves
    # instead of sweeping the gantry past one completed, tall part.
    settings["print_sequence"] = "by layer"
    # Every plate contains one filament, using the primary nozzle.
    settings["filament_map"] = ["1"] * 4
    settings["filament_nozzle_map"] = ["0"] * 4
    for old in config.findall("plate"):
        config.remove(old)
    build_node = model.find("{*}build")
    items = {i.get("objectid"): i for i in build_node.findall("{*}item")}
    # A saved project may contain extra instances of a part. This canonical
    # five-part package has exactly one print instance of each current solid.
    for item in list(build_node):
        build_node.remove(item)
    for part in parts.values():
        build_node.append(items[part["object_id"]])
    old_assemble = config.find("assemble")
    if old_assemble is not None:
        config.remove(old_assemble)
    for index, (label, definitions) in enumerate(PLATES):
        origin = np.array([(index % 2)*307.2, -(index // 2)*307.2, 0.])
        plate = ET.Element("plate")
        for key, value in {"plater_id": index+1, "plater_name": label, "locked": "false",
                           "filament_map_mode": "Auto For Flush", "filament_maps": "1 1 1 1",
                           "filament_volume_maps": "0 0 0 0"}.items():
            add_metadata(plate, key, value)
        for name, rotation, xy_min in definitions:
            part = parts[name]
            rotated = part["vertices"] @ rotation.T
            translation = origin + np.array([*xy_min, 0.]) - rotated.min(axis=0)
            items[part["object_id"]].set("transform", transform_text(rotation, translation))
            items[part["object_id"]].set("printable", "1")
            instance = ET.SubElement(plate, "model_instance")
            for key, value in {"object_id": part["object_id"], "instance_id": 0,
                               "identify_id": 100+int(part["object_id"])}.items():
                add_metadata(instance, key, value)
        assemble_node = config.find("assemble")
        config.insert(list(config).index(assemble_node) if assemble_node is not None else len(config), plate)
    entries["3D/3dmodel.model"] = ET.tostring(model, encoding="utf-8", xml_declaration=True)
    entries["Metadata/model_settings.config"] = ET.tostring(config, encoding="utf-8", xml_declaration=True)
    entries["Metadata/project_settings.config"] = json.dumps(settings, indent=4).encode()
    # Bambu Studio regenerates plate images and slice data when saving the new project.
    entries = {name: data for name, data in entries.items()
               if not re.match(r"Metadata/(?:plate(?:_no_light)?_|top_|pick_)\d+\.", name)
               and not name.endswith(".gcode")}
    entries["Metadata/filament_sequence.json"] = json.dumps({
        f"plate_{i+1}": {"nozzle_sequence": [], "optimal_assignment": [], "sequence": []}
        for i in range(len(PLATES))}).encode()
    old_slice = ET.fromstring(entries["Metadata/slice_info.config"])
    for child in list(old_slice):
        if child.tag != "header":
            old_slice.remove(child)
    entries["Metadata/slice_info.config"] = ET.tostring(old_slice, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(TARGET, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)


def verify():
    entries = read_zip(TARGET)
    model, config, parts = project_parts(entries)
    geometry = geometry_checks(parts)
    adapter_config = next(o for o in config.findall("object")
                          if metadata(o).get("name") == "PETG - Square adapter")
    strength = metadata(adapter_config)
    assert strength["wall_loops"] == "6" and strength["sparse_infill_density"] == "100%"
    assert strength["sparse_infill_pattern"] == "zig-zag"
    settings = json.loads(entries["Metadata/project_settings.config"])
    assert settings["filament_type"] == ["PETG", "PETG", "PETG", "PLA"]
    assert settings["enable_prime_tower"] == "0"
    assert settings["print_sequence"] == "by layer"
    items = {i.get("objectid"): i for i in model.findall("{*}build/{*}item")}
    assert len(model.findall("{*}build/{*}item")) == len(items) == 5
    by_id = {p["object_id"]: (name, p) for name, p in parts.items()}
    assigned = []
    plates = config.findall("plate")
    assert len(plates) == 4
    plate_checks = []
    for index, plate in enumerate(plates):
        origin = np.array([(index % 2)*307.2, -(index // 2)*307.2, 0.])
        ids = [metadata(instance)["object_id"] for instance in plate.findall("model_instance")]
        assert ids
        filament_ids, boxes, names = set(), [], []
        for obj_id in ids:
            name, part = by_id[obj_id]
            transform = np.array([float(s) for s in items[obj_id].get("transform").split()])
            vertices = part["vertices"] @ transform[:9].reshape(3,3) + transform[9:] - origin
            box = np.array([vertices.min(axis=0), vertices.max(axis=0)])
            assert box[0,0] >= 20.5-0.001 and box[0,1] >= 10-0.001
            assert np.all(box[1,:2] <= 246.001) and abs(box[0,2]) < 0.001
            assert box[1,2] < 256
            assert items[obj_id].get("printable") == "1"
            names.append(name); boxes.append(box); assigned.append(obj_id)
            filament_ids.add(part["extruder"])
        assert len(filament_ids) == 1
        for a in range(len(boxes)):
            for b in range(a+1, len(boxes)):
                assert np.any((boxes[a][1,:2] + 10 <= boxes[b][0,:2]) |
                              (boxes[b][1,:2] + 10 <= boxes[a][0,:2])), "Insufficient brim spacing"
        plate_checks.append({"plate": index+1, "name": metadata(plate)["plater_name"],
                             "parts": names, "filament": next(iter(filament_ids)),
                             "bounds_mm": [box.tolist() for box in boxes]})
    assert len(assigned) == len(set(assigned)) == len(parts) == 5
    proof = json.loads((ROOT/"direct-drive-verification.json").read_text())
    for filename, expected_hash in proof["artifact_sha256"].items():
        assert hashlib.sha256((ROOT/filename).read_bytes()).hexdigest() == expected_hash, filename
    interface_filament = int(settings.get("support_interface_filament", "0"))
    report = {
        "project": TARGET.name, "sha256": hashlib.sha256(TARGET.read_bytes()).hexdigest(),
        "canonical_export": CANONICAL.name, "canonical_artifact_hashes_verified": True,
        "geometry": geometry, "plates": plate_checks,
        "filament_types": settings["filament_type"], "filament_profiles": settings["filament_settings_id"],
        "filament_colors": settings["filament_colour"], "printer": settings["printer_settings_id"],
        "process_profile": settings["print_settings_id"], "prime_tower": False,
        "layer_height_mm": float(settings["layer_height"]),
        "support_settings": {"enabled": settings.get("enable_support") == "1",
                             "type": settings.get("support_type"),
                             "base_filament": int(settings.get("support_filament", "0")),
                             "interface_filament": interface_filament,
                             "interface_material": settings["filament_type"][interface_filament-1] if interface_filament else "same as model",
                             "top_z_distance_mm": float(settings.get("support_top_z_distance", "0")),
                             "scope": "Each plate has one model filament; support interfaces can add another material."},
        "saved_filament_and_process_profiles_preserved": True,
        "layout_overrides": {"print_sequence": "by layer", "prime_tower": False,
                             "primary_nozzle_for_each_single_filament_plate": True},
        "all_five_parts_on_plates_with_one_model_filament": True,
        "adapter_strength_override": {"wall_loops": 6, "infill_density_percent": 100,
                                      "infill_pattern": "zig-zag"},
        "scope": "Geometry and plate-layout verification; physical fit and load qualification remain in README.",
    }
    (ROOT/"bambu-latest-verification.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"project": report["project"], "parts": len(geometry), "plates": len(plates),
                      "canonical_geometry_verified": True, "all_parts_on_bed": True,
                      "sha256": report["sha256"]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if not args.verify_only:
        build()
    verify()
