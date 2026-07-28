"""Build V3.2 with a truthful zero pose based on the flat BM_v2_DEV scan."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import bpy


SOURCE_OBJECT = "BM_AJUSTE_SCAN_BASE_v3_1"
SOURCE_FACADE = "BM_AjusteScan_v3_1"
SOURCE_ADAPTER = "BM_AS_Nucleo_Clinico_v3_1"
MODEL_CORE = "Biomodelo_v3_1"
CANONICAL_OBJECT = "BM_v2_DEV"
CANONICAL_CORE = "Biomodelo_v2"

TARGET_OBJECT = "BM_AJUSTE_SCAN_BASE_v3_2"
TARGET_FACADE = "BM_AjusteScan_v3_2"
TARGET_ADAPTER = "BM_AS_Nucleo_Clinico_v3_2"

FINGERS = {
    "index": "Indicador",
    "middle": "Médio",
    "ring": "Anelar",
    "little": "Mindinho",
}

JOINTS = {
    "mcp": ("proximal", "MCP"),
    "pip": ("média", "PIP"),
    "dip": ("distal", "DIP"),
}

POSE_CONTROLS = {
    "mcp_flexion_global",
    "pip_flexion_global",
    "dip_flexion_global",
    "finger_opening",
    "mcp_lateral_pair",
    "palm_curve_radial",
    "palm_curve_ulnar",
    "palmar_arc_global",
    "thumb_opposition",
    "thumb_cmc_flexion",
    "thumb_cmc_abduction",
    "thumb_mcp_flexion",
    "thumb_ip_flexion",
    "thumb_cmc_radial",
    "thumb_cmc_palmar",
    "thumb_proximal_palmar",
    "thumb_distal_palmar",
    "thumb_cmc_longitudinal",
    "mcp_arch",
    "metacarpal_radial_global",
    "wrist_deviation",
    "wrist_flexion_legacy",
    "metacarpal_setback_legacy",
}
for finger_id in FINGERS:
    POSE_CONTROLS.update(
        {
            f"{finger_id}_mcp_flexion",
            f"{finger_id}_pip_flexion",
            f"{finger_id}_dip_flexion",
            f"{finger_id}_abduction",
            f"{finger_id}_mcp_lateral",
            f"{finger_id}_palmar_arc",
            f"{finger_id}_mcp_advance",
        }
    )


def _inputs(tree):
    return [
        item
        for item in tree.interface.items_tree
        if getattr(item, "item_type", "") == "SOCKET"
        and getattr(item, "in_out", "") == "INPUT"
    ]


def _panel(tree, name):
    for item in tree.interface.items_tree:
        if getattr(item, "item_type", "") == "PANEL" and item.name == name:
            return item
    raise KeyError(f"{tree.name}: panel not found: {name}")


def _semantic_map(tree):
    return json.loads(tree.get("semantic_input_identifiers", "{}"))


def _semantic_item(tree, control_id):
    identifier = _semantic_map(tree)[control_id]
    for item in _inputs(tree):
        if item.identifier == identifier:
            return item
    raise KeyError(f"{tree.name}: semantic item not found: {control_id}")


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


def _semantic_values(modifier):
    return {
        control_id: _modifier_get(modifier, identifier)
        for control_id, identifier in _semantic_map(modifier.node_group).items()
    }


def _set_semantic(modifier, control_id, value):
    _modifier_set(
        modifier,
        _semantic_map(modifier.node_group)[control_id],
        value,
    )


def _unlink(tree, socket):
    for link in list(socket.links):
        tree.links.remove(link)


def _modifier_for(obj, group_name):
    return next(
        (
            modifier
            for modifier in obj.modifiers
            if modifier.type == "NODES"
            and modifier.node_group
            and modifier.node_group.name == group_name
        ),
        None,
    )


def _canonical_values():
    obj = bpy.data.objects[CANONICAL_OBJECT]
    modifier = _modifier_for(obj, CANONICAL_CORE)
    if modifier is None:
        raise RuntimeError("BM_v2_DEV raw modifier not found")
    return {
        item.name: _modifier_get(modifier, item.identifier)
        for item in _inputs(modifier.node_group)
    }


def _value_node(tree, name, value, label):
    node = tree.nodes.new("ShaderNodeValue")
    node.name = name
    node.label = label
    node.outputs[0].default_value = float(value)
    return node


def _add_node(tree, name, baseline, label):
    node = tree.nodes.new("ShaderNodeMath")
    node.name = name
    node.label = label
    node.operation = "ADD"
    node.inputs[1].default_value = float(baseline)
    return node


def _link_baseline(tree, source, target, baseline, name, label):
    _unlink(tree, target)
    if abs(float(baseline)) <= 1e-12:
        tree.links.new(source, target)
        return None
    node = _add_node(tree, name, baseline, label)
    tree.links.new(source, node.inputs[0])
    tree.links.new(node.outputs[0], target)
    return node


def _link_constant(tree, target, value, name, label):
    _unlink(tree, target)
    target.default_value = float(value)
    node = _value_node(tree, name, value, label)
    tree.links.new(node.outputs[0], target)
    return node


def _geometry(obj):
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


def _assert_absent():
    occupied = []
    if bpy.data.objects.get(TARGET_OBJECT):
        occupied.append(TARGET_OBJECT)
    for name in (TARGET_FACADE, TARGET_ADAPTER):
        if bpy.data.node_groups.get(name):
            occupied.append(name)
    if occupied:
        raise RuntimeError("V3.2 target names already exist: " + ", ".join(occupied))


def _rebuild_pose_adapter(adapter, canonical):
    group_input = adapter.nodes["Entradas_Clinicas"]
    core = adapter.nodes["Nucleo_Biomodelo_v3_1"]
    core.label = "Núcleo V3.1 — neutro clínico V3.2"

    def output(name):
        socket = group_input.outputs.get(name)
        if socket is None:
            raise KeyError(f"Adapter input missing: {name}")
        return socket

    # Global long-finger pose: zero is the canonical flat scan.
    global_links = (
        (
            "Flexão MCP global",
            "Dedos - Flex/Ext proximal geral",
            canonical["Dedos - Flex/Ext proximal geral"],
            "MCP",
        ),
        (
            "Flexão PIP global",
            "Dedos - Flex/Ext média geral",
            canonical["Dedos - Flex/Ext média geral"],
            "PIP",
        ),
        (
            "Abertura dos dedos",
            "Dedos - Abdução geral",
            canonical["Dedos - Abdução geral"],
            "abertura",
        ),
        (
            "MCP - curvatura do arco",
            "Dedos - Curvatura arco MCP",
            canonical["Dedos - Curvatura arco MCP"],
            "fileira MCP",
        ),
        (
            "Desvio radial/ulnar do punho",
            "Desvio Rad/Ulnar Punho",
            canonical["Desvio Rad/Ulnar Punho"],
            "desvio do punho",
        ),
        (
            "Flexão/extensão do punho",
            "Flex/Ext Punho",
            canonical["Flex/Ext Punho"],
            "flexão legada do punho",
        ),
        (
            "Metacarpos - recuo global",
            "Metacarpos - Recuo geral",
            canonical["Metacarpos - Recuo geral"],
            "recuo metacarpal",
        ),
        (
            "V3::metacarpal_radial_global",
            "Metacarpos - Radial geral",
            canonical["Metacarpos - Radial geral"],
            "radial metacarpal",
        ),
    )
    for index, (source_name, target_name, baseline, label) in enumerate(global_links):
        node = _link_baseline(
            adapter,
            output(source_name),
            core.inputs[target_name],
            baseline,
            f"V32_GlobalNeutral_{index:02d}",
            f"neutro BM_v2_DEV + {label}",
        )
        if node:
            node.location = (760, 980 - index * 120)

    # Keep automatic DIP coupling from the existing adapter. With auto off and
    # the public DIP at zero, the raw distal global is also zero.
    _link_constant(
        adapter,
        core.inputs["Dedos - Avanço MCP geral"],
        canonical["Dedos - Avanço MCP geral"],
        "V32_AdvanceGlobalNeutral",
        "avanço geral canônico",
    )
    _link_constant(
        adapter,
        core.inputs["Dedos - Lateral MCP geral"],
        canonical["Dedos - Lateral MCP geral"],
        "V32_LateralGlobalNeutral",
        "translação lateral geral aposentada",
    )
    _link_constant(
        adapter,
        core.inputs["Metacarpos - Arco Z geral"],
        canonical["Metacarpos - Arco Z geral"],
        "V32_ArcGlobalNeutral",
        "arco global bruto neutro",
    )

    for finger_index, (finger_id, label) in enumerate(FINGERS.items()):
        for joint_index, (joint_id, (raw_suffix, public_suffix)) in enumerate(
            JOINTS.items()
        ):
            _link_baseline(
                adapter,
                output(f"V3::{finger_id}_{joint_id}_flexion"),
                core.inputs[f"{label} - Flex/Ext {raw_suffix}"],
                canonical[f"{label} - Flex/Ext {raw_suffix}"],
                f"V32_FlexNeutral_{finger_id}_{joint_id}",
                f"{label} {public_suffix}: canônico + ajuste",
            )
        _link_baseline(
            adapter,
            output(f"V3::{finger_id}_abduction"),
            core.inputs[f"{label} - Abdução"],
            canonical[f"{label} - Abdução"],
            f"V32_AbductionNeutral_{finger_id}",
            f"{label}: abertura canônica + ajuste",
        )
        _link_baseline(
            adapter,
            output(f"V3::{finger_id}_mcp_advance"),
            core.inputs[f"{label} - Avanço MCP"],
            canonical[f"{label} - Avanço MCP"],
            f"V32_AdvanceNeutral_{finger_id}",
            f"{label}: avanço canônico + ajuste",
        )
        _link_constant(
            adapter,
            core.inputs[f"{label} - Lateral MCP"],
            canonical[f"{label} - Lateral MCP"],
            f"V32_LateralNeutral_{finger_id}",
            f"{label}: sem translação lateral oculta",
        )
        _link_constant(
            adapter,
            core.inputs[f"{label} - Recuo"],
            canonical[f"{label} - Recuo"],
            f"V32_SetbackNeutral_{finger_id}",
            f"{label}: recuo canônico",
        )
        _link_constant(
            adapter,
            core.inputs[f"{label} - Radial"],
            canonical[f"{label} - Radial"],
            f"V32_RadialNeutral_{finger_id}",
            f"{label}: radial canônico",
        )

        calibration_suffixes = (
            "Curvatura fator",
            "X fator",
            "Arco fator",
            "Coroa Y",
            "Direcao Abd",
            "Arco Z peso",
            "Largura fator",
            "Radial sinal",
        )
        for suffix in calibration_suffixes:
            target = core.inputs[f"{label} - {suffix}"]
            _unlink(adapter, target)
            target.default_value = canonical[f"{label} - {suffix}"]

    # MCP clearance must follow the current head radius, not a fixed 18 mm hand.
    finger_size_target = core.inputs["Dedos - Tamanho"]
    if not finger_size_target.is_linked:
        raise RuntimeError("Clinical finger thickness derivation is missing")
    finger_size_source = finger_size_target.links[0].from_socket
    clearance_target = core.inputs["Folga MCP base (mm)"]
    _unlink(adapter, clearance_target)
    clearance = adapter.nodes.new("ShaderNodeMath")
    clearance.name = "V32_MCP_ClearanceFromCurrentRadius"
    clearance.label = "folga base = espessura atual × 0,492"
    clearance.operation = "MULTIPLY"
    clearance.inputs[1].default_value = 0.492
    clearance.location = (820, -760)
    adapter.links.new(finger_size_source, clearance.inputs[0])
    adapter.links.new(clearance.outputs[0], clearance_target)

    # Thumb: visible zero means the canonical flat-scan pose. All old hidden
    # V1 correction offsets are bypassed.
    thumb_links = (
        ("Oposição do polegar", "Polegar - Oposição", "Polegar - Oposição"),
        (
            "Flexão do metacarpo do polegar (CMC)",
            "Flex/Ext Polegar",
            "Flex/Ext Polegar",
        ),
        (
            "Abdução/adução palmar do polegar (CMC)",
            "Abdução Polegar",
            "Abdução Polegar",
        ),
        (
            "Flexão MCP do polegar",
            "Flex/Ext Falange Prox Polegar",
            "Flex/Ext Falange Prox Polegar",
        ),
        (
            "Flexão IP do polegar",
            "Flex/Ext Falange Dist Polegar",
            "Flex/Ext Falange Dist Polegar",
        ),
        ("V3::thumb_cmc_radial", "Polegar - CMC radial", "Polegar - CMC radial"),
        ("V3::thumb_cmc_palmar", "Polegar - CMC baixar", "Polegar - CMC baixar"),
        (
            "V3::thumb_proximal_palmar",
            "Polegar - Palmar falange prox",
            "Polegar - Palmar falange prox",
        ),
        (
            "V3::thumb_distal_palmar",
            "Polegar - Palmar falange dist",
            "Polegar - Palmar falange dist",
        ),
        (
            "V3::thumb_cmc_longitudinal",
            "Polegar - CMC recuo",
            "Polegar - CMC recuo",
        ),
    )
    for index, (source_name, target_name, canonical_name) in enumerate(thumb_links):
        node = _link_baseline(
            adapter,
            output(source_name),
            core.inputs[target_name],
            canonical[canonical_name],
            f"V32_ThumbNeutral_{index:02d}",
            f"polegar canônico + ajuste: {target_name}",
        )
        if node:
            node.location = (1120, 620 - index * 115)

    _link_constant(
        adapter,
        core.inputs["Polegar - Ângulo palmar"],
        canonical["Polegar - Ângulo palmar"],
        "V32_ThumbPalmarAngleNeutral",
        "ângulo palmar canônico do scan espalmado",
    )
    for name in (
        "Polegar - Largura MC fator",
        "Polegar - Largura falange prox fator",
        "Polegar - Largura falange dist fator",
        "Polegar - CMC X fator",
        "Polegar - CMC Y offset (mm)",
    ):
        target = core.inputs[name]
        _unlink(adapter, target)
        target.default_value = canonical[name]

    adapter["schema_version"] = 11
    adapter["neutral_reference"] = CANONICAL_OBJECT
    adapter["visible_zero_semantics"] = "canonical_flat_scan_pose"
    adapter["hidden_v1_pose_offsets"] = "retired"
    adapter["mcp_clearance_formula"] = "current_finger_thickness * 0.492 + 2.5"


def _build_facade(adapter):
    facade = bpy.data.node_groups[SOURCE_FACADE].copy()
    facade.name = TARGET_FACADE
    facade.use_fake_user = True
    facade.description = (
        "Painel clínico V3.2: zero de pose reproduz a mão espalmada canônica; "
        "sem offsets V1 ocultos."
    )
    inner = facade.nodes["Nucleo_Clinico_V3_1"]
    inner.node_tree = adapter
    inner.name = "Nucleo_Clinico_V3_2"
    inner.label = "Neutro clínico V3.2"

    opening_panel = _panel(facade, "4. Punho, abertura e arco da palma")
    arc = _semantic_item(facade, "palmar_arc_global")
    wrist = _semantic_item(facade, "wrist_deviation")
    facade.interface.move_to_parent(arc, opening_panel, 0)
    facade.interface.move_to_parent(wrist, opening_panel, 1)

    for control_id in POSE_CONTROLS:
        item = _semantic_item(facade, control_id)
        if hasattr(item, "default_value"):
            item.default_value = 0.0
        suffix = " 0 = pose espalmada de referência."
        if suffix.strip() not in item.description:
            item.description = (item.description.rstrip() + suffix).strip()

    facade["schema_version"] = 11
    facade["architecture"] = "clinical_scan_facade_v3_2"
    facade["adapter"] = TARGET_ADAPTER
    facade["model_core"] = MODEL_CORE
    facade["contract_file"] = "presets/biomodel_clinical_patch_v3_2.json"
    return facade


def _build_object(facade, source_obj, source_modifier, current_values):
    target = source_obj.copy()
    target.data = source_obj.data.copy() if source_obj.data else None
    target.name = TARGET_OBJECT
    target.animation_data_clear()

    registry = bpy.data.collections.get("BIOMODELOS_CLINICOS")
    if registry is None:
        registry = bpy.data.collections.new("BIOMODELOS_CLINICOS")
        bpy.context.scene.collection.children.link(registry)
    registry.objects.link(target)

    modifier = _modifier_for(target, SOURCE_FACADE)
    if modifier is None:
        raise RuntimeError("Copied V3.1 modifier not found")
    modifier.node_group = facade
    modifier.name = "Painel Clínico V3.2"

    for control_id, value in current_values.items():
        if control_id in _semantic_map(facade):
            _set_semantic(modifier, control_id, value)
    for control_id in POSE_CONTROLS:
        _set_semantic(modifier, control_id, 0.0)
    _set_semantic(modifier, "dip_auto", False)

    target["bm_version"] = "3.2"
    target["bm_schema_version"] = 11
    target["bm_facade"] = TARGET_FACADE
    target["bm_adapter"] = TARGET_ADAPTER
    target["bm_core"] = MODEL_CORE
    target["bm_source_object"] = SOURCE_OBJECT
    target["bm_neutral_reference"] = CANONICAL_OBJECT
    target["bm_zero_pose"] = "canonical_flat_scan"
    target["bm_created_utc"] = datetime.now(timezone.utc).isoformat()
    return target, modifier


def _validate(target, modifier, facade, adapter):
    target.update_tag()
    bpy.context.view_layer.update()
    neutral = _geometry(target)
    if neutral["vertices"] != 1762 or neutral["polygons"] != 1812:
        raise RuntimeError(
            "Unexpected V3.2 topology: "
            f"{neutral['vertices']} vertices, {neutral['polygons']} polygons"
        )

    values = _semantic_values(modifier)
    nonzero = {
        control_id: values[control_id]
        for control_id in POSE_CONTROLS
        if abs(float(values[control_id])) > 1e-7
    }
    if nonzero:
        raise RuntimeError(f"V3.2 pose controls are not neutral: {nonzero}")

    tests = {
        "mcp_flexion_global": 10.0,
        "thumb_mcp_flexion": 10.0,
        "palmar_arc_global": 5.0,
        "mcp_lateral_pair": 5.0,
    }
    responses = {}
    for control_id, test_value in tests.items():
        _set_semantic(modifier, control_id, test_value)
        target.update_tag()
        bpy.context.view_layer.update()
        delta = _max_delta(neutral, _geometry(target))
        if not math.isfinite(delta) or delta <= 1e-6:
            raise RuntimeError(f"V3.2 control did not respond: {control_id}")
        responses[control_id] = delta
        _set_semantic(modifier, control_id, 0.0)

    target.update_tag()
    bpy.context.view_layer.update()
    restored = _max_delta(neutral, _geometry(target))
    if restored > 1e-5:
        raise RuntimeError(f"V3.2 tests did not restore neutral: {restored}")

    opening_panel = _panel(facade, "4. Punho, abertura e arco da palma")
    top_level_names = [
        item.name
        for item in facade.interface.items_tree
        if getattr(item, "item_type", "") == "SOCKET"
        and item.parent == opening_panel
    ]
    if not top_level_names or top_level_names[0] != "Flexão/extensão do arco da mão":
        raise RuntimeError(f"Arc is not first in group 4: {top_level_names}")

    core = adapter.nodes["Nucleo_Biomodelo_v3_1"]
    clearance = core.inputs["Folga MCP base (mm)"]
    if not clearance.is_linked or (
        clearance.links[0].from_node.name != "V32_MCP_ClearanceFromCurrentRadius"
    ):
        raise RuntimeError("Dynamic MCP clearance is not connected")

    return {
        "object": target.name,
        "facade": facade.name,
        "adapter": adapter.name,
        "vertices": neutral["vertices"],
        "edges": neutral["edges"],
        "polygons": neutral["polygons"],
        "restored_delta": restored,
        "responses": responses,
        "pose_controls_at_zero": len(POSE_CONTROLS),
        "group_4_order": top_level_names,
        "neutral_reference": CANONICAL_OBJECT,
        "mcp_clearance": "finger_thickness * 0.492 + 2.5",
    }


def patch_live():
    _assert_absent()
    for group_name in (SOURCE_FACADE, SOURCE_ADAPTER, MODEL_CORE, CANONICAL_CORE):
        if bpy.data.node_groups.get(group_name) is None:
            raise RuntimeError(f"Missing source group: {group_name}")
    source_obj = bpy.data.objects.get(SOURCE_OBJECT)
    if source_obj is None:
        raise RuntimeError(f"Missing source object: {SOURCE_OBJECT}")
    if bpy.data.objects.get(CANONICAL_OBJECT) is None:
        raise RuntimeError(f"Missing canonical object: {CANONICAL_OBJECT}")
    source_modifier = _modifier_for(source_obj, SOURCE_FACADE)
    if source_modifier is None:
        raise RuntimeError("V3.1 clinical modifier not found")

    current_values = _semantic_values(source_modifier)
    canonical = _canonical_values()
    created_groups = []
    created_objects = []
    try:
        adapter = bpy.data.node_groups[SOURCE_ADAPTER].copy()
        adapter.name = TARGET_ADAPTER
        adapter.use_fake_user = True
        adapter.description = (
            "V3.2 neutral adapter calibrated from the flat BM_v2_DEV reference."
        )
        created_groups.append(adapter)
        _rebuild_pose_adapter(adapter, canonical)

        facade = _build_facade(adapter)
        created_groups.append(facade)

        target, modifier = _build_object(
            facade,
            source_obj,
            source_modifier,
            current_values,
        )
        created_objects.append(target)
        validation = _validate(target, modifier, facade, adapter)

        source_obj["bm_successor"] = TARGET_OBJECT
        source_obj.hide_set(True)
        source_obj.hide_render = True
        target.hide_set(False)
        target.hide_render = False
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        target.select_set(True)
        bpy.context.view_layer.objects.active = target
        target["bm_validation"] = json.dumps(
            validation,
            ensure_ascii=False,
            sort_keys=True,
        )
        bpy.context.view_layer.update()
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
        validation["saved_to"] = bpy.data.filepath
        validation["source_hidden_as_rollback"] = SOURCE_OBJECT
        return validation
    except Exception:
        for obj in reversed(created_objects):
            if obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        for group in reversed(created_groups):
            if group.name in bpy.data.node_groups:
                bpy.data.node_groups.remove(group, do_unlink=True)
        raise


if __name__ == "__main__":
    print(json.dumps(patch_live(), indent=2, ensure_ascii=False))
