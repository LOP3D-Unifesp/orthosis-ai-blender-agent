"""Add independent wrist width/thickness to the V3.4 clinical biomodel."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import bpy


SOURCE_OBJECT = "BM_AJUSTE_SCAN_BASE_v3_4"
TARGET_OBJECT = "BM_AJUSTE_SCAN_BASE_v3_5"
TARGET_FACADE = "BM_AjusteScan_v3_5"
TARGET_ADAPTER = "BM_AS_Nucleo_Clinico_v3_5"
TARGET_CORE = "Biomodelo_v3_5"
TARGET_FOREARM = "BM_Antebraco_Punho_v3_5"

WIDTH_ID = "wrist_width"
THICKNESS_ID = "wrist_thickness"
WIDTH_INTERNAL = "V35::wrist_width"
THICKNESS_INTERNAL = "V35::wrist_thickness"
WIDTH_CORE_INPUT = "Antebraço - Largura do punho"
THICKNESS_CORE_INPUT = "Antebraço - Espessura do punho"
WIDTH_FOREARM_INPUT = "Largura do punho"
THICKNESS_FOREARM_INPUT = "Espessura do punho"


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
    raise KeyError(f"{tree.name}: semantic input not found: {control_id}")


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


def _group_input(tree, preferred=None):
    if preferred:
        node = tree.nodes.get(preferred)
        if node and node.bl_idname == "NodeGroupInput":
            return node
    return next(node for node in tree.nodes if node.bl_idname == "NodeGroupInput")


def _find_nested(tree, target=None, prefix=None):
    nodes = [
        node
        for node in tree.nodes
        if node.bl_idname == "GeometryNodeGroup" and node.node_tree
    ]
    if target:
        for node in nodes:
            if node.node_tree == target:
                return node
    if prefix:
        for node in nodes:
            if node.name.startswith(prefix):
                return node
    if len(nodes) == 1:
        return nodes[0]
    raise RuntimeError(f"Nested group node not resolved in {tree.name}")


def _new_float(
    tree,
    name,
    default,
    minimum=20.0,
    maximum=150.0,
    description="",
):
    item = tree.interface.new_socket(
        name=name,
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    item.default_value = float(default)
    item.min_value = float(minimum)
    item.max_value = float(maximum)
    item.subtype = "DISTANCE"
    item.description = description
    return item


def _math(tree, name, operation, label, location):
    node = tree.nodes.new("ShaderNodeMath")
    node.name = name
    node.label = label
    node.operation = operation
    node.location = location
    return node


def _source():
    obj = bpy.context.view_layer.objects.active
    if obj is None or obj.name != SOURCE_OBJECT:
        obj = bpy.data.objects.get(SOURCE_OBJECT)
    if obj is None:
        raise RuntimeError(f"Source object missing: {SOURCE_OBJECT}")
    modifier = next(
        (
            modifier
            for modifier in obj.modifiers
            if modifier.type == "NODES"
            and modifier.node_group
            and modifier.node_group.name.startswith("BM_AjusteScan_v3_4")
        ),
        None,
    )
    if modifier is None:
        raise RuntimeError("V3.4 clinical modifier not found")
    facade = modifier.node_group
    adapter_node = _find_nested(facade, prefix="Nucleo_Clinico")
    adapter = adapter_node.node_tree
    core_node = _find_nested(adapter, prefix="Nucleo_Biomodelo")
    core = core_node.node_tree
    forearm_node = core.nodes["M01_Antebraco_Punho"]
    return {
        "object": obj,
        "modifier": modifier,
        "facade": facade,
        "adapter": adapter,
        "adapter_core_node": core_node,
        "core": core,
        "forearm": forearm_node.node_tree,
    }


def _current_wrist_dimensions(source, values):
    core_node = source["adapter_core_node"]
    factor_socket = core_node.inputs["Carpo - Raio (x punho)"]
    if factor_socket.is_linked:
        raise RuntimeError("Carpal radius factor is unexpectedly linked")
    radius_factor = float(factor_socket.default_value)
    scale = source["forearm"].nodes["Vec_Carpo_Scale"]
    x_socket = scale.inputs["X"]
    y_socket = scale.inputs["Y"]
    if x_socket.is_linked or y_socket.is_linked:
        raise RuntimeError("V3.4 carpal cross-section is unexpectedly linked")
    diameter = float(values["wrist_perimeter"]) / math.pi * radius_factor
    return (
        diameter * float(x_socket.default_value),
        diameter * float(y_socket.default_value),
    )


def _build_forearm(source_tree, width, thickness):
    tree = source_tree.copy()
    tree.name = TARGET_FOREARM
    tree.use_fake_user = True
    tree.description = (
        "Antebraço V3.5: largura/espessura independentes no punho e na "
        "base proximal, com transição linear entre as seções."
    )
    width_item = _new_float(
        tree,
        WIDTH_FOREARM_INPUT,
        width,
        description="Largura medial-lateral absoluta do punho.",
    )
    thickness_item = _new_float(
        tree,
        THICKNESS_FOREARM_INPUT,
        thickness,
        description="Espessura palmar-dorsal absoluta do punho.",
    )
    group_input = tree.nodes.new("NodeGroupInput")
    group_input.name = "GI_V35_WristDimensions"
    group_input.label = "V3.5 — largura e espessura do punho"
    group_input.location = (80, 900)

    wrist_radius = tree.nodes["Punho_raio"].outputs[0]
    carpal_radius = tree.nodes["Carpo_raio"].outputs[0]

    wrist_diameter = _math(
        tree,
        "V35_WristCircleDiameter",
        "MULTIPLY",
        "diâmetro circular do punho",
        (280, 1020),
    )
    wrist_diameter.inputs[1].default_value = 2.0
    wrist_flat_diameter = _math(
        tree,
        "V35_WristFlatDiameter",
        "MULTIPLY",
        "espessura-base achatada 0,8",
        (280, 860),
    )
    wrist_flat_diameter.inputs[1].default_value = 1.6
    wrist_width_scale = _math(
        tree,
        "V35_WristWidthScale",
        "DIVIDE",
        "largura do punho ÷ diâmetro-base",
        (500, 1020),
    )
    wrist_thickness_scale = _math(
        tree,
        "V35_WristThicknessScale",
        "DIVIDE",
        "espessura do punho ÷ espessura-base",
        (500, 860),
    )
    tree.links.new(wrist_radius, wrist_diameter.inputs[0])
    tree.links.new(wrist_radius, wrist_flat_diameter.inputs[0])
    tree.links.new(
        group_input.outputs[width_item.name],
        wrist_width_scale.inputs[0],
    )
    tree.links.new(wrist_diameter.outputs[0], wrist_width_scale.inputs[1])
    tree.links.new(
        group_input.outputs[thickness_item.name],
        wrist_thickness_scale.inputs[0],
    )
    tree.links.new(
        wrist_flat_diameter.outputs[0],
        wrist_thickness_scale.inputs[1],
    )

    # V3.4 used 1 + (proximal_scale - 1) * progress. V3.5 changes
    # this to wrist_scale + (proximal_scale - wrist_scale) * progress.
    width_delta = tree.nodes["V33_WidthDelta"]
    width_final = tree.nodes["V33_WidthFinal"]
    thickness_delta = tree.nodes["V33_ThicknessDelta"]
    thickness_final = tree.nodes["V33_ThicknessFinal"]
    _unlink(tree, width_delta.inputs[1])
    _unlink(tree, width_final.inputs[1])
    _unlink(tree, thickness_delta.inputs[1])
    _unlink(tree, thickness_final.inputs[1])
    tree.links.new(wrist_width_scale.outputs[0], width_delta.inputs[1])
    tree.links.new(wrist_width_scale.outputs[0], width_final.inputs[1])
    tree.links.new(
        wrist_thickness_scale.outputs[0],
        thickness_delta.inputs[1],
    )
    tree.links.new(
        wrist_thickness_scale.outputs[0],
        thickness_final.inputs[1],
    )
    width_delta.label = "escala proximal − escala do punho"
    width_final.label = "interpola punho → base proximal"
    thickness_delta.label = "escala proximal − escala do punho"
    thickness_final.label = "interpola punho → base proximal"

    # The same absolute dimensions define the carpal sphere cross-section.
    carpal_diameter = _math(
        tree,
        "V35_CarpalDiameter",
        "MULTIPLY",
        "diâmetro-base da esfera do punho",
        (720, 1020),
    )
    carpal_diameter.inputs[1].default_value = 2.0
    carpal_width_scale = _math(
        tree,
        "V35_CarpalWidthScale",
        "DIVIDE",
        "largura absoluta da esfera",
        (920, 1020),
    )
    carpal_thickness_scale = _math(
        tree,
        "V35_CarpalThicknessScale",
        "DIVIDE",
        "espessura absoluta da esfera",
        (920, 860),
    )
    tree.links.new(carpal_radius, carpal_diameter.inputs[0])
    tree.links.new(
        group_input.outputs[width_item.name],
        carpal_width_scale.inputs[0],
    )
    tree.links.new(carpal_diameter.outputs[0], carpal_width_scale.inputs[1])
    tree.links.new(
        group_input.outputs[thickness_item.name],
        carpal_thickness_scale.inputs[0],
    )
    tree.links.new(
        carpal_diameter.outputs[0],
        carpal_thickness_scale.inputs[1],
    )
    carpal_scale = tree.nodes["Vec_Carpo_Scale"]
    _unlink(tree, carpal_scale.inputs["X"])
    _unlink(tree, carpal_scale.inputs["Y"])
    tree.links.new(carpal_width_scale.outputs[0], carpal_scale.inputs["X"])
    tree.links.new(
        carpal_thickness_scale.outputs[0],
        carpal_scale.inputs["Y"],
    )

    tree["schema_version"] = 14
    tree["wrist_dimensions"] = "independent_absolute_mm"
    tree["wrist_transition"] = "linear_wrist_to_proximal"
    tree["wrist_perimeter_precedence"] = "reference_only_when_dimensions_override"
    return tree


def _build_core(source_tree, forearm_tree, width, thickness):
    tree = source_tree.copy()
    tree.name = TARGET_CORE
    tree.use_fake_user = True
    tree.description = "Biomodelo V3.5 with independent wrist dimensions."
    width_item = _new_float(tree, WIDTH_CORE_INPUT, width)
    thickness_item = _new_float(tree, THICKNESS_CORE_INPUT, thickness)
    forearm_node = tree.nodes["M01_Antebraco_Punho"]
    forearm_node.node_tree = forearm_tree
    group_input = tree.nodes.new("NodeGroupInput")
    group_input.name = "GI_V35_WristDimensions"
    group_input.label = "V3.5 — dimensões do punho"
    group_input.location = (-820, 1500)
    tree.links.new(
        group_input.outputs[width_item.name],
        forearm_node.inputs[WIDTH_FOREARM_INPUT],
    )
    tree.links.new(
        group_input.outputs[thickness_item.name],
        forearm_node.inputs[THICKNESS_FOREARM_INPUT],
    )
    tree["schema_version"] = 14
    return tree


def _build_adapter(source_tree, old_core, core, width, thickness):
    tree = source_tree.copy()
    tree.name = TARGET_ADAPTER
    tree.use_fake_user = True
    tree.description = "Clinical V3.5 adapter with wrist width/thickness in mm."
    width_item = _new_float(tree, WIDTH_INTERNAL, width)
    thickness_item = _new_float(tree, THICKNESS_INTERNAL, thickness)
    group_input = _group_input(tree, "Entradas_Clinicas")
    core_node = _find_nested(tree, target=old_core)
    core_node.node_tree = core
    core_node.name = "Nucleo_Biomodelo_v3_5"
    core_node.label = "Núcleo V3.5"
    tree.links.new(
        group_input.outputs[width_item.name],
        core_node.inputs[WIDTH_CORE_INPUT],
    )
    tree.links.new(
        group_input.outputs[thickness_item.name],
        core_node.inputs[THICKNESS_CORE_INPUT],
    )
    tree["schema_version"] = 14
    return tree


def _build_facade(source_tree, old_adapter, adapter, width, thickness):
    tree = source_tree.copy()
    tree.name = TARGET_FACADE
    tree.use_fake_user = True
    tree.description = (
        "Painel clínico V3.5: largura e espessura independentes no punho."
    )
    measures = _panel(tree, "1. Medidas do indivíduo")
    width_item = _new_float(
        tree,
        "Punho — largura",
        width,
        description="Largura medial-lateral real do punho.",
    )
    thickness_item = _new_float(
        tree,
        "Punho — espessura",
        thickness,
        description="Espessura palmar-dorsal real do punho.",
    )
    tree.interface.move_to_parent(width_item, measures, 10_000)
    tree.interface.move_to_parent(thickness_item, measures, 10_000)

    mapping = _semantic_map(tree)
    mapping[WIDTH_ID] = width_item.identifier
    mapping[THICKNESS_ID] = thickness_item.identifier
    tree["semantic_input_identifiers"] = json.dumps(
        mapping,
        ensure_ascii=False,
        sort_keys=True,
    )

    ordered_ids = (
        "forearm_length",
        "elbow_perimeter",
        "wrist_perimeter",
    )
    ordered = [_semantic_item(tree, control_id) for control_id in ordered_ids]
    ordered.extend(
        (
            width_item,
            thickness_item,
            _semantic_item(tree, "wrist_flexion_legacy"),
            _semantic_item(tree, "forearm_pronation"),
            _semantic_item(tree, "forearm_base_width"),
            _semantic_item(tree, "forearm_base_thickness"),
            _semantic_item(tree, "left_member"),
            _semantic_item(tree, "wrist_to_mcp"),
            _semantic_item(tree, "palm_width"),
            _semantic_item(tree, "palm_thickness"),
        )
    )
    for index, item in enumerate(ordered):
        tree.interface.move_to_parent(item, measures, index)

    group_input = _group_input(tree)
    adapter_node = _find_nested(tree, target=old_adapter)
    adapter_node.node_tree = adapter
    adapter_node.name = "Nucleo_Clinico_V3_5"
    adapter_node.label = "Derivações clínicas V3.5"
    tree.links.new(
        group_input.outputs[width_item.name],
        adapter_node.inputs[WIDTH_INTERNAL],
    )
    tree.links.new(
        group_input.outputs[thickness_item.name],
        adapter_node.inputs[THICKNESS_INTERNAL],
    )
    tree["schema_version"] = 14
    tree["architecture"] = "clinical_scan_facade_v3_5"
    tree["adapter"] = TARGET_ADAPTER
    tree["model_core"] = TARGET_CORE
    tree["contract_file"] = "presets/biomodel_clinical_patch_v3_5.json"
    return tree


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


def _build_object(source, old_facade, facade, values, width, thickness):
    obj = source.copy()
    obj.data = source.data.copy() if source.data else None
    obj.name = TARGET_OBJECT
    obj.animation_data_clear()
    registry = bpy.data.collections.get("BIOMODELOS_CLINICOS")
    if registry is None:
        registry = bpy.data.collections.new("BIOMODELOS_CLINICOS")
        bpy.context.scene.collection.children.link(registry)
    registry.objects.link(obj)
    modifier = next(
        (
            modifier
            for modifier in obj.modifiers
            if modifier.type == "NODES" and modifier.node_group == old_facade
        ),
        None,
    )
    if modifier is None:
        raise RuntimeError("Copied V3.4 modifier not found")
    modifier.node_group = facade
    modifier.name = "Painel Clínico V3.5"
    for control_id, value in values.items():
        if control_id in _semantic_map(facade):
            _set_semantic(modifier, control_id, value)
    _set_semantic(modifier, WIDTH_ID, width)
    _set_semantic(modifier, THICKNESS_ID, thickness)
    obj["bm_version"] = "3.5"
    obj["bm_schema_version"] = 14
    obj["bm_facade"] = TARGET_FACADE
    obj["bm_adapter"] = TARGET_ADAPTER
    obj["bm_core"] = TARGET_CORE
    obj["bm_source_object"] = source.name
    obj["bm_created_utc"] = datetime.now(timezone.utc).isoformat()
    obj["bm_wrist_dimensions"] = "independent_width_thickness_mm"
    return obj, modifier


def _validate(source_obj, obj, modifier, facade):
    source_geometry = _geometry(source_obj)
    neutral = _geometry(obj)
    baseline_delta = _max_delta(source_geometry, neutral)
    if baseline_delta > 1e-3:
        raise RuntimeError(
            f"V3.5 did not preserve the current V3.4 shape: {baseline_delta}"
        )
    values = _semantic_values(modifier)
    tests = {
        WIDTH_ID: float(values[WIDTH_ID]) + 20.0,
        THICKNESS_ID: float(values[THICKNESS_ID]) + 20.0,
    }
    responses = {}
    for control_id, test_value in tests.items():
        original = values[control_id]
        _set_semantic(modifier, control_id, test_value)
        obj.update_tag()
        bpy.context.view_layer.update()
        tested = _geometry(obj)
        delta = _max_delta(neutral, tested)
        if not math.isfinite(delta) or delta <= 1e-6:
            raise RuntimeError(f"V3.5 control did not respond: {control_id}")
        responses[control_id] = delta
        _set_semantic(modifier, control_id, original)
    obj.update_tag()
    bpy.context.view_layer.update()
    restored = _max_delta(neutral, _geometry(obj))
    if restored > 1e-5:
        raise RuntimeError(f"V3.5 did not restore its baseline: {restored}")

    measures = _panel(facade, "1. Medidas do indivíduo")
    order = [
        item.name
        for item in facade.interface.items_tree
        if getattr(item, "item_type", "") == "SOCKET" and item.parent == measures
    ]
    expected = [
        "Comprimento do antebraço",
        "Perímetro proximal do antebraço",
        "Perímetro do punho",
        "Punho — largura",
        "Punho — espessura",
        "Flexão/extensão do punho",
        "Pronação/supinação da base proximal",
        "Base proximal — largura",
        "Base proximal — espessura",
    ]
    if order[:9] != expected:
        raise RuntimeError(f"Unexpected V3.5 group 1 order: {order}")
    return {
        "object": obj.name,
        "facade": facade.name,
        "vertices": neutral["vertices"],
        "edges": neutral["edges"],
        "polygons": neutral["polygons"],
        "baseline_delta": baseline_delta,
        "restored_delta": restored,
        "responses": responses,
        "group_1_order": order,
        "wrist_width_mm": values[WIDTH_ID],
        "wrist_thickness_mm": values[THICKNESS_ID],
    }


def patch_live():
    if bpy.data.objects.get(TARGET_OBJECT):
        raise RuntimeError(f"Target object already exists: {TARGET_OBJECT}")
    for name in (TARGET_FACADE, TARGET_ADAPTER, TARGET_CORE, TARGET_FOREARM):
        if bpy.data.node_groups.get(name):
            raise RuntimeError(f"Target group already exists: {name}")

    source = _source()
    values = _semantic_values(source["modifier"])
    width, thickness = _current_wrist_dimensions(source, values)
    created_groups = []
    created_objects = []
    try:
        forearm = _build_forearm(source["forearm"], width, thickness)
        created_groups.append(forearm)
        core = _build_core(source["core"], forearm, width, thickness)
        created_groups.append(core)
        adapter = _build_adapter(
            source["adapter"],
            source["core"],
            core,
            width,
            thickness,
        )
        created_groups.append(adapter)
        facade = _build_facade(
            source["facade"],
            source["adapter"],
            adapter,
            width,
            thickness,
        )
        created_groups.append(facade)
        obj, modifier = _build_object(
            source["object"],
            source["facade"],
            facade,
            values,
            width,
            thickness,
        )
        created_objects.append(obj)
        bpy.context.view_layer.update()
        validation = _validate(
            source["object"],
            obj,
            modifier,
            facade,
        )
        source["object"].hide_set(True)
        source["object"].hide_render = True
        obj.hide_set(False)
        obj.hide_render = False
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.context.view_layer.update()
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
        validation["saved_to"] = bpy.data.filepath
        validation["source_hidden_as_rollback"] = source["object"].name
        return validation
    except Exception:
        for obj in reversed(created_objects):
            if obj and obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        for group in reversed(created_groups):
            if group and group.name in bpy.data.node_groups:
                bpy.data.node_groups.remove(group, do_unlink=True)
        raise


if __name__ == "__main__":
    result = patch_live()
    print(json.dumps(result, indent=2, ensure_ascii=False))
