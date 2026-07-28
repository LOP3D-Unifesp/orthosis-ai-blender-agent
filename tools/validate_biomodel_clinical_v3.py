"""Validate the V3 clinical facade, every public control, and scan test setup."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "presets" / "biomodel_clinical_contract_v3.json"


def _inputs(tree):
    return [
        item
        for item in tree.interface.items_tree
        if getattr(item, "item_type", "") == "SOCKET"
        and getattr(item, "in_out", "") == "INPUT"
    ]


def _panels(tree):
    return [
        item
        for item in tree.interface.items_tree
        if getattr(item, "item_type", "") == "PANEL"
    ]


def _get(modifier, identifier):
    try:
        return getattr(modifier.properties.inputs, identifier).value
    except Exception:
        return modifier[identifier]


def _set(modifier, identifier, value):
    try:
        getattr(modifier.properties.inputs, identifier).value = value
    except Exception:
        modifier[identifier] = value


def _geometry(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        coords = [vertex.co.copy() for vertex in mesh.vertices]
        if any(not all(math.isfinite(component) for component in point) for point in coords):
            raise RuntimeError(f"Non-finite coordinate in {obj.name}")
        return coords, len(mesh.edges), len(mesh.polygons)
    finally:
        evaluated.to_mesh_clear()


def _max_delta(before, after):
    return max(
        ((left - right).length for left, right in zip(before, after)),
        default=0.0,
    )


def validate(contract_path=DEFAULT_CONTRACT):
    contract = json.loads(Path(contract_path).read_text(encoding="utf-8"))
    obj = bpy.data.objects.get(contract["target_object"])
    facade = bpy.data.node_groups.get(contract["target_facade"])
    inner = bpy.data.node_groups.get(contract["target_adapter"])
    raw = bpy.data.node_groups.get(contract["model_core"])
    if any(item is None for item in (obj, facade, inner, raw)):
        raise RuntimeError("V3 object or required node groups are missing")

    modifier = next(
        (
            item
            for item in obj.modifiers
            if item.type == "NODES" and item.node_group == facade
        ),
        None,
    )
    if modifier is None:
        raise RuntimeError("V3 modifier not found")

    facade_inputs = _inputs(facade)
    facade_by_id = {item.identifier: item for item in facade_inputs}
    semantic = json.loads(facade["semantic_input_identifiers"])
    expected_control_ids = [item["id"] for item in contract["controls"]]
    if set(semantic) != set(expected_control_ids):
        raise RuntimeError("Semantic control map differs from the V3 contract")
    if set(semantic.values()) != set(facade_by_id):
        raise RuntimeError("Semantic identifiers differ from facade interface")

    facade_group_input = next(
        node for node in facade.nodes if node.bl_idname == "NodeGroupInput"
    )
    public_link_counts = {}
    for spec in contract["controls"]:
        socket = facade_group_input.outputs.get(spec["label"])
        public_link_counts[spec["id"]] = len(socket.links) if socket else 0
    bad_public_links = {
        key: count for key, count in public_link_counts.items() if count != 1
    }
    if bad_public_links:
        raise RuntimeError(f"Public controls not linked exactly once: {bad_public_links}")

    baseline_coords, baseline_edges, baseline_polygons = _geometry(obj)
    response = {}
    zero_response = []
    original_values = {}
    try:
        for spec in contract["controls"]:
            control_id = spec["id"]
            identifier = semantic[control_id]
            current = _get(modifier, identifier)
            original_values[identifier] = current
            if isinstance(current, bool):
                probe = not current
            else:
                current = float(current)
                maximum = spec.get("max")
                minimum = spec.get("min")
                step = 1.0
                probe = current + step
                if maximum is not None and probe > float(maximum):
                    probe = current - step
                if minimum is not None and probe < float(minimum):
                    probe = current + step * 0.5
            _set(modifier, identifier, probe)
            obj.update_tag()
            bpy.context.view_layer.update()
            coords, edges, polygons = _geometry(obj)
            if len(coords) != len(baseline_coords) or edges != baseline_edges or polygons != baseline_polygons:
                raise RuntimeError(f"Topology changed while probing {control_id}")
            delta = _max_delta(baseline_coords, coords)
            response[control_id] = delta
            if not math.isfinite(delta) or delta <= 1e-7:
                zero_response.append(control_id)
            _set(modifier, identifier, current)
            obj.update_tag()
            bpy.context.view_layer.update()
    finally:
        for identifier, value in original_values.items():
            _set(modifier, identifier, value)
        obj.update_tag()
        bpy.context.view_layer.update()

    restored_coords, restored_edges, restored_polygons = _geometry(obj)
    restored_delta = _max_delta(baseline_coords, restored_coords)
    if restored_edges != baseline_edges or restored_polygons != baseline_polygons:
        raise RuntimeError("Topology changed after restoring V3 controls")
    if restored_delta > 1e-5:
        raise RuntimeError(f"V3 controls did not restore exactly: {restored_delta}")
    if zero_response:
        raise RuntimeError(f"Public V3 controls with no geometric response: {zero_response}")

    new_neutral = {}
    for spec in contract["controls"]:
        if spec["kind"] != "new":
            continue
        value = float(_get(modifier, semantic[spec["id"]]))
        if abs(value) > 1e-9:
            new_neutral[spec["id"]] = value
    if new_neutral:
        raise RuntimeError(f"New additive controls are not neutral: {new_neutral}")

    hierarchy = {}
    for panel in _panels(facade):
        hierarchy[panel.name] = panel.parent.name if panel.parent else None

    scan_test = bpy.data.objects.get("BM_SCAN_RENATA_v3")
    scan_reference = bpy.data.objects.get("SCAN_RENATA_REFERENCIA_v3")
    scan_test_report = None
    if scan_test is not None or scan_reference is not None:
        if scan_test is None or scan_reference is None:
            raise RuntimeError("Incomplete V3 scan test pair")
        if scan_test.get("bm_independent_values_validated") is not True:
            raise RuntimeError("Scan test independence marker is missing")
        scan_test_report = {
            "controller": scan_test.name,
            "reference": scan_reference.name,
            "case_id": scan_test.get("case_id"),
            "independent_values": True,
            "active": bpy.context.view_layer.objects.active.name
            if bpy.context.view_layer.objects.active
            else None,
        }

    report = {
        "object": obj.name,
        "facade": facade.name,
        "adapter": inner.name,
        "model_core": raw.name,
        "geometry": {
            "vertices": len(baseline_coords),
            "edges": baseline_edges,
            "polygons": baseline_polygons,
        },
        "public_inputs": len(facade_inputs),
        "public_inputs_linked_once": len(public_link_counts),
        "panels": len(_panels(facade)),
        "panel_hierarchy": hierarchy,
        "new_neutral_controls": sum(
            1 for spec in contract["controls"] if spec["kind"] == "new"
        ),
        "control_responses": {
            "tested": len(response),
            "minimum_max_delta": min(response.values()),
            "maximum_max_delta": max(response.values()),
            "zero_response": zero_response,
        },
        "restored_delta": restored_delta,
        "facade_nodes_links": [len(facade.nodes), len(facade.links)],
        "adapter_nodes_links": [len(inner.nodes), len(inner.links)],
        "raw_nodes_links_inputs": [len(raw.nodes), len(raw.links), len(_inputs(raw))],
        "invalid_facade_links": sum(not link.is_valid for link in facade.links),
        "invalid_adapter_links": sum(not link.is_valid for link in inner.links),
        "scan_test": scan_test_report,
    }
    return report


def _parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    return parser.parse_args(argv)


def main(argv=None):
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = _parse_args(argv)
    report = validate(args.contract)
    print("BM_CLINICAL_V3_VALIDATION_BEGIN")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("BM_CLINICAL_V3_VALIDATION_END")
    return report


if __name__ == "__main__":
    main()
