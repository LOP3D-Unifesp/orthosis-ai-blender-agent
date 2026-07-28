"""Build the versioned clinical scan facade V3 inside Blender.

The builder is intentionally non-destructive:

* ``Biomodelo_v2`` is only referenced, never edited.
* ``BM_AjusteScan_v2`` and ``BM_AS_Nucleo_Clinico_v2`` remain untouched.
* the effective state of ``BM_AJUSTE_SCAN_BASE_v1`` is baked as the V3
  baseline, while every newly exposed fine control starts at zero.

Run headlessly:

    blender -b source.blend --python tools/build_biomodel_clinical_v3.py -- \
      --contract presets/biomodel_clinical_contract_v3.json \
      --output candidate.blend

The ``build`` function can also be called through the live Blender bridge.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "presets" / "biomodel_clinical_contract_v3.json"


FINGERS = {
    "index": {
        "label": "Indicador",
        "length_node": "index",
        "old_flex": {
            "mcp": "Indicador - correção MCP",
            "pip": "Indicador - correção PIP",
            "dip": "Indicador - correção DIP",
        },
        "core_flex": {
            "mcp": "Indicador - Flex/Ext proximal",
            "pip": "Indicador - Flex/Ext média",
            "dip": "Indicador - Flex/Ext distal",
        },
        "old_abduction": "Indicador - correção de abdução",
        "core_abduction": "Indicador - Abdução",
        "old_advance": "MCP indicador - avanço",
        "core_advance": "Indicador - Avanço MCP",
        "old_lateral": "MCP indicador - lateral",
        "core_lateral": "Indicador - Lateral MCP",
        "old_arc": "Metacarpo indicador - arco palmar",
        "core_arc": "Indicador - Arco Z",
        "core_arc_weight": "Indicador - Arco Z peso",
        "old_radial": "Metacarpo indicador - radial",
        "core_radial": "Indicador - Radial",
        "side_curve": "Curvatura radial da palma",
        "pair_sign": 1.0,
    },
    "middle": {
        "label": "Médio",
        "length_node": "middle",
        "old_flex": {
            "mcp": "Médio - correção MCP",
            "pip": "Médio - correção PIP",
            "dip": "Médio - correção DIP",
        },
        "core_flex": {
            "mcp": "Médio - Flex/Ext proximal",
            "pip": "Médio - Flex/Ext média",
            "dip": "Médio - Flex/Ext distal",
        },
        "old_abduction": "Médio - correção de abdução",
        "core_abduction": "Médio - Abdução",
        "old_advance": "MCP médio - avanço",
        "core_advance": "Médio - Avanço MCP",
        "old_lateral": "MCP médio - lateral",
        "core_lateral": "Médio - Lateral MCP",
        "old_arc": "Metacarpo médio - arco palmar",
        "core_arc": "Médio - Arco Z",
        "core_arc_weight": "Médio - Arco Z peso",
        "old_radial": "Metacarpo médio - radial",
        "core_radial": "Médio - Radial",
        "side_curve": "Curvatura radial da palma",
        "pair_sign": 1.0,
    },
    "ring": {
        "label": "Anelar",
        "length_node": "ring",
        "old_flex": {
            "mcp": "Anelar - correção MCP",
            "pip": "Anelar - correção PIP",
            "dip": "Anelar - correção DIP",
        },
        "core_flex": {
            "mcp": "Anelar - Flex/Ext proximal",
            "pip": "Anelar - Flex/Ext média",
            "dip": "Anelar - Flex/Ext distal",
        },
        "old_abduction": "Anelar - correção de abdução",
        "core_abduction": "Anelar - Abdução",
        "old_advance": "MCP anelar - avanço",
        "core_advance": "Anelar - Avanço MCP",
        "old_lateral": "MCP anelar - lateral",
        "core_lateral": "Anelar - Lateral MCP",
        "old_arc": "Metacarpo anelar - arco palmar",
        "core_arc": "Anelar - Arco Z",
        "core_arc_weight": "Anelar - Arco Z peso",
        "old_radial": "Metacarpo anelar - radial",
        "core_radial": "Anelar - Radial",
        "side_curve": "Curvatura ulnar da palma",
        "pair_sign": -1.0,
    },
    "little": {
        "label": "Mindinho",
        "length_node": "little",
        "old_flex": {
            "mcp": "Mindinho - correção MCP",
            "pip": "Mindinho - correção PIP",
            "dip": "Mindinho - correção DIP",
        },
        "core_flex": {
            "mcp": "Mindinho - Flex/Ext proximal",
            "pip": "Mindinho - Flex/Ext média",
            "dip": "Mindinho - Flex/Ext distal",
        },
        "old_abduction": "Mindinho - correção de abdução",
        "core_abduction": "Mindinho - Abdução",
        "old_advance": "MCP mindinho - avanço",
        "core_advance": "Mindinho - Avanço MCP",
        "old_lateral": "MCP mindinho - lateral",
        "core_lateral": "Mindinho - Lateral MCP",
        "old_arc": "Metacarpo mindinho - arco palmar",
        "core_arc": "Mindinho - Arco Z",
        "core_arc_weight": "Mindinho - Arco Z peso",
        "old_radial": "Metacarpo mindinho - radial",
        "core_radial": "Mindinho - Radial",
        "side_curve": "Curvatura ulnar da palma",
        "pair_sign": -1.0,
    },
}

SEGMENTS = {
    "proximal": ("0", "long_proximal_global"),
    "middle": ("1", "long_middle_global"),
    "distal": ("2", "long_distal_global"),
}


def _input_items(tree):
    return [
        item
        for item in tree.interface.items_tree
        if getattr(item, "item_type", "") == "SOCKET"
        and getattr(item, "in_out", "") == "INPUT"
    ]


def _item_by_name(tree, name):
    for item in _input_items(tree):
        if item.name == name:
            return item
    raise KeyError(f"Interface input not found in {tree.name}: {name}")


def _node_input(node, name):
    socket = node.inputs.get(name)
    if socket is None:
        raise KeyError(f"Node input not found on {node.name}: {name}")
    return socket


def _group_output(group_input, name):
    socket = group_input.outputs.get(name)
    if socket is None:
        raise KeyError(f"Group input output not found: {name}")
    return socket


def _modifier_get(modifier, identifier):
    try:
        return getattr(modifier.properties.inputs, identifier).value
    except Exception:
        try:
            return modifier[identifier]
        except Exception:
            return None


def _modifier_set(modifier, identifier, value):
    try:
        getattr(modifier.properties.inputs, identifier).value = value
        return
    except Exception:
        pass
    modifier[identifier] = value


def _plain(value):
    if hasattr(value, "to_list"):
        return value.to_list()
    return value


def _set_interface_default(tree, name, value):
    item = _item_by_name(tree, name)
    if hasattr(item, "default_value") and value is not None:
        item.default_value = value


def _unlink_target(tree, socket):
    for link in list(socket.links):
        tree.links.remove(link)


def _math_node(tree, name, operation, label, x, y, frame=None):
    node = tree.nodes.new("ShaderNodeMath")
    node.name = name
    node.label = label
    node.operation = operation
    node.location = (x, y)
    if frame is not None:
        node.parent = frame
    return node


def _value_node(tree, name, value, label, x, y, frame=None):
    node = tree.nodes.new("ShaderNodeValue")
    node.name = name
    node.label = label
    node.outputs[0].default_value = float(value)
    node.location = (x, y)
    if frame is not None:
        node.parent = frame
    return node


def _frame(tree, name, label, x, y):
    frame = tree.nodes.new("NodeFrame")
    frame.name = name
    frame.label = label
    frame.location = (x, y)
    frame.label_size = 24
    return frame


def _evaluated_geometry(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        coords = [vertex.co.copy() for vertex in mesh.vertices]
        return {
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "polygons": len(mesh.polygons),
            "coords": coords,
        }
    finally:
        evaluated.to_mesh_clear()


def _compare_geometry(reference, candidate):
    if reference["vertices"] != candidate["vertices"]:
        raise RuntimeError(
            f"Vertex count changed: {reference['vertices']} -> {candidate['vertices']}"
        )
    if reference["polygons"] != candidate["polygons"]:
        raise RuntimeError(
            f"Polygon count changed: {reference['polygons']} -> {candidate['polygons']}"
        )
    max_delta = max(
        (
            (before - after).length
            for before, after in zip(reference["coords"], candidate["coords"])
        ),
        default=0.0,
    )
    return max_delta


def _control_default(spec, values, core_node, inner):
    kind = spec["kind"]
    if kind == "passthrough":
        return values[spec["source"]]
    if kind == "new":
        return spec.get("default", 0.0)
    if kind == "default_from_core":
        return _plain(_node_input(core_node, spec["default_from_core"]).default_value)
    if kind == "derived_thumb_current":
        total = float(values["Comprimento do polegar (MCP-ponta)"])
        ratio_node = (
            inner.nodes["Derivar_thumb_0"]
            if spec["segment"] == "proximal"
            else inner.nodes["Derivar_thumb_1"]
        )
        return total * float(ratio_node.inputs[1].default_value)
    raise ValueError(f"Unknown control kind: {kind}")


def _add_interface_socket(tree, spec, default, parent=None):
    socket = tree.interface.new_socket(
        name=spec["label"],
        in_out="INPUT",
        socket_type=spec.get("socket_type", "NodeSocketFloat"),
    )
    if hasattr(socket, "default_value"):
        socket.default_value = default
    if spec.get("subtype") and hasattr(socket, "subtype"):
        socket.subtype = spec["subtype"]
    if spec.get("min") is not None and hasattr(socket, "min_value"):
        socket.min_value = spec["min"]
    if spec.get("max") is not None and hasattr(socket, "max_value"):
        socket.max_value = spec["max"]
    socket.description = (
        f"[V3:{spec['id']}] "
        + (
            "valor clínico preservado do BASE V2"
            if spec["kind"] == "passthrough"
            else "ajuste V3; zero preserva a base migrada"
        )
    )
    if parent is not None:
        tree.interface.move_to_parent(socket, parent, 10_000)
    return socket


def _add_internal_control_socket(inner, spec, default):
    internal_spec = dict(spec)
    internal_spec["label"] = f"V3::{spec['id']}"
    return _add_interface_socket(inner, internal_spec, default, parent=None)


def _register_metadata(
    contract,
    dev_obj,
    legacy_obj,
    target_obj,
    facade,
    inner,
    validation,
):
    collection_name = contract["registry_collection"]
    registry = bpy.data.collections.get(collection_name)
    if registry is None:
        registry = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(registry)

    for obj in (dev_obj, legacy_obj, target_obj):
        if obj is not None and obj.name not in registry.objects:
            registry.objects.link(obj)

    if dev_obj is not None:
        dev_obj["bm_registry_role"] = "raw_core_dev"
        dev_obj["bm_registry_status"] = "engineering_only"
        dev_obj["bm_clinical_entry"] = False
        dev_obj["bm_model_core"] = contract["model_core"]

    legacy_obj["bm_registry_role"] = "clinical_adapter_legacy"
    legacy_obj["bm_registry_status"] = "preserved_reference"
    legacy_obj["bm_clinical_entry"] = True
    legacy_obj["bm_model_core"] = contract["model_core"]
    legacy_obj["bm_clinical_successor"] = contract["target_object"]

    target_obj["bm_registry_role"] = "clinical_scan_primary"
    target_obj["bm_registry_status"] = "candidate_usability_test"
    target_obj["bm_clinical_entry"] = True
    target_obj["bm_model_core"] = contract["model_core"]
    target_obj["bm_facade"] = contract["target_facade"]
    target_obj["bm_adapter"] = contract["target_adapter"]
    target_obj["bm_schema_version"] = int(contract["schema_version"])
    target_obj["bm_baseline_source"] = contract["source_object"]
    target_obj["bm_workflow"] = (
        "Duplicate per scan; rename BM_SCAN_<case_id>; keep BM_AjusteScan_v3 shared"
    )
    target_obj["case_id"] = "BASE"
    target_obj["finish_mode"] = "Raw"
    target_obj["bm_validation_max_delta"] = float(validation["max_delta"])

    facade["architecture"] = contract["architecture"]
    facade["schema_version"] = int(contract["schema_version"])
    facade["model_core"] = contract["model_core"]
    facade["adapter"] = contract["target_adapter"]
    facade["purpose"] = "Routine scan fitting; operator-facing controls"
    facade.use_fake_user = True

    inner["architecture"] = "clinical_controls_and_derivations_v3"
    inner["schema_version"] = int(contract["schema_version"])
    inner["model_core"] = contract["model_core"]
    inner["baseline_source"] = contract["source_object"]
    inner["source_tree"] = contract["model_core"]
    inner["notes"] = (
        "V2 clinical state baked as baseline; V3 fine controls are additive and neutral"
    )
    inner.use_fake_user = True

    manifest = {
        "schema_version": contract["schema_version"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "blend_source": bpy.data.filepath,
        "model_core": contract["model_core"],
        "entries": [
            {
                "object": dev_obj.name if dev_obj else None,
                "role": "raw_core_dev",
                "routine_clinical_use": False,
            },
            {
                "object": legacy_obj.name,
                "role": "clinical_adapter_legacy",
                "facade": contract["source_facade"],
                "routine_clinical_use": False,
            },
            {
                "object": target_obj.name,
                "role": "clinical_scan_primary",
                "facade": facade.name,
                "adapter": inner.name,
                "routine_clinical_use": True,
            },
        ],
        "validation": validation,
    }
    text = bpy.data.texts.get("BM_REGISTRO_CLINICO.json")
    if text is None:
        text = bpy.data.texts.new("BM_REGISTRO_CLINICO.json")
    else:
        text.clear()
    text.write(json.dumps(manifest, indent=2, ensure_ascii=False))


def build(contract_path=DEFAULT_CONTRACT, *, object_offset_x=170.0):
    contract_path = Path(contract_path).resolve()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    required_groups = (
        contract["source_facade"],
        contract["source_adapter"],
        contract["model_core"],
    )
    missing_groups = [name for name in required_groups if bpy.data.node_groups.get(name) is None]
    if missing_groups:
        raise RuntimeError(f"Missing required node groups: {missing_groups}")

    legacy_obj = bpy.data.objects.get(contract["source_object"])
    if legacy_obj is None:
        raise RuntimeError(f"Source object not found: {contract['source_object']}")
    dev_obj = bpy.data.objects.get("BM_v2_DEV")

    target_names = (
        contract["target_object"],
        contract["target_facade"],
        contract["target_adapter"],
    )
    collisions = [
        name
        for name in target_names
        if bpy.data.objects.get(name) is not None or bpy.data.node_groups.get(name) is not None
    ]
    if collisions:
        raise RuntimeError(f"V3 targets already exist; refusing to overwrite: {collisions}")

    legacy_modifier = next(
        (
            modifier
            for modifier in legacy_obj.modifiers
            if modifier.type == "NODES"
            and modifier.node_group
            and modifier.node_group.name == contract["source_facade"]
        ),
        None,
    )
    if legacy_modifier is None:
        raise RuntimeError("Source clinical Geometry Nodes modifier not found")

    v2_values = {
        item.name: _plain(_modifier_get(legacy_modifier, item.identifier))
        for item in _input_items(legacy_modifier.node_group)
    }
    if any(value is None for value in v2_values.values()):
        missing = [name for name, value in v2_values.items() if value is None]
        raise RuntimeError(f"Could not read V2 modifier values: {missing}")

    baseline_geometry = _evaluated_geometry(legacy_obj)
    raw = bpy.data.node_groups[contract["model_core"]]
    raw_counts_before = (len(raw.nodes), len(raw.links), len(_input_items(raw)))

    inner_v2 = bpy.data.node_groups[contract["source_adapter"]]
    inner = inner_v2.copy()
    inner.name = contract["target_adapter"]
    inner.color_tag = "CONVERTER"
    inner.description = (
        "Painel clínico V3: controles organizados para ajuste em scans; "
        "Biomodelo_v2 permanece como núcleo Raw."
    )

    for item in _input_items(inner):
        if item.name in v2_values and hasattr(item, "default_value"):
            item.default_value = v2_values[item.name]

    group_input = inner.nodes.get("Entradas_Clinicas")
    core = inner.nodes.get("Nucleo_Biomodelo_v2")
    if group_input is None or core is None or core.node_tree != raw:
        raise RuntimeError("Unexpected V2 adapter topology")

    control_defaults = {
        spec["id"]: _control_default(spec, v2_values, core, inner)
        for spec in contract["controls"]
    }
    internal_items = {}
    for spec in contract["controls"]:
        if spec["kind"] == "passthrough":
            internal_items[spec["id"]] = _item_by_name(inner, spec["source"])
        else:
            internal_items[spec["id"]] = _add_internal_control_socket(
                inner, spec, control_defaults[spec["id"]]
            )

    frames = {
        "lengths": _frame(inner, "FRAME_V3_LENGTHS", "V3 — Comprimentos por falange", -650, 550),
        "pose": _frame(inner, "FRAME_V3_POSE", "V3 — Flexão e abertura", -350, 100),
        "palm": _frame(inner, "FRAME_V3_PALM", "V3 — MCP e arco palmar", 0, -450),
        "thumb": _frame(inner, "FRAME_V3_THUMB", "V3 — Polegar", -650, -900),
    }

    def new_output(control_id):
        return _group_output(group_input, internal_items[control_id].name)

    # D2-D5 lengths: retain the migrated per-finger base, then add the new
    # shared segment master and the neutral per-finger fine control.
    for finger_index, (finger_id, data) in enumerate(FINGERS.items()):
        for segment_index, (segment_id, (node_suffix, master_id)) in enumerate(
            SEGMENTS.items()
        ):
            base_node = inner.nodes[f"Corrigir_{data['length_node']}_{node_suffix}"]
            target = _node_input(
                core,
                f"{data['label']} - Comp. falange "
                + ("proximal" if segment_id == "proximal" else "média" if segment_id == "middle" else "distal"),
            )
            _unlink_target(inner, target)
            delta = _math_node(
                inner,
                f"V3_LengthDelta_{finger_id}_{segment_id}",
                "ADD",
                "master do segmento + ajuste do dedo",
                -520 + segment_index * 220,
                420 - finger_index * 150,
                frames["lengths"],
            )
            total = _math_node(
                inner,
                f"V3_LengthFinal_{finger_id}_{segment_id}",
                "ADD",
                "comprimento-base + ajuste V3",
                -300 + segment_index * 220,
                420 - finger_index * 150,
                frames["lengths"],
            )
            inner.links.new(new_output(master_id), delta.inputs[0])
            inner.links.new(new_output(f"{finger_id}_length_{segment_id}"), delta.inputs[1])
            inner.links.new(base_node.outputs[0], total.inputs[0])
            inner.links.new(delta.outputs[0], total.inputs[1])
            inner.links.new(total.outputs[0], target)

    # Thumb lengths are now independent and absolute.
    thumb_length_targets = {
        "thumb_metacarpal_length": "Comp Metacarpo Polegar",
        "thumb_proximal_length": "Comp Falange Prox Polegar",
        "thumb_distal_length": "Comp Falange Dist Polegar",
    }
    for index, (control_id, core_name) in enumerate(thumb_length_targets.items()):
        target = _node_input(core, core_name)
        _unlink_target(inner, target)
        inner.links.new(new_output(control_id), target)

    # Width/thickness corrections stay close to the size controls but become
    # neutral deltas. The V2 corrections remain baked in the migrated base.
    dimension_fines = {
        "palm_bone_width": (
            "Ajuste_Fino_palm_bone_width",
            "Ref. antro - largura osso (mm)",
        ),
        "finger_thickness": (
            "Ajuste_Fino_finger_thickness",
            "Dedos - Tamanho",
        ),
    }
    for index, (control_id, (base_node_name, core_name)) in enumerate(
        dimension_fines.items()
    ):
        target = _node_input(core, core_name)
        _unlink_target(inner, target)
        add = _math_node(
            inner,
            f"V3_DimensionFine_{control_id}",
            "ADD",
            "dimensão-base + ajuste V3",
            380,
            300 - index * 160,
            frames["lengths"],
        )
        inner.links.new(inner.nodes[base_node_name].outputs[0], add.inputs[0])
        inner.links.new(new_output(control_id), add.inputs[1])
        inner.links.new(add.outputs[0], target)

    # All per-finger pose corrections are additive and start at zero.
    for finger_index, (finger_id, data) in enumerate(FINGERS.items()):
        for joint_index, joint in enumerate(("mcp", "pip", "dip")):
            target = _node_input(core, data["core_flex"][joint])
            _unlink_target(inner, target)
            add = _math_node(
                inner,
                f"V3_Flex_{finger_id}_{joint}",
                "ADD",
                "pose-base + ajuste clínico",
                -250 + joint_index * 190,
                360 - finger_index * 130,
                frames["pose"],
            )
            inner.links.new(_group_output(group_input, data["old_flex"][joint]), add.inputs[0])
            inner.links.new(new_output(f"{finger_id}_{joint}_flexion"), add.inputs[1])
            inner.links.new(add.outputs[0], target)

        target = _node_input(core, data["core_abduction"])
        _unlink_target(inner, target)
        add = _math_node(
            inner,
            f"V3_Abduction_{finger_id}",
            "ADD",
            "abdução-base + ajuste clínico",
            360,
            360 - finger_index * 130,
            frames["pose"],
        )
        inner.links.new(_group_output(group_input, data["old_abduction"]), add.inputs[0])
        inner.links.new(new_output(f"{finger_id}_abduction"), add.inputs[1])
        inner.links.new(add.outputs[0], target)

    # Global MCP advance was redundant. Bake it into each ray and expose only
    # a neutral per-finger correction.
    old_advance_global = float(v2_values["MCP - avanço global"])
    _set_interface_default(inner, "MCP - avanço global", 0.0)
    for finger_index, (finger_id, data) in enumerate(FINGERS.items()):
        baked = float(v2_values[data["old_advance"]]) + old_advance_global
        _set_interface_default(inner, data["old_advance"], baked)
        target = _node_input(core, data["core_advance"])
        _unlink_target(inner, target)
        add = _math_node(
            inner,
            f"V3_Advance_{finger_id}",
            "ADD",
            "avanço-base + ajuste do MCP",
            -350,
            320 - finger_index * 150,
            frames["palm"],
        )
        inner.links.new(_group_output(group_input, data["old_advance"]), add.inputs[0])
        inner.links.new(new_output(f"{finger_id}_mcp_advance"), add.inputs[1])
        inner.links.new(add.outputs[0], target)

    # Replace equal lateral translation with a two-versus-two master. The old
    # global value is baked into the four individual baselines.
    old_lateral_global = float(v2_values["MCP - lateral global"])
    _set_interface_default(inner, "MCP - lateral global", 0.0)
    for finger_index, (finger_id, data) in enumerate(FINGERS.items()):
        baked = float(v2_values[data["old_lateral"]]) + old_lateral_global
        _set_interface_default(inner, data["old_lateral"], baked)
        target = _node_input(core, data["core_lateral"])
        _unlink_target(inner, target)
        signed = _math_node(
            inner,
            f"V3_LateralPair_{finger_id}",
            "MULTIPLY",
            f"master × {data['pair_sign']:+g}",
            20,
            320 - finger_index * 150,
            frames["palm"],
        )
        signed.inputs[1].default_value = data["pair_sign"]
        delta = _math_node(
            inner,
            f"V3_LateralDelta_{finger_id}",
            "ADD",
            "master simétrico + ajuste do dedo",
            210,
            320 - finger_index * 150,
            frames["palm"],
        )
        final = _math_node(
            inner,
            f"V3_LateralFinal_{finger_id}",
            "ADD",
            "lateral-base + ajuste V3",
            400,
            320 - finger_index * 150,
            frames["palm"],
        )
        inner.links.new(new_output("mcp_lateral_pair"), signed.inputs[0])
        inner.links.new(signed.outputs[0], delta.inputs[0])
        inner.links.new(new_output(f"{finger_id}_mcp_lateral"), delta.inputs[1])
        inner.links.new(_group_output(group_input, data["old_lateral"]), final.inputs[0])
        inner.links.new(delta.outputs[0], final.inputs[1])
        inner.links.new(final.outputs[0], target)

    # Keep a single radial master. Its V2 result is baked per ray, and the new
    # zero-based master is distributed with the anatomical radial signs.
    old_radial_global = float(v2_values["Metacarpos - radial global"])
    _set_interface_default(inner, "Metacarpos - radial global", 0.0)
    for finger_index, (finger_id, data) in enumerate(FINGERS.items()):
        sign = data["pair_sign"]
        baked = float(v2_values[data["old_radial"]]) + old_radial_global * sign
        target = _node_input(core, data["core_radial"])
        _unlink_target(inner, target)
        base = _value_node(
            inner,
            f"V3_RadialBase_{finger_id}",
            baked,
            "radial-base migrado",
            650,
            320 - finger_index * 150,
            frames["palm"],
        )
        signed = _math_node(
            inner,
            f"V3_RadialMaster_{finger_id}",
            "MULTIPLY",
            f"radial global × {sign:+g}",
            830,
            320 - finger_index * 150,
            frames["palm"],
        )
        signed.inputs[1].default_value = sign
        final = _math_node(
            inner,
            f"V3_RadialFinal_{finger_id}",
            "ADD",
            "radial-base + master",
            1020,
            320 - finger_index * 150,
            frames["palm"],
        )
        inner.links.new(new_output("metacarpal_radial_global"), signed.inputs[0])
        inner.links.new(base.outputs[0], final.inputs[0])
        inner.links.new(signed.outputs[0], final.inputs[1])
        inner.links.new(final.outputs[0], target)

    # Replace the weighted global Arco Z with an equal master on all four rays.
    # The prior weighted result is baked per ray; radial/ulnar curvature remains
    # visible and additive, followed by the neutral fine correction.
    old_arc_global = float(v2_values["Metacarpos - arco palmar global"])
    _set_interface_default(inner, "Metacarpos - arco palmar global", 0.0)
    for finger_index, (finger_id, data) in enumerate(FINGERS.items()):
        weight = float(_node_input(core, data["core_arc_weight"]).default_value)
        baked_without_side = (
            float(v2_values[data["old_arc"]])
            + old_arc_global * weight
            + float(v2_values[data["side_curve"]])
        )
        target = _node_input(core, data["core_arc"])
        _unlink_target(inner, target)
        base = _value_node(
            inner,
            f"V3_ArcBase_{finger_id}",
            baked_without_side,
            "arco-base migrado",
            -40,
            -360 - finger_index * 150,
            frames["palm"],
        )
        master_fine = _math_node(
            inner,
            f"V3_ArcMasterFine_{finger_id}",
            "ADD",
            "movimento comum + ajuste fino",
            150,
            -360 - finger_index * 150,
            frames["palm"],
        )
        side = _math_node(
            inner,
            f"V3_ArcSide_{finger_id}",
            "ADD",
            "curvatura do lado + movimento comum",
            340,
            -360 - finger_index * 150,
            frames["palm"],
        )
        final = _math_node(
            inner,
            f"V3_ArcFinal_{finger_id}",
            "ADD",
            "arco-base + controles V3",
            530,
            -360 - finger_index * 150,
            frames["palm"],
        )
        inner.links.new(new_output("palmar_arc_global"), master_fine.inputs[0])
        inner.links.new(new_output(f"{finger_id}_palmar_arc"), master_fine.inputs[1])
        side_control = (
            "palm_curve_radial"
            if data["side_curve"] == "Curvatura radial da palma"
            else "palm_curve_ulnar"
        )
        inner.links.new(new_output(side_control), side.inputs[0])
        inner.links.new(master_fine.outputs[0], side.inputs[1])
        inner.links.new(base.outputs[0], final.inputs[0])
        inner.links.new(side.outputs[0], final.inputs[1])
        inner.links.new(final.outputs[0], target)

    # Thumb fine controls: bake the current V2 offsets, expose only neutral
    # corrections in the consolidated thumb panel.
    thumb_direct = {
        "thumb_cmc_radial": ("Polegar - CMC radial/ulnar", "Polegar - CMC radial"),
        "thumb_cmc_palmar": ("Polegar - CMC palmar/dorsal", "Polegar - CMC baixar"),
        "thumb_proximal_palmar": (
            "Polegar - correção palmar proximal",
            "Polegar - Palmar falange prox",
        ),
        "thumb_distal_palmar": (
            "Polegar - correção palmar distal",
            "Polegar - Palmar falange dist",
        ),
    }
    for index, (control_id, (old_name, core_name)) in enumerate(thumb_direct.items()):
        target = _node_input(core, core_name)
        _unlink_target(inner, target)
        add = _math_node(
            inner,
            f"V3_ThumbFine_{control_id}",
            "ADD",
            "posição-base + ajuste do polegar",
            -260,
            260 - index * 150,
            frames["thumb"],
        )
        inner.links.new(_group_output(group_input, old_name), add.inputs[0])
        inner.links.new(new_output(control_id), add.inputs[1])
        inner.links.new(add.outputs[0], target)

    cmc_position = inner.nodes.get("CMC_Posicao_Independente")
    if cmc_position is None:
        raise RuntimeError("CMC compensation node not found")
    _unlink_target(inner, cmc_position.inputs[0])
    cmc_fine = _math_node(
        inner,
        "V3_ThumbFine_CMC_Longitudinal",
        "ADD",
        "implantação-base + ajuste proximal/distal",
        30,
        -340,
        frames["thumb"],
    )
    inner.links.new(
        _group_output(group_input, "Polegar - correção CMC proximal/distal"),
        cmc_fine.inputs[0],
    )
    inner.links.new(new_output("thumb_cmc_longitudinal"), cmc_fine.inputs[1])
    inner.links.new(cmc_fine.outputs[0], cmc_position.inputs[0])

    # Remove derivations that V3 explicitly bypasses.
    for node_name in (
        "Derivar_thumb_0",
        "Derivar_thumb_1",
        "Curvatura_Palma_Radial_0",
        "Curvatura_Palma_Radial_1",
        "Curvatura_Palma_Ulnar_0",
        "Curvatura_Palma_Ulnar_1",
    ):
        node = inner.nodes.get(node_name)
        if node is not None:
            inner.nodes.remove(node)

    # Public facade: nested clinical panels plus one-to-one links to the
    # versioned adapter. The raw and legacy-only sockets remain hidden here.
    facade = bpy.data.node_groups.new(contract["target_facade"], "GeometryNodeTree")
    facade.description = (
        "Interface clínica V3 para ajuste rotineiro do biomodelo sobre scans."
    )
    panels = {}
    for panel_spec in contract["panels"]:
        panel = facade.interface.new_panel(panel_spec["label"])
        panel.default_closed = bool(panel_spec.get("default_closed", False))
        panels[panel_spec["id"]] = panel
    for panel_spec in contract["panels"]:
        parent_id = panel_spec.get("parent")
        if parent_id:
            facade.interface.move_to_parent(
                panels[panel_spec["id"]], panels[parent_id], 10_000
            )

    facade.interface.new_socket(
        name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )
    facade_items = {}
    semantic_identifiers = {}
    for spec in contract["controls"]:
        item = _add_interface_socket(
            facade,
            spec,
            control_defaults[spec["id"]],
            parent=panels[spec["panel"]],
        )
        facade_items[spec["id"]] = item
        semantic_identifiers[spec["id"]] = item.identifier

    facade["semantic_input_identifiers"] = json.dumps(
        semantic_identifiers, ensure_ascii=False, sort_keys=True
    )
    facade["contract_file"] = str(contract_path)

    facade_in = facade.nodes.new("NodeGroupInput")
    facade_in.name = "Entradas_Clinicas_V3"
    facade_in.label = "Painel clínico V3"
    facade_in.location = (-500, 0)
    inner_node = facade.nodes.new("GeometryNodeGroup")
    inner_node.name = "Nucleo_Clinico_V3"
    inner_node.label = "Derivações clínicas V3"
    inner_node.node_tree = inner
    inner_node.location = (0, 0)
    facade_out = facade.nodes.new("NodeGroupOutput")
    facade_out.name = "Saida_Geometria"
    facade_out.location = (500, 0)

    # Apply every internal interface default explicitly to the nested instance.
    for item in _input_items(inner):
        socket = inner_node.inputs.get(item.name)
        if socket is not None and hasattr(socket, "default_value"):
            try:
                socket.default_value = item.default_value
            except (TypeError, ValueError, AttributeError):
                pass

    for spec in contract["controls"]:
        public_socket = facade_in.outputs.get(spec["label"])
        internal_name = (
            spec["source"] if spec["kind"] == "passthrough" else f"V3::{spec['id']}"
        )
        internal_socket = inner_node.inputs.get(internal_name)
        if public_socket is None or internal_socket is None:
            raise RuntimeError(
                f"Could not link V3 control {spec['id']}: "
                f"{spec['label']} -> {internal_name}"
            )
        facade.links.new(public_socket, internal_socket)

    facade.links.new(
        inner_node.outputs["Geometry"],
        facade_out.inputs["Geometry"],
    )

    target_obj = legacy_obj.copy()
    target_obj.data = legacy_obj.data.copy()
    target_obj.animation_data_clear()
    target_obj.name = contract["target_object"]
    for modifier in list(target_obj.modifiers):
        target_obj.modifiers.remove(modifier)
    target_modifier = target_obj.modifiers.new("Painel Clínico V3", "NODES")
    target_modifier.node_group = facade
    target_obj.location = legacy_obj.location + Vector((float(object_offset_x), 0.0, 0.0))

    registry = bpy.data.collections.get(contract["registry_collection"])
    if registry is None:
        registry = bpy.data.collections.new(contract["registry_collection"])
        bpy.context.scene.collection.children.link(registry)
    registry.objects.link(target_obj)

    for spec in contract["controls"]:
        _modifier_set(
            target_modifier,
            facade_items[spec["id"]].identifier,
            control_defaults[spec["id"]],
        )
    target_obj.update_tag()
    bpy.context.view_layer.update()

    candidate_geometry = _evaluated_geometry(target_obj)
    max_delta = _compare_geometry(baseline_geometry, candidate_geometry)
    if max_delta > 1e-4:
        raise RuntimeError(
            f"V3 default does not preserve the V2 base; max vertex delta={max_delta:.8f}"
        )

    raw_counts_after = (len(raw.nodes), len(raw.links), len(_input_items(raw)))
    if raw_counts_after != raw_counts_before:
        raise RuntimeError(
            f"Raw core changed unexpectedly: {raw_counts_before} -> {raw_counts_after}"
        )

    # Functional smoke tests for the controls introduced by the user request.
    response_tests = {
        "long_proximal_global": 5.0,
        "long_middle_global": 5.0,
        "long_distal_global": 5.0,
        "thumb_metacarpal_length": control_defaults["thumb_metacarpal_length"] + 5.0,
        "thumb_proximal_length": control_defaults["thumb_proximal_length"] + 5.0,
        "thumb_distal_length": control_defaults["thumb_distal_length"] + 5.0,
        "mcp_lateral_pair": 5.0,
        "palmar_arc_global": 5.0,
    }
    responses = {}
    neutral_geometry = candidate_geometry
    for control_id, test_value in response_tests.items():
        item = facade_items[control_id]
        original = control_defaults[control_id]
        _modifier_set(target_modifier, item.identifier, test_value)
        target_obj.update_tag()
        bpy.context.view_layer.update()
        tested = _evaluated_geometry(target_obj)
        delta = _compare_geometry(neutral_geometry, tested)
        if not math.isfinite(delta) or delta <= 1e-6:
            raise RuntimeError(f"V3 control produced no valid response: {control_id}")
        responses[control_id] = delta
        _modifier_set(target_modifier, item.identifier, original)
        target_obj.update_tag()
        bpy.context.view_layer.update()

    restored_delta = _compare_geometry(
        neutral_geometry,
        _evaluated_geometry(target_obj),
    )
    if restored_delta > 1e-5:
        raise RuntimeError(f"Control smoke test did not restore baseline: {restored_delta}")

    zero_controls = [
        spec["id"]
        for spec in contract["controls"]
        if spec["kind"] == "new"
        and spec["id"]
        not in {
            "thumb_metacarpal_length",
            "thumb_proximal_length",
            "thumb_distal_length",
        }
    ]
    nonzero_fine = {
        control_id: control_defaults[control_id]
        for control_id in zero_controls
        if abs(float(control_defaults[control_id])) > 1e-9
    }
    if nonzero_fine:
        raise RuntimeError(f"New neutral controls are not zero: {nonzero_fine}")

    validation = {
        "baseline_object": legacy_obj.name,
        "target_object": target_obj.name,
        "vertices": candidate_geometry["vertices"],
        "edges": candidate_geometry["edges"],
        "polygons": candidate_geometry["polygons"],
        "max_delta": max_delta,
        "restored_delta": restored_delta,
        "public_inputs": len(_input_items(facade)),
        "panels": sum(
            1
            for item in facade.interface.items_tree
            if getattr(item, "item_type", "") == "PANEL"
        ),
        "neutral_v3_controls": len(zero_controls),
        "response_max_deltas": responses,
        "raw_core_counts_before": raw_counts_before,
        "raw_core_counts_after": raw_counts_after,
        "lateral_pair_signs": {
            finger_id: data["pair_sign"] for finger_id, data in FINGERS.items()
        },
    }

    _register_metadata(
        contract,
        dev_obj,
        legacy_obj,
        target_obj,
        facade,
        inner,
        validation,
    )

    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    target_obj.select_set(True)
    bpy.context.view_layer.objects.active = target_obj

    # Mark the final state after metadata and active-object changes.
    target_obj.update_tag()
    bpy.context.view_layer.update()
    return validation


def _parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output")
    parser.add_argument("--object-offset-x", type=float, default=170.0)
    return parser.parse_args(argv)


def main(argv=None):
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = _parse_args(argv)
    validation = build(args.contract, object_offset_x=args.object_offset_x)
    if args.output:
        output = str(Path(args.output).resolve())
        bpy.ops.wm.save_as_mainfile(filepath=output)
        validation["saved_to"] = output
    print("BM_CLINICAL_V3_RESULT_BEGIN")
    print(json.dumps(validation, indent=2, ensure_ascii=False))
    print("BM_CLINICAL_V3_RESULT_END")
    return validation


if __name__ == "__main__":
    main()
