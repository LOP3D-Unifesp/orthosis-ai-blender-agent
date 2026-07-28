"""Replace the V3.3 proximal aspect ratio with width and thickness in mm."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import bpy


SOURCE_OBJECT = "BM_AJUSTE_SCAN_BASE_v3_3"
TARGET_OBJECT = "BM_AJUSTE_SCAN_BASE_v3_4"
TARGET_FACADE = "BM_AjusteScan_v3_4"
TARGET_ADAPTER = "BM_AS_Nucleo_Clinico_v3_4"
TARGET_CORE = "Biomodelo_v3_4"
TARGET_FOREARM = "BM_Antebraco_Punho_v3_4"

OLD_ID = "forearm_base_aspect"
WIDTH_ID = "forearm_base_width"
THICKNESS_ID = "forearm_base_thickness"
OLD_INTERNAL = "V33::forearm_base_aspect"
WIDTH_INTERNAL = "V34::forearm_base_width"
THICKNESS_INTERNAL = "V34::forearm_base_thickness"
OLD_CORE_INPUT = "Antebraço - Razão proximal largura/espessura"
WIDTH_CORE_INPUT = "Antebraço - Largura proximal"
THICKNESS_CORE_INPUT = "Antebraço - Espessura proximal"
OLD_FOREARM_INPUT = "Razão proximal largura/espessura"
WIDTH_FOREARM_INPUT = "Largura proximal"
THICKNESS_FOREARM_INPUT = "Espessura proximal"


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
    raise KeyError(f"{tree.name}: input not found: {name}")


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


def _new_float(tree, name, default, minimum=20.0, maximum=250.0, description=""):
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
            and modifier.node_group.name.startswith("BM_AjusteScan_v3_3")
        ),
        None,
    )
    if modifier is None:
        raise RuntimeError("V3.3 clinical modifier not found")
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
        "core": core,
        "forearm": forearm_node.node_tree,
    }


def _dimensions_from_perimeter(perimeter, aspect):
    q = max(float(aspect), 1e-6)
    denominator = math.pi * (
        3.0 * (q + 1.0) - math.sqrt((3.0 * q + 1.0) * (q + 3.0))
    )
    semi_thickness = float(perimeter) / denominator
    semi_width = q * semi_thickness
    return 2.0 * semi_width, 2.0 * semi_thickness


def _build_forearm(source_tree, width, thickness):
    tree = source_tree.copy()
    tree.name = TARGET_FOREARM
    tree.use_fake_user = True
    tree.description = (
        "Antebraço V3.4: largura e espessura proximais independentes em mm; "
        "pronação/supinação progressiva preservada."
    )
    old_item = _interface_item(tree, OLD_FOREARM_INPUT)
    tree.interface.remove(old_item)
    width_item = _new_float(
        tree,
        WIDTH_FOREARM_INPUT,
        width,
        description="Largura medial-lateral absoluta da seção proximal.",
    )
    thickness_item = _new_float(
        tree,
        THICKNESS_FOREARM_INPUT,
        thickness,
        description="Espessura palmar-dorsal absoluta da seção proximal.",
    )

    group_input = tree.nodes.new("NodeGroupInput")
    group_input.name = "GI_V34_ProximalDimensions"
    group_input.label = "V3.4 — largura e espessura proximais"
    group_input.location = (80, 620)

    # Remove the old Ramanujan aspect branch. Progressive deformation and
    # pronation nodes remain and receive new absolute scale factors.
    old_nodes = (
        "V33_QPlus1",
        "V33_ThreeQ",
        "V33_ThreeQPlus1",
        "V33_QPlus3",
        "V33_RamanujanProduct",
        "V33_RamanujanRoot",
        "V33_TripleQPlus1",
        "V33_RamanujanDenominator",
        "V33_ThicknessScaleAbsolute",
        "V33_WidthScaleAbsolute",
        "V33_ThicknessScaleRelative",
    )
    for name in old_nodes:
        node = tree.nodes.get(name)
        if node is not None:
            tree.nodes.remove(node)

    diameter = _math(
        tree,
        "V34_ProximalCircleDiameter",
        "MULTIPLY",
        "diâmetro circular do perímetro",
        (280, 700),
    )
    diameter.inputs[1].default_value = 2.0
    old_flat_diameter = _math(
        tree,
        "V34_OldThicknessDiameter",
        "MULTIPLY",
        "diâmetro após achatamento-base 0,8",
        (280, 540),
    )
    old_flat_diameter.inputs[1].default_value = 1.6
    width_scale = _math(
        tree,
        "V34_WidthScale",
        "DIVIDE",
        "largura alvo ÷ diâmetro-base",
        (500, 700),
    )
    thickness_scale = _math(
        tree,
        "V34_ThicknessScale",
        "DIVIDE",
        "espessura alvo ÷ espessura-base",
        (500, 540),
    )
    elbow_radius = tree.nodes["Cotovelo_raio"].outputs[0]
    tree.links.new(elbow_radius, diameter.inputs[0])
    tree.links.new(elbow_radius, old_flat_diameter.inputs[0])
    tree.links.new(
        group_input.outputs[width_item.name],
        width_scale.inputs[0],
    )
    tree.links.new(diameter.outputs[0], width_scale.inputs[1])
    tree.links.new(
        group_input.outputs[thickness_item.name],
        thickness_scale.inputs[0],
    )
    tree.links.new(old_flat_diameter.outputs[0], thickness_scale.inputs[1])

    width_delta = tree.nodes["V33_WidthDelta"]
    thickness_delta = tree.nodes["V33_ThicknessDelta"]
    _unlink(tree, width_delta.inputs[0])
    _unlink(tree, thickness_delta.inputs[0])
    tree.links.new(width_scale.outputs[0], width_delta.inputs[0])
    tree.links.new(thickness_scale.outputs[0], thickness_delta.inputs[0])

    tree["schema_version"] = 13
    tree["proximal_dimensions"] = "independent_absolute_mm"
    tree["proximal_perimeter_precedence"] = "reference_only_when_dimensions_override"
    return tree


def _build_core(source_tree, forearm_tree, width, thickness):
    tree = source_tree.copy()
    tree.name = TARGET_CORE
    tree.use_fake_user = True
    tree.description = "Biomodelo V3.4 with independent proximal width/thickness."
    tree.interface.remove(_interface_item(tree, OLD_CORE_INPUT))
    width_item = _new_float(tree, WIDTH_CORE_INPUT, width)
    thickness_item = _new_float(tree, THICKNESS_CORE_INPUT, thickness)

    forearm_node = tree.nodes["M01_Antebraco_Punho"]
    forearm_node.node_tree = forearm_tree
    group_input = tree.nodes.new("NodeGroupInput")
    group_input.name = "GI_V34_ProximalDimensions"
    group_input.label = "V3.4 — dimensões proximais"
    group_input.location = (-820, 1320)
    tree.links.new(
        group_input.outputs[width_item.name],
        forearm_node.inputs[WIDTH_FOREARM_INPUT],
    )
    tree.links.new(
        group_input.outputs[thickness_item.name],
        forearm_node.inputs[THICKNESS_FOREARM_INPUT],
    )
    tree["schema_version"] = 13
    return tree


def _build_adapter(source_tree, old_core, core, width, thickness):
    tree = source_tree.copy()
    tree.name = TARGET_ADAPTER
    tree.use_fake_user = True
    tree.description = "Clinical V3.4 adapter with proximal width/thickness in mm."
    tree.interface.remove(_interface_item(tree, OLD_INTERNAL))
    width_item = _new_float(tree, WIDTH_INTERNAL, width)
    thickness_item = _new_float(tree, THICKNESS_INTERNAL, thickness)
    group_input = _group_input(tree, "Entradas_Clinicas")
    core_node = _find_nested(tree, target=old_core)
    core_node.node_tree = core
    core_node.name = "Nucleo_Biomodelo_v3_4"
    core_node.label = "Núcleo V3.4"
    tree.links.new(
        group_input.outputs[width_item.name],
        core_node.inputs[WIDTH_CORE_INPUT],
    )
    tree.links.new(
        group_input.outputs[thickness_item.name],
        core_node.inputs[THICKNESS_CORE_INPUT],
    )
    tree["schema_version"] = 13
    return tree


def _build_facade(source_tree, old_adapter, adapter, width, thickness):
    tree = source_tree.copy()
    tree.name = TARGET_FACADE
    tree.use_fake_user = True
    tree.description = (
        "Painel clínico V3.4: largura e espessura proximais independentes."
    )
    old_public = _semantic_item(tree, OLD_ID)
    tree.interface.remove(old_public)
    measures = _panel(tree, "1. Medidas do indivíduo")
    width_item = _new_float(
        tree,
        "Base proximal — largura",
        width,
        description=(
            "Largura medial-lateral real da seção proximal do antebraço."
        ),
    )
    thickness_item = _new_float(
        tree,
        "Base proximal — espessura",
        thickness,
        description=(
            "Espessura palmar-dorsal real da seção proximal do antebraço."
        ),
    )
    tree.interface.move_to_parent(width_item, measures, 10_000)
    tree.interface.move_to_parent(thickness_item, measures, 10_000)

    mapping = _semantic_map(tree)
    mapping.pop(OLD_ID, None)
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
        "wrist_flexion_legacy",
        "forearm_pronation",
    )
    ordered = [_semantic_item(tree, control_id) for control_id in ordered_ids]
    ordered.extend(
        (
            width_item,
            thickness_item,
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
    adapter_node.name = "Nucleo_Clinico_V3_4"
    adapter_node.label = "Derivações clínicas V3.4"
    tree.links.new(
        group_input.outputs[width_item.name],
        adapter_node.inputs[WIDTH_INTERNAL],
    )
    tree.links.new(
        group_input.outputs[thickness_item.name],
        adapter_node.inputs[THICKNESS_INTERNAL],
    )
    tree["schema_version"] = 13
    tree["architecture"] = "clinical_scan_facade_v3_4"
    tree["adapter"] = TARGET_ADAPTER
    tree["model_core"] = TARGET_CORE
    tree["contract_file"] = "presets/biomodel_clinical_patch_v3_4.json"
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
        raise RuntimeError("Copied V3.3 modifier not found")
    modifier.node_group = facade
    modifier.name = "Painel Clínico V3.4"
    for control_id, value in values.items():
        if control_id in _semantic_map(facade):
            _set_semantic(modifier, control_id, value)
    _set_semantic(modifier, WIDTH_ID, width)
    _set_semantic(modifier, THICKNESS_ID, thickness)
    obj["bm_version"] = "3.4"
    obj["bm_schema_version"] = 13
    obj["bm_facade"] = TARGET_FACADE
    obj["bm_adapter"] = TARGET_ADAPTER
    obj["bm_core"] = TARGET_CORE
    obj["bm_source_object"] = source.name
    obj["bm_created_utc"] = datetime.now(timezone.utc).isoformat()
    obj["bm_proximal_dimensions"] = "independent_width_thickness_mm"
    return obj, modifier


def _validate(source_obj, obj, modifier, facade):
    source_geometry = _geometry(source_obj)
    neutral = _geometry(obj)
    baseline_delta = _max_delta(source_geometry, neutral)
    if baseline_delta > 1e-3:
        raise RuntimeError(
            f"V3.4 did not preserve the current V3.3 shape: {baseline_delta}"
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
            raise RuntimeError(f"V3.4 control did not respond: {control_id}")
        responses[control_id] = delta
        _set_semantic(modifier, control_id, original)
    obj.update_tag()
    bpy.context.view_layer.update()
    restored = _max_delta(neutral, _geometry(obj))
    if restored > 1e-5:
        raise RuntimeError(f"V3.4 did not restore its baseline: {restored}")

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
        "Flexão/extensão do punho",
        "Pronação/supinação da base proximal",
        "Base proximal — largura",
        "Base proximal — espessura",
    ]
    if order[:7] != expected:
        raise RuntimeError(f"Unexpected V3.4 group 1 order: {order}")
    if OLD_ID in _semantic_map(facade):
        raise RuntimeError("Old proximal aspect control is still public")
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
        "width_mm": values[WIDTH_ID],
        "thickness_mm": values[THICKNESS_ID],
    }


def patch_live():
    if bpy.data.objects.get(TARGET_OBJECT):
        raise RuntimeError(f"Target object already exists: {TARGET_OBJECT}")
    for name in (TARGET_FACADE, TARGET_ADAPTER, TARGET_CORE, TARGET_FOREARM):
        if bpy.data.node_groups.get(name):
            raise RuntimeError(f"Target group already exists: {name}")

    source = _source()
    values = _semantic_values(source["modifier"])
    width, thickness = _dimensions_from_perimeter(
        values["elbow_perimeter"],
        values[OLD_ID],
    )
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
        validation = _validate(
            source["object"],
            obj,
            modifier,
            facade,
        )
        source["object"]["bm_successor"] = TARGET_OBJECT
        source["object"].hide_set(True)
        source["object"].hide_render = True
        obj.hide_set(False)
        obj.hide_render = False
        for selected in bpy.context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        obj["bm_validation"] = json.dumps(
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
