"""Create the non-destructive clinical biomodel V3.1 in the open Blender file."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import bpy


SOURCE_OBJECT = "BM_AJUSTE_SCAN_BASE_v3"
SOURCE_FACADE = "BM_AjusteScan_v3"
SOURCE_ADAPTER = "BM_AS_Nucleo_Clinico_v3"
SOURCE_CORE = "Biomodelo_v2"
SOURCE_FINGER = "BM_Dedo_Longo"
SOURCE_ARC = "BM_Dedo_ArcoZ"

TARGET_OBJECT = "BM_AJUSTE_SCAN_BASE_v3_1"
TARGET_FACADE = "BM_AjusteScan_v3_1"
TARGET_ADAPTER = "BM_AS_Nucleo_Clinico_v3_1"
TARGET_CORE = "Biomodelo_v3_1"
TARGET_FINGER = "BM_Dedo_Longo_v3_1"
TARGET_ANGULAR = "BM_Dedo_AberturaZ_v1"

FINGERS = {
    "index": {
        "label": "Indicador",
        "node": "M02_Dedo_Indicador",
        "sign": 1.0,
        "old_lateral": "MCP indicador - lateral",
        "core_lateral": "Indicador - Lateral MCP",
    },
    "middle": {
        "label": "Médio",
        "node": "M02_Dedo_Medio",
        "sign": 1.0,
        "old_lateral": "MCP médio - lateral",
        "core_lateral": "Médio - Lateral MCP",
    },
    "ring": {
        "label": "Anelar",
        "node": "M02_Dedo_Anelar",
        "sign": -1.0,
        "old_lateral": "MCP anelar - lateral",
        "core_lateral": "Anelar - Lateral MCP",
    },
    "little": {
        "label": "Mindinho",
        "node": "M02_Dedo_Mindinho",
        "sign": -1.0,
        "old_lateral": "MCP mindinho - lateral",
        "core_lateral": "Mindinho - Lateral MCP",
    },
}

SEGMENTS = {
    "proximal": {
        "reference_id": "long_proximal_global",
        "reference": 46.10,
        "suffix": "proximal",
    },
    "middle": {
        "reference_id": "long_middle_global",
        "reference": 28.40,
        "suffix": "média",
    },
    "distal": {
        "reference_id": "long_distal_global",
        "reference": 18.20,
        "suffix": "distal",
    },
}

FACTORS = {
    "index": {
        "proximal": 42.93 / 46.10,
        "middle": 25.33 / 28.40,
        "distal": 16.75 / 18.20,
    },
    "middle": {"proximal": 1.0, "middle": 1.0, "distal": 1.0},
    "ring": {
        "proximal": 43.50 / 46.10,
        "middle": 27.10 / 28.40,
        "distal": 17.30 / 18.20,
    },
    "little": {
        "proximal": 34.20 / 46.10,
        "middle": 19.80 / 28.40,
        "distal": 15.10 / 18.20,
    },
}


def _inputs(tree):
    return [
        item
        for item in tree.interface.items_tree
        if getattr(item, "item_type", "") == "SOCKET"
        and getattr(item, "in_out", "") == "INPUT"
    ]


def _interface_item(tree, name):
    for item in _inputs(tree):
        if item.name == name:
            return item
    raise KeyError(f"{tree.name}: interface input not found: {name}")


def _panel(tree, name):
    for item in tree.interface.items_tree:
        if getattr(item, "item_type", "") == "PANEL" and item.name == name:
            return item
    raise KeyError(f"{tree.name}: panel not found: {name}")


def _socket(node, collection, name):
    socket = getattr(node, collection).get(name)
    if socket is None:
        raise KeyError(f"{node.name}: {collection} socket not found: {name}")
    return socket


def _unlink_input(tree, socket):
    for link in list(socket.links):
        tree.links.remove(link)


def _modifier_get(modifier, identifier):
    try:
        value = getattr(modifier.properties.inputs, identifier).value
    except Exception:
        value = modifier.get(identifier)
    if hasattr(value, "to_list"):
        return value.to_list()
    return value


def _modifier_set(modifier, identifier, value):
    try:
        getattr(modifier.properties.inputs, identifier).value = value
        return
    except Exception:
        modifier[identifier] = value


def _semantic_map(tree):
    return json.loads(tree.get("semantic_input_identifiers", "{}"))


def _semantic_values(modifier):
    mapping = _semantic_map(modifier.node_group)
    return {
        control_id: _modifier_get(modifier, identifier)
        for control_id, identifier in mapping.items()
    }


def _set_semantic(modifier, control_id, value):
    identifier = _semantic_map(modifier.node_group)[control_id]
    _modifier_set(modifier, identifier, value)


def _semantic_item(tree, control_id):
    identifier = _semantic_map(tree)[control_id]
    for item in _inputs(tree):
        if item.identifier == identifier:
            return item
    raise KeyError(f"{tree.name}: semantic item not found: {control_id}")


def _evaluated_geometry(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        return {
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "polygons": len(mesh.polygons),
            "coords": [tuple(vertex.co) for vertex in mesh.vertices],
        }
    finally:
        evaluated.to_mesh_clear()


def _max_delta(a, b):
    if len(a["coords"]) != len(b["coords"]):
        return math.inf
    return max(
        math.dist(point_a, point_b)
        for point_a, point_b in zip(a["coords"], b["coords"])
    )


def _new_float_input(tree, name, default=0.0, minimum=-45.0, maximum=45.0):
    item = tree.interface.new_socket(
        name=name,
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    item.default_value = float(default)
    item.min_value = float(minimum)
    item.max_value = float(maximum)
    return item


def _math(tree, name, operation, label):
    node = tree.nodes.new("ShaderNodeMath")
    node.name = name
    node.label = label
    node.operation = operation
    return node


def _assert_targets_absent():
    occupied = []
    if bpy.data.objects.get(TARGET_OBJECT):
        occupied.append(TARGET_OBJECT)
    for name in (
        TARGET_FACADE,
        TARGET_ADAPTER,
        TARGET_CORE,
        TARGET_FINGER,
        TARGET_ANGULAR,
    ):
        if bpy.data.node_groups.get(name):
            occupied.append(name)
    if occupied:
        raise RuntimeError(
            "V3.1 target names already exist; refusing to overwrite: "
            + ", ".join(occupied)
        )


def _source_modifier(source_obj):
    for modifier in source_obj.modifiers:
        if modifier.type == "NODES" and modifier.node_group == bpy.data.node_groups.get(
            SOURCE_FACADE
        ):
            return modifier
    raise RuntimeError(f"{SOURCE_OBJECT}: V3 clinical modifier not found")


def _build_angular_matrix_group(created):
    angular = bpy.data.node_groups[SOURCE_ARC].copy()
    angular.name = TARGET_ANGULAR
    angular.description = (
        "Rotação angular dos metacarpos em Z ao redor da base fixa: "
        "T(P) · Rz · T(-P)."
    )
    angular.use_fake_user = True
    created.append(angular)

    rename = {
        "Arco Z (geral)": "Abertura Z (geral)",
        "Peso do dedo": "Sinal do dedo",
        "Arco Z (dedo)": "Ajuste angular do dedo",
    }
    for item in _inputs(angular):
        if item.name in rename:
            item.name = rename[item.name]

    euler = angular.nodes["Euler_X"]
    euler.name = "Euler_Z"
    euler.label = "✔ rotação no eixo Z"
    inversion = angular.nodes["Inverte_sinal"]
    for link in list(euler.inputs["X"].links):
        angular.links.remove(link)
    angular.links.new(inversion.outputs["Value"], euler.inputs["Z"])

    angular.nodes["Arco_Ponderado"].label = "abertura geral × sinal do dedo"
    angular.nodes["Arco_Total_graus"].label = "ângulo 2+2 + ajuste individual"
    angular.nodes["Arco_radianos"].label = "graus → radianos"
    angular["rotation_axis"] = "Z"
    angular["pivot_semantics"] = "fixed_metacarpal_base"
    return angular


def _build_finger_group(angular, created):
    finger = bpy.data.node_groups[SOURCE_FINGER].copy()
    finger.name = TARGET_FINGER
    finger.description = (
        "Dedo longo V3.1 com abertura angular em Z ao redor da base do metacarpo."
    )
    finger.use_fake_user = True
    created.append(finger)

    _new_float_input(finger, "Metacarpos - Abertura Z geral")
    _new_float_input(finger, "Dedo - Abertura Z")
    _new_float_input(finger, "Cal - Abertura Z sinal", default=1.0, minimum=-1.0, maximum=1.0)

    group_input = finger.nodes.new("NodeGroupInput")
    group_input.name = "GI_AberturaZ_V31"
    group_input.label = "Entradas — abertura angular V3.1"
    group_input.location = (900, -780)

    matrix = finger.nodes.new("GeometryNodeGroup")
    matrix.name = "AberturaZ_Matriz_V31"
    matrix.label = "Abertura 2+2 com base fixa"
    matrix.node_tree = angular
    matrix.location = (1170, -720)

    transform = finger.nodes.new("GeometryNodeTransform")
    transform.name = "AberturaZ_TF_Dedo_V31"
    transform.label = "Gira metacarpo + MCP + falanges"
    transform.location = (1420, -570)
    transform.inputs["Mode"].default_value = "Matrix"

    join = finger.nodes["Join_Dedo"]
    output = finger.nodes["Saida"]
    output_socket = _socket(output, "inputs", "Geometria")
    _unlink_input(finger, output_socket)

    finger.links.new(
        _socket(finger.nodes["Osso_Metacarpo"], "outputs", "Base P"),
        _socket(matrix, "inputs", "Base P"),
    )
    finger.links.new(
        _socket(group_input, "outputs", "Metacarpos - Abertura Z geral"),
        _socket(matrix, "inputs", "Abertura Z (geral)"),
    )
    finger.links.new(
        _socket(group_input, "outputs", "Cal - Abertura Z sinal"),
        _socket(matrix, "inputs", "Sinal do dedo"),
    )
    finger.links.new(
        _socket(group_input, "outputs", "Dedo - Abertura Z"),
        _socket(matrix, "inputs", "Ajuste angular do dedo"),
    )
    finger.links.new(join.outputs["Geometry"], transform.inputs["Geometry"])
    finger.links.new(matrix.outputs["Matriz"], transform.inputs["Transform"])
    finger.links.new(transform.outputs["Geometry"], output_socket)
    finger["opening_semantics"] = "angular_z_about_fixed_base"
    return finger


def _build_core(finger, created):
    source = bpy.data.node_groups[SOURCE_CORE]
    core = source.copy()
    core.name = TARGET_CORE
    core.description = (
        "Núcleo versionado V3.1; Biomodelo_v2 permanece intocado. "
        "Adiciona abertura angular 2+2 dos metacarpos."
    )
    core.use_fake_user = True
    created.append(core)

    _new_float_input(core, "Metacarpos - Abertura Z geral")
    for data in FINGERS.values():
        _new_float_input(core, f"{data['label']} - Abertura Z")

    group_input = core.nodes.new("NodeGroupInput")
    group_input.name = "GI_V31_Abertura"
    group_input.label = "V3.1 — abertura angular 2+2"
    group_input.location = (-780, -1080)

    for finger_id, data in FINGERS.items():
        node = core.nodes[data["node"]]
        node.node_tree = finger
        core.links.new(
            group_input.outputs["Metacarpos - Abertura Z geral"],
            node.inputs["Metacarpos - Abertura Z geral"],
        )
        core.links.new(
            group_input.outputs[f"{data['label']} - Abertura Z"],
            node.inputs["Dedo - Abertura Z"],
        )
        node.inputs["Cal - Abertura Z sinal"].default_value = data["sign"]

    core["source_core"] = SOURCE_CORE
    core["source_core_untouched"] = True
    core["opening_pair_signs"] = json.dumps(
        {finger_id: data["sign"] for finger_id, data in FINGERS.items()},
        sort_keys=True,
    )
    return core


def _build_adapter(core, created):
    adapter = bpy.data.node_groups[SOURCE_ADAPTER].copy()
    adapter.name = TARGET_ADAPTER
    adapter.description = (
        "Derivações clínicas V3.1: medidas reais, fatores antropométricos, "
        "arco neutro e abertura angular."
    )
    adapter.use_fake_user = True
    created.append(adapter)

    group_input = adapter.nodes["Entradas_Clinicas"]
    core_node = adapter.nodes["Nucleo_Biomodelo_v2"]
    core_node.node_tree = core
    core_node.name = "Nucleo_Biomodelo_v3_1"
    core_node.label = "Núcleo versionado V3.1"

    # Reference measurement × calibrated factor + optional zero-based difference.
    for finger_index, (finger_id, data) in enumerate(FINGERS.items()):
        for segment_index, (segment_id, segment) in enumerate(SEGMENTS.items()):
            target = core_node.inputs[
                f"{data['label']} - Comp. falange {segment['suffix']}"
            ]
            _unlink_input(adapter, target)
            scale = _math(
                adapter,
                f"V31_LengthScale_{finger_id}_{segment_id}",
                "MULTIPLY",
                f"medida do médio × {FACTORS[finger_id][segment_id]:.4f}",
            )
            scale.inputs[1].default_value = FACTORS[finger_id][segment_id]
            fine = _math(
                adapter,
                f"V31_LengthFine_{finger_id}_{segment_id}",
                "ADD",
                "comprimento derivado + diferença opcional",
            )
            scale.location = (-180 + segment_index * 210, 860 - finger_index * 155)
            fine.location = (20 + segment_index * 210, 860 - finger_index * 155)
            adapter.links.new(
                group_input.outputs[f"V3::{segment['reference_id']}"],
                scale.inputs[0],
            )
            adapter.links.new(scale.outputs[0], fine.inputs[0])
            adapter.links.new(
                group_input.outputs[f"V3::{finger_id}_length_{segment_id}"],
                fine.inputs[1],
            )
            adapter.links.new(fine.outputs[0], target)

    # Zero is the true neutral for the common palmar flexion/extension.
    for finger_id in FINGERS:
        base = adapter.nodes.get(f"V3_ArcBase_{finger_id}")
        if base is None:
            raise RuntimeError(f"Arc baseline node missing for {finger_id}")
        base.outputs[0].default_value = 0.0
        base.label = "neutro anatômico = 0°"

    # Keep migrated lateral baselines, but stop exposing translation as opening.
    _unlink_input(adapter, core_node.inputs["Dedos - Lateral MCP geral"])
    core_node.inputs["Dedos - Lateral MCP geral"].default_value = 0.0
    for finger_id, data in FINGERS.items():
        old_target = core_node.inputs[data["core_lateral"]]
        _unlink_input(adapter, old_target)
        adapter.links.new(group_input.outputs[data["old_lateral"]], old_target)

    # Public 2+2 controls now drive the new angular system.
    adapter.links.new(
        group_input.outputs["V3::mcp_lateral_pair"],
        core_node.inputs["Metacarpos - Abertura Z geral"],
    )
    for finger_id, data in FINGERS.items():
        adapter.links.new(
            group_input.outputs[f"V3::{finger_id}_mcp_lateral"],
            core_node.inputs[f"{data['label']} - Abertura Z"],
        )

    adapter["schema_version"] = 10
    adapter["reference_digit"] = "middle"
    adapter["reference_lengths_mm"] = json.dumps(
        {segment_id: data["reference"] for segment_id, data in SEGMENTS.items()},
        sort_keys=True,
    )
    adapter["anthropometric_factors"] = json.dumps(FACTORS, sort_keys=True)
    adapter["arc_zero_semantics"] = "neutral"
    adapter["mcp_opening_semantics"] = "angular_z_fixed_base"
    return adapter


def _update_facade_interface(facade):
    panel_renames = {
        "2. Dimensões dos dedos": "2. Medidas das falanges",
        "2a. Ajuste fino por falange": "2a. Diferenças por dedo (opcional)",
        "4. Abertura e arco da palma": "4. Punho, abertura e arco da palma",
        "7. Punho e legado": "7. Ajustes técnicos",
    }
    for old_name, new_name in panel_renames.items():
        _panel(facade, old_name).name = new_name

    opening_panel = _panel(facade, "4. Punho, abertura e arco da palma")
    wrist_item = _semantic_item(facade, "wrist_deviation")
    facade.interface.move_to_parent(wrist_item, opening_panel, 0)

    reference_labels = {
        "long_proximal_global": "Dedo médio — falange proximal",
        "long_middle_global": "Dedo médio — falange média",
        "long_distal_global": "Dedo médio — falange distal",
    }
    for segment_id, segment in SEGMENTS.items():
        item = _semantic_item(facade, segment["reference_id"])
        item.name = reference_labels[segment["reference_id"]]
        item.default_value = segment["reference"]
        item.min_value = 5.0
        item.max_value = 90.0
        item.subtype = "DISTANCE"
        item.description = (
            "Medida real do paciente. Os outros dedos são derivados por "
            "proporções antropométricas calibradas."
        )

    for finger_id, data in FINGERS.items():
        for segment_id, segment in SEGMENTS.items():
            item = _semantic_item(facade, f"{finger_id}_length_{segment_id}")
            item.name = f"{data['label']} — diferença {segment['suffix']}"
            item.description = (
                "Diferença opcional em relação ao comprimento derivado; "
                "0 mantém a proporção antropométrica."
            )

    angular_labels = {
        "mcp_lateral_pair": "Abertura angular MCP (2 + 2)",
        "index_mcp_lateral": "Indicador — ajuste angular MCP",
        "middle_mcp_lateral": "Médio — ajuste angular MCP",
        "ring_mcp_lateral": "Anelar — ajuste angular MCP",
        "little_mcp_lateral": "Mindinho — ajuste angular MCP",
    }
    for control_id, label in angular_labels.items():
        item = _semantic_item(facade, control_id)
        item.name = label
        item.subtype = "NONE"
        item.min_value = -30.0
        item.max_value = 30.0
        item.description = (
            "Rotação em graus ao redor da base fixa do metacarpo; "
            "não desloca lateralmente o punho."
        )

    arc = _semantic_item(facade, "palmar_arc_global")
    arc.description = (
        "Flexão/extensão comum dos quatro metacarpos. 0° é a posição neutra."
    )
    wrist_item.description = (
        "Desvio radial/ulnar do punho; controle clínico principal."
    )


def _build_facade(adapter, created):
    facade = bpy.data.node_groups[SOURCE_FACADE].copy()
    facade.name = TARGET_FACADE
    facade.description = (
        "Painel clínico V3.1: medidas reais, ajuste fino explícito, "
        "punho acessível e movimentos com neutro anatômico."
    )
    facade.use_fake_user = True
    created.append(facade)
    _update_facade_interface(facade)

    inner_node = facade.nodes["Nucleo_Clinico_V3"]
    inner_node.node_tree = adapter
    inner_node.name = "Nucleo_Clinico_V3_1"
    inner_node.label = "Derivações clínicas V3.1"

    facade["schema_version"] = 10
    facade["architecture"] = "clinical_scan_facade_v3_1"
    facade["model_core"] = TARGET_CORE
    facade["adapter"] = TARGET_ADAPTER
    facade["contract_file"] = "presets/biomodel_clinical_patch_v3_1.json"
    return facade


def _build_object(facade, source_obj, source_modifier, current_values, created_objects):
    target = source_obj.copy()
    target.data = source_obj.data.copy() if source_obj.data else None
    target.name = TARGET_OBJECT
    target.animation_data_clear()
    created_objects.append(target)

    registry = bpy.data.collections.get("BIOMODELOS_CLINICOS")
    if registry is None:
        registry = bpy.data.collections.new("BIOMODELOS_CLINICOS")
        bpy.context.scene.collection.children.link(registry)
    registry.objects.link(target)

    target_modifier = None
    for modifier in target.modifiers:
        if modifier.type == "NODES" and modifier.node_group == bpy.data.node_groups.get(
            SOURCE_FACADE
        ):
            target_modifier = modifier
            break
    if target_modifier is None:
        raise RuntimeError("Copied V3 modifier not found")
    target_modifier.node_group = facade
    target_modifier.name = "Painel Clínico V3.1"

    for control_id, value in current_values.items():
        if control_id in _semantic_map(facade):
            _set_semantic(target_modifier, control_id, value)

    for segment in SEGMENTS.values():
        _set_semantic(
            target_modifier,
            segment["reference_id"],
            segment["reference"],
        )
    _set_semantic(target_modifier, "wrist_flexion_legacy", 0.0)

    target["bm_version"] = "3.1"
    target["bm_schema_version"] = 10
    target["bm_facade"] = TARGET_FACADE
    target["bm_adapter"] = TARGET_ADAPTER
    target["bm_core"] = TARGET_CORE
    target["bm_source_object"] = SOURCE_OBJECT
    target["bm_created_utc"] = datetime.now(timezone.utc).isoformat()
    target["bm_measurement_logic"] = "middle_reference_times_factor_plus_optional_difference"
    target["bm_arc_zero"] = "neutral"
    target["bm_mcp_opening"] = "angular_z_about_fixed_metacarpal_base"
    return target, target_modifier


def _validate(
    source_core_counts,
    source_finger_counts,
    source_obj,
    target_obj,
    target_modifier,
    facade,
    adapter,
    core,
):
    target_obj.update_tag()
    bpy.context.view_layer.update()
    neutral = _evaluated_geometry(target_obj)
    if neutral["vertices"] == 0 or neutral["polygons"] == 0:
        raise RuntimeError("V3.1 produced empty geometry")

    source = _evaluated_geometry(source_obj)
    if (
        neutral["vertices"],
        neutral["edges"],
        neutral["polygons"],
    ) != (
        source["vertices"],
        source["edges"],
        source["polygons"],
    ):
        raise RuntimeError("V3.1 unexpectedly changed mesh topology")

    responses = {}
    tests = {
        "long_proximal_global": SEGMENTS["proximal"]["reference"] + 2.0,
        "long_middle_global": SEGMENTS["middle"]["reference"] + 2.0,
        "long_distal_global": SEGMENTS["distal"]["reference"] + 2.0,
        "mcp_lateral_pair": float(
            _semantic_values(target_modifier)["mcp_lateral_pair"]
        )
        + 5.0,
        "palmar_arc_global": 5.0,
        "wrist_deviation": 0.0,
    }
    original_values = _semantic_values(target_modifier)
    for control_id, test_value in tests.items():
        _set_semantic(target_modifier, control_id, test_value)
        target_obj.update_tag()
        bpy.context.view_layer.update()
        tested = _evaluated_geometry(target_obj)
        delta = _max_delta(neutral, tested)
        if not math.isfinite(delta) or delta <= 1e-6:
            raise RuntimeError(f"V3.1 control did not respond: {control_id}")
        responses[control_id] = delta
        _set_semantic(target_modifier, control_id, original_values[control_id])

    target_obj.update_tag()
    bpy.context.view_layer.update()
    restored = _max_delta(neutral, _evaluated_geometry(target_obj))
    if restored > 1e-5:
        raise RuntimeError(f"V3.1 smoke tests did not restore values: {restored}")

    for finger_id in FINGERS:
        if abs(adapter.nodes[f"V3_ArcBase_{finger_id}"].outputs[0].default_value) > 1e-9:
            raise RuntimeError(f"Non-neutral arc baseline remains on {finger_id}")

    if tuple(source_core_counts) != (
        len(bpy.data.node_groups[SOURCE_CORE].nodes),
        len(bpy.data.node_groups[SOURCE_CORE].links),
        len(_inputs(bpy.data.node_groups[SOURCE_CORE])),
    ):
        raise RuntimeError("Shared Biomodelo_v2 was modified")
    if tuple(source_finger_counts) != (
        len(bpy.data.node_groups[SOURCE_FINGER].nodes),
        len(bpy.data.node_groups[SOURCE_FINGER].links),
        len(_inputs(bpy.data.node_groups[SOURCE_FINGER])),
    ):
        raise RuntimeError("Shared BM_Dedo_Longo was modified")

    values = _semantic_values(target_modifier)
    for segment in SEGMENTS.values():
        if abs(float(values[segment["reference_id"]]) - segment["reference"]) > 1e-5:
            raise RuntimeError("Reference measurement migration failed")
    if abs(float(values["wrist_flexion_legacy"])) > 1e-7:
        raise RuntimeError("Legacy wrist flexion did not reset to neutral")

    wrist_parent = _semantic_item(facade, "wrist_deviation").parent
    if wrist_parent is None or wrist_parent.name != "4. Punho, abertura e arco da palma":
        raise RuntimeError("Wrist deviation was not moved to group 4")

    return {
        "object": target_obj.name,
        "facade": facade.name,
        "adapter": adapter.name,
        "core": core.name,
        "vertices": neutral["vertices"],
        "edges": neutral["edges"],
        "polygons": neutral["polygons"],
        "restored_delta": restored,
        "response_max_deltas": responses,
        "reference_lengths_mm": {
            segment_id: data["reference"] for segment_id, data in SEGMENTS.items()
        },
        "anthropometric_factors": FACTORS,
        "wrist_deviation": values["wrist_deviation"],
        "legacy_wrist_flexion": values["wrist_flexion_legacy"],
        "mcp_angular_pair": values["mcp_lateral_pair"],
        "arc_master": values["palmar_arc_global"],
    }


def patch_live():
    _assert_targets_absent()
    required_groups = (
        SOURCE_FACADE,
        SOURCE_ADAPTER,
        SOURCE_CORE,
        SOURCE_FINGER,
        SOURCE_ARC,
    )
    missing = [name for name in required_groups if bpy.data.node_groups.get(name) is None]
    source_obj = bpy.data.objects.get(SOURCE_OBJECT)
    if source_obj is None:
        missing.append(SOURCE_OBJECT)
    if missing:
        raise RuntimeError("Missing V3.1 sources: " + ", ".join(missing))

    source_modifier = _source_modifier(source_obj)
    current_values = _semantic_values(source_modifier)
    source_core = bpy.data.node_groups[SOURCE_CORE]
    source_finger = bpy.data.node_groups[SOURCE_FINGER]
    source_core_counts = (
        len(source_core.nodes),
        len(source_core.links),
        len(_inputs(source_core)),
    )
    source_finger_counts = (
        len(source_finger.nodes),
        len(source_finger.links),
        len(_inputs(source_finger)),
    )

    created = []
    created_objects = []
    try:
        angular = _build_angular_matrix_group(created)
        finger = _build_finger_group(angular, created)
        core = _build_core(finger, created)
        adapter = _build_adapter(core, created)
        facade = _build_facade(adapter, created)
        target_obj, target_modifier = _build_object(
            facade,
            source_obj,
            source_modifier,
            current_values,
            created_objects,
        )
        validation = _validate(
            source_core_counts,
            source_finger_counts,
            source_obj,
            target_obj,
            target_modifier,
            facade,
            adapter,
            core,
        )

        source_obj["bm_successor"] = TARGET_OBJECT
        source_obj.hide_set(True)
        source_obj.hide_render = True
        target_obj.hide_set(False)
        target_obj.hide_render = False
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        target_obj.select_set(True)
        bpy.context.view_layer.objects.active = target_obj

        target_obj["bm_validation"] = json.dumps(validation, ensure_ascii=False, sort_keys=True)
        bpy.context.view_layer.update()
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
        validation["saved_to"] = bpy.data.filepath
        validation["source_hidden_as_rollback"] = SOURCE_OBJECT
        return validation
    except Exception:
        for obj in reversed(created_objects):
            if obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        for group in reversed(created):
            if group.name in bpy.data.node_groups:
                bpy.data.node_groups.remove(group, do_unlink=True)
        raise


if __name__ == "__main__":
    print(json.dumps(patch_live(), indent=2, ensure_ascii=False))
