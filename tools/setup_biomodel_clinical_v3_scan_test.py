"""Create a non-destructive Renata usability pair for the clinical V3 panel."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


MODEL_BASE = "BM_AJUSTE_SCAN_BASE_v3"
SCAN_SOURCE = "Renata_Acometido"
MODEL_TEST = "BM_SCAN_RENATA_v3"
SCAN_TEST = "SCAN_RENATA_REFERENCIA_v3"
COLLECTION = "BM_TESTE_USABILIDADE_V3"


def _evaluated_local_vertices(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        return [vertex.co.copy() for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def _centroid(points):
    result = Vector((0.0, 0.0, 0.0))
    for point in points:
        result += point
    return result / max(1, len(points))


def _bounds_center(points):
    minimum = Vector((min(point[i] for point in points) for i in range(3)))
    maximum = Vector((max(point[i] for point in points) for i in range(3)))
    return (minimum + maximum) * 0.5


def _world_bounds_center(obj):
    return _centroid([obj.matrix_world @ Vector(corner) for corner in obj.bound_box])


def _modifier_value(modifier, identifier):
    try:
        return getattr(modifier.properties.inputs, identifier).value
    except Exception:
        return modifier[identifier]


def _modifier_set(modifier, identifier, value):
    try:
        getattr(modifier.properties.inputs, identifier).value = value
    except Exception:
        modifier[identifier] = value


def setup(*, destination_center=(900.0, 0.0, 0.0)):
    existing = [
        name
        for name in (MODEL_TEST, SCAN_TEST)
        if bpy.data.objects.get(name) is not None
    ]
    if existing:
        raise RuntimeError(f"Usability test objects already exist: {existing}")

    model_base = bpy.data.objects.get(MODEL_BASE)
    scan_source = bpy.data.objects.get(SCAN_SOURCE)
    if model_base is None or scan_source is None:
        raise RuntimeError(
            f"Required objects missing: {MODEL_BASE!r}, {SCAN_SOURCE!r}"
        )

    collection = bpy.data.collections.get(COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION)
        bpy.context.scene.collection.children.link(collection)

    scan_center = _world_bounds_center(scan_source)
    destination_center = Vector(destination_center)
    gallery_to_test = Matrix.Translation(destination_center - scan_center)

    scan_test = scan_source.copy()
    scan_test.data = scan_source.data
    scan_test.animation_data_clear()
    scan_test.name = SCAN_TEST
    scan_test.matrix_world = gallery_to_test @ scan_source.matrix_world
    scan_test.display_type = "WIRE"
    scan_test.show_wire = True
    scan_test.show_all_edges = True
    scan_test.color = (0.08, 0.35, 0.95, 1.0)
    scan_test["bm_test_role"] = "scan_reference"
    scan_test["bm_source_object"] = scan_source.name
    collection.objects.link(scan_test)

    model_points = _evaluated_local_vertices(model_base)
    model_center = _bounds_center(model_points)
    aligned_at_gallery = Matrix.Translation(scan_center - model_center)

    model_test = model_base.copy()
    model_test.data = model_base.data
    model_test.animation_data_clear()
    model_test.name = MODEL_TEST
    model_test.matrix_world = gallery_to_test @ aligned_at_gallery
    model_test.display_type = "SOLID"
    model_test.show_in_front = True
    model_test.color = (0.95, 0.18, 0.06, 1.0)
    model_test["case_id"] = "RENATA_USABILITY_V3"
    model_test["bm_test_role"] = "clinical_controller"
    model_test["bm_scan_target"] = scan_test.name
    model_test["bm_alignment"] = "world_bbox_center_translation_only"
    model_test["bm_workflow"] = (
        "Select this object and use Painel Clínico V3; scan reference is blue wire"
    )
    collection.objects.link(model_test)

    modifier = next(
        (
            item
            for item in model_test.modifiers
            if item.type == "NODES"
            and item.node_group
            and item.node_group.name == "BM_AjusteScan_v3"
        ),
        None,
    )
    base_modifier = next(
        (
            item
            for item in model_base.modifiers
            if item.type == "NODES"
            and item.node_group
            and item.node_group.name == "BM_AjusteScan_v3"
        ),
        None,
    )
    if modifier is None or base_modifier is None:
        raise RuntimeError("V3 modifiers not found")

    semantic = json.loads(modifier.node_group["semantic_input_identifiers"])
    probe_id = semantic["long_proximal_global"]
    base_before = float(_modifier_value(base_modifier, probe_id))
    test_before = float(_modifier_value(modifier, probe_id))
    _modifier_set(modifier, probe_id, test_before + 1.0)
    bpy.context.view_layer.update()
    base_after = float(_modifier_value(base_modifier, probe_id))
    _modifier_set(modifier, probe_id, test_before)
    bpy.context.view_layer.update()
    if abs(base_after - base_before) > 1e-9:
        raise RuntimeError("Per-object modifier values are not independent")

    model_test["bm_independent_values_validated"] = True
    model_test["bm_probe_base_value"] = base_before
    model_test["bm_probe_test_value"] = test_before

    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    model_test.select_set(True)
    bpy.context.view_layer.objects.active = model_test

    report = {
        "collection": collection.name,
        "controller": model_test.name,
        "scan_reference": scan_test.name,
        "source_scan": scan_source.name,
        "destination_center": list(destination_center),
        "alignment": model_test["bm_alignment"],
        "independent_modifier_values": True,
        "active_object": bpy.context.view_layer.objects.active.name,
    }
    text = bpy.data.texts.get("BM_TESTE_USABILIDADE_V3.json")
    if text is None:
        text = bpy.data.texts.new("BM_TESTE_USABILIDADE_V3.json")
    else:
        text.clear()
    text.write(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def _parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--destination-x", type=float, default=900.0)
    return parser.parse_args(argv)


def main(argv=None):
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = _parse_args(argv)
    report = setup(destination_center=(args.destination_x, 0.0, 0.0))
    if args.output:
        output = str(Path(args.output).resolve())
        bpy.ops.wm.save_as_mainfile(filepath=output)
        report["saved_to"] = output
    print("BM_CLINICAL_V3_SCAN_TEST_BEGIN")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("BM_CLINICAL_V3_SCAN_TEST_END")
    return report


if __name__ == "__main__":
    main()
