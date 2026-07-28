"""Add wrist axial length and metacarpal-base placement to V3.5."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import bpy


SOURCE_OBJECT = "BM_AJUSTE_SCAN_BASE_v3_5"
TARGET_OBJECT = "BM_AJUSTE_SCAN_BASE_v3_6"
TARGET_FACADE = "BM_AjusteScan_v3_6"
TARGET_ADAPTER = "BM_AS_Nucleo_Clinico_v3_6"
TARGET_CORE = "Biomodelo_v3_6"
TARGET_FOREARM = "BM_Antebraco_Punho_v3_6"
TARGET_DERIVATION = "BM_Deriv_Punho_Carpo_v3_6"
TARGET_FINGER = "BM_Dedo_Longo_v3_6"

AXIAL_ID = "wrist_axial_length"
HEIGHT_ID = "metacarpal_base_height"
SETBACK_ID = "metacarpal_setback_legacy"
AXIAL_INTERNAL = "V36::wrist_axial_length"
HEIGHT_INTERNAL = "V36::metacarpal_base_height"
AXIAL_CORE_INPUT = "Punho - Comprimento axial"
HEIGHT_CORE_INPUT = "Metacarpos - Altura base geral"
AXIAL_FOREARM_INPUT = "Comprimento axial do punho"
AXIAL_DERIVATION_INPUT = "Comprimento axial do punho"
HEIGHT_FINGER_INPUT = "Metacarpos - Altura base geral"

FINGER_NODES = (
    "M02_Dedo_Indicador",
    "M02_Dedo_Medio",
    "M02_Dedo_Anelar",
    "M02_Dedo_Mindinho",
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


def _group_output(tree, preferred=None):
    if preferred:
        node = tree.nodes.get(preferred)
        if node and node.bl_idname == "NodeGroupOutput":
            return node
    return next(node for node in tree.nodes if node.bl_idname == "NodeGroupOutput")


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
    minimum,
    maximum,
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
            and modifier.node_group.name.startswith("BM_AjusteScan_v3_5")
        ),
        None,
    )
    if modifier is None:
        raise RuntimeError("V3.5 clinical modifier not found")
    facade = modifier.node_group
    adapter_node = _find_nested(facade, prefix="Nucleo_Clinico")
    adapter = adapter_node.node_tree
    core_node = _find_nested(adapter, prefix="Nucleo_Biomodelo")
    core = core_node.node_tree
    forearm_node = core.nodes["M01_Antebraco_Punho"]
    derivation_node = core.nodes["M00a_Punho_Carpo"]
    finger_node = core.nodes["M02_Dedo_Medio"]
    return {
        "object": obj,
        "modifier": modifier,
        "facade": facade,
        "adapter": adapter,
        "adapter_core_node": core_node,
        "core": core,
        "forearm": forearm_node.node_tree,
        "derivation": derivation_node.node_tree,
        "finger": finger_node.node_tree,
    }


def _current_axial_length(source, values):
    core_node = source["adapter_core_node"]
    radius_factor = core_node.inputs["Carpo - Raio (x punho)"]
    axial_factor = core_node.inputs["Carpo - Escala Y"]
    if radius_factor.is_linked or axial_factor.is_linked:
        raise RuntimeError("Hidden carpal factors are unexpectedly linked")
    return (
        float(values["wrist_perimeter"])
        / math.pi
        * float(radius_factor.default_value)
        * 1.06
        * float(axial_factor.default_value)
    )


def _build_forearm(source_tree, axial_length):
    tree = source_tree.copy()
    tree.name = TARGET_FOREARM
    tree.use_fake_user = True
    tree.description = (
        "Antebraço V3.6: seção do punho com largura, espessura e "
        "comprimento axial absolutos."
    )
    axial_item = _new_float(
        tree,
        AXIAL_FOREARM_INPUT,
        axial_length,
        20.0,
        100.0,
        "Comprimento da esfera do punho ao longo do eixo do antebraço.",
    )
    group_input = tree.nodes.new("NodeGroupInput")
    group_input.name = "GI_V36_WristAxialLength"
    group_input.label = "V3.6 — comprimento axial do punho"
    group_input.location = (720, 700)

    carpal_diameter = tree.nodes.get("V35_CarpalDiameter")
    if carpal_diameter is None:
        carpal_diameter = _math(
            tree,
            "V36_CarpalDiameter",
            "MULTIPLY",
            "diâmetro-base da esfera",
            (720, 700),
        )
        carpal_diameter.inputs[1].default_value = 2.0
        tree.links.new(
            tree.nodes["Carpo_raio"].outputs[0],
            carpal_diameter.inputs[0],
        )
    axial_scale = _math(
        tree,
        "V36_CarpalAxialScale",
        "DIVIDE",
        "comprimento axial ÷ diâmetro-base",
        (1120, 700),
    )
    tree.links.new(
        group_input.outputs[axial_item.name],
        axial_scale.inputs[0],
    )
    tree.links.new(carpal_diameter.outputs[0], axial_scale.inputs[1])
    carpal_scale = tree.nodes["Vec_Carpo_Scale"]
    _unlink(tree, carpal_scale.inputs["Z"])
    tree.links.new(axial_scale.outputs[0], carpal_scale.inputs["Z"])

    tree["schema_version"] = 15
    tree["wrist_axial_length"] = "independent_absolute_mm"
    return tree


def _build_derivation(source_tree, axial_length):
    tree = source_tree.copy()
    tree.name = TARGET_DERIVATION
    tree.use_fake_user = True
    tree.description = (
        "Derivação V3.6: limite do carpo e início dos metacarpos derivados "
        "do comprimento axial real do punho."
    )
    axial_item = _new_float(
        tree,
        AXIAL_DERIVATION_INPUT,
        axial_length,
        20.0,
        100.0,
        "Comprimento axial total da esfera do punho.",
    )
    group_input = tree.nodes.new("NodeGroupInput")
    group_input.name = "GI_V36_WristAxialLength"
    group_input.label = "V3.6 — comprimento axial"
    group_input.location = (-520, 520)
    half = _math(
        tree,
        "V36_CarpalHalfAxial",
        "MULTIPLY",
        "semi-comprimento axial do punho",
        (-260, 520),
    )
    half.inputs[1].default_value = 0.5
    tree.links.new(group_input.outputs[axial_item.name], half.inputs[0])

    carpal_y = tree.nodes["d_CarpoY"]
    metacarpal_length = tree.nodes["d_V4_MC_Length_Raw"]
    output = _group_output(tree, "Saidas")
    _unlink(tree, carpal_y.inputs[0])
    _unlink(tree, metacarpal_length.inputs[1])
    _unlink(tree, output.inputs["Carpo Semi Y"])
    tree.links.new(half.outputs[0], carpal_y.inputs[0])
    tree.links.new(half.outputs[0], metacarpal_length.inputs[1])
    tree.links.new(half.outputs[0], output.inputs["Carpo Semi Y"])
    tree.nodes["d_V4_CarpoHalfY"].label = (
        "LEGADO — substituído pelo comprimento axial V3.6"
    )

    tree["schema_version"] = 15
    tree["carpal_boundary"] = "wrist_axial_length_half"
    return tree


def _build_finger(source_tree):
    tree = source_tree.copy()
    tree.name = TARGET_FINGER
    tree.use_fake_user = True
    tree.description = (
        "Dedo longo V3.6: altura global da base preserva o raio completo."
    )
    height_item = _new_float(
        tree,
        HEIGHT_FINGER_INPUT,
        0.0,
        -30.0,
        30.0,
        "Translação palmar-dorsal do metacarpo, MCP e falanges.",
    )
    group_input = tree.nodes.new("NodeGroupInput")
    group_input.name = "GI_V36_MetacarpalBaseHeight"
    group_input.label = "V3.6 — altura da base metacarpal"
    group_input.location = (1860, -880)
    translation = tree.nodes.new("ShaderNodeCombineXYZ")
    translation.name = "V36_MetacarpalBaseHeightVector"
    translation.label = "altura global no eixo Z"
    translation.location = (2080, -880)
    tree.links.new(
        group_input.outputs[height_item.name],
        translation.inputs["Z"],
    )
    transform = tree.nodes.new("GeometryNodeTransform")
    transform.name = "V36_MetacarpalBaseHeight"
    transform.label = "Move os quatro raios na altura"
    transform.location = (2300, -660)
    opening = tree.nodes["AberturaZ_TF_Dedo_V31"]
    output = _group_output(tree, "Saida")
    _unlink(tree, output.inputs["Geometria"])
    tree.links.new(opening.outputs["Geometry"], transform.inputs["Geometry"])
    tree.links.new(translation.outputs["Vector"], transform.inputs["Translation"])
    tree.links.new(transform.outputs["Geometry"], output.inputs["Geometria"])

    tree["schema_version"] = 15
    tree["metacarpal_base_height"] = "global_long_ray_translation_z"
    return tree


def _build_core(
    source_tree,
    forearm_tree,
    derivation_tree,
    finger_tree,
    axial_length,
):
    tree = source_tree.copy()
    tree.name = TARGET_CORE
    tree.use_fake_user = True
    tree.description = (
        "Biomodelo V3.6 with wrist axial length and metacarpal base height."
    )
    axial_item = _new_float(
        tree,
        AXIAL_CORE_INPUT,
        axial_length,
        20.0,
        100.0,
    )
    height_item = _new_float(
        tree,
        HEIGHT_CORE_INPUT,
        0.0,
        -30.0,
        30.0,
    )
    forearm_node = tree.nodes["M01_Antebraco_Punho"]
    derivation_node = tree.nodes["M00a_Punho_Carpo"]
    forearm_node.node_tree = forearm_tree
    derivation_node.node_tree = derivation_tree
    for name in FINGER_NODES:
        tree.nodes[name].node_tree = finger_tree

    group_input = tree.nodes.new("NodeGroupInput")
    group_input.name = "GI_V36_WristAndMetacarpalBase"
    group_input.label = "V3.6 — punho e base metacarpal"
    group_input.location = (-820, 1720)
    tree.links.new(
        group_input.outputs[axial_item.name],
        forearm_node.inputs[AXIAL_FOREARM_INPUT],
    )
    tree.links.new(
        group_input.outputs[axial_item.name],
        derivation_node.inputs[AXIAL_DERIVATION_INPUT],
    )
    for name in FINGER_NODES:
        tree.links.new(
            group_input.outputs[height_item.name],
            tree.nodes[name].inputs[HEIGHT_FINGER_INPUT],
        )
    tree["schema_version"] = 15
    return tree


def _build_adapter(source_tree, old_core, core, axial_length):
    tree = source_tree.copy()
    tree.name = TARGET_ADAPTER
    tree.use_fake_user = True
    tree.description = (
        "Clinical V3.6 adapter for wrist axial length and metacarpal height."
    )
    axial_item = _new_float(
        tree,
        AXIAL_INTERNAL,
        axial_length,
        20.0,
        100.0,
    )
    height_item = _new_float(
        tree,
        HEIGHT_INTERNAL,
        0.0,
        -30.0,
        30.0,
    )
    group_input = _group_input(tree, "Entradas_Clinicas")
    core_node = _find_nested(tree, target=old_core)
    core_node.node_tree = core
    core_node.name = "Nucleo_Biomodelo_v3_6"
    core_node.label = "Núcleo V3.6"
    tree.links.new(
        group_input.outputs[axial_item.name],
        core_node.inputs[AXIAL_CORE_INPUT],
    )
    tree.links.new(
        group_input.outputs[height_item.name],
        core_node.inputs[HEIGHT_CORE_INPUT],
    )
    tree["schema_version"] = 15
    return tree


def _build_facade(source_tree, old_adapter, adapter, axial_length):
    tree = source_tree.copy()
    tree.name = TARGET_FACADE
    tree.use_fake_user = True
    tree.description = (
        "Painel clínico V3.6: comprimento axial do punho e posicionamento "
        "da base dos metacarpos."
    )
    measures = _panel(tree, "1. Medidas do indivíduo")
    opening = _panel(tree, "4. Punho, abertura e arco da palma")
    axial_item = _new_float(
        tree,
        "Punho — comprimento axial",
        axial_length,
        20.0,
        100.0,
        "Comprimento do volume do punho no eixo do antebraço.",
    )
    height_item = _new_float(
        tree,
        "Base dos metacarpos — altura",
        0.0,
        -30.0,
        30.0,
        "Move juntos os quatro raios no eixo palmar-dorsal.",
    )
    tree.interface.move_to_parent(axial_item, measures, 10_000)
    tree.interface.move_to_parent(height_item, opening, 10_000)

    setback = _semantic_item(tree, SETBACK_ID)
    setback.name = "Base dos metacarpos — avanço/recuo"
    setback.description = (
        "Ajuste longitudinal dos quatro metacarpos. Valores positivos "
        "aproximam a base do punho; valores negativos deslocam para os dedos."
    )

    mapping = _semantic_map(tree)
    mapping[AXIAL_ID] = axial_item.identifier
    mapping[HEIGHT_ID] = height_item.identifier
    tree["semantic_input_identifiers"] = json.dumps(
        mapping,
        ensure_ascii=False,
        sort_keys=True,
    )

    measure_order = (
        "forearm_length",
        "elbow_perimeter",
        "wrist_perimeter",
        "wrist_width",
        "wrist_thickness",
    )
    ordered_measures = [
        _semantic_item(tree, control_id) for control_id in measure_order
    ]
    ordered_measures.extend(
        (
            axial_item,
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
    for index, item in enumerate(ordered_measures):
        tree.interface.move_to_parent(item, measures, index)

    ordered_opening = (
        _semantic_item(tree, "palmar_arc_global"),
        _semantic_item(tree, "wrist_deviation"),
        setback,
        height_item,
    )
    for index, item in enumerate(ordered_opening):
        tree.interface.move_to_parent(item, opening, index)

    group_input = _group_input(tree)
    adapter_node = _find_nested(tree, target=old_adapter)
    adapter_node.node_tree = adapter
    adapter_node.name = "Nucleo_Clinico_V3_6"
    adapter_node.label = "Derivações clínicas V3.6"
    tree.links.new(
        group_input.outputs[axial_item.name],
        adapter_node.inputs[AXIAL_INTERNAL],
    )
    tree.links.new(
        group_input.outputs[height_item.name],
        adapter_node.inputs[HEIGHT_INTERNAL],
    )
    tree["schema_version"] = 15
    tree["architecture"] = "clinical_scan_facade_v3_6"
    tree["adapter"] = TARGET_ADAPTER
    tree["model_core"] = TARGET_CORE
    tree["contract_file"] = "presets/biomodel_clinical_patch_v3_6.json"
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


def _build_object(source, old_facade, facade, values, axial_length):
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
        raise RuntimeError("Copied V3.5 modifier not found")
    modifier.node_group = facade
    modifier.name = "Painel Clínico V3.6"
    for control_id, value in values.items():
        if control_id in _semantic_map(facade):
            _set_semantic(modifier, control_id, value)
    _set_semantic(modifier, AXIAL_ID, axial_length)
    _set_semantic(modifier, HEIGHT_ID, 0.0)
    obj["bm_version"] = "3.6"
    obj["bm_schema_version"] = 15
    obj["bm_facade"] = TARGET_FACADE
    obj["bm_adapter"] = TARGET_ADAPTER
    obj["bm_core"] = TARGET_CORE
    obj["bm_source_object"] = source.name
    obj["bm_created_utc"] = datetime.now(timezone.utc).isoformat()
    obj["bm_wrist_axial_length"] = "absolute_mm"
    obj["bm_metacarpal_base_controls"] = "longitudinal_and_height"
    return obj, modifier


def _validate(source_obj, obj, modifier, facade, source_values):
    source_geometry = _geometry(source_obj)
    neutral = _geometry(obj)
    baseline_delta = _max_delta(source_geometry, neutral)
    if baseline_delta > 1e-3:
        raise RuntimeError(
            f"V3.6 did not preserve the current V3.5 shape: {baseline_delta}"
        )
    values = _semantic_values(modifier)
    migration_differences = {}
    for control_id, source_value in source_values.items():
        target_value = values[control_id]
        if isinstance(source_value, (int, float)):
            delta = abs(float(source_value) - float(target_value))
            if delta > 1e-7:
                migration_differences[control_id] = delta
        elif source_value != target_value:
            migration_differences[control_id] = {
                "source": source_value,
                "target": target_value,
            }
    if migration_differences:
        raise RuntimeError(
            f"V3.6 value migration failed: {migration_differences}"
        )

    tests = {
        AXIAL_ID: max(20.0, float(values[AXIAL_ID]) - 10.0),
        SETBACK_ID: float(values[SETBACK_ID]) + 10.0,
        HEIGHT_ID: float(values[HEIGHT_ID]) + 10.0,
        "wrist_flexion_legacy": float(values["wrist_flexion_legacy"]) + 10.0,
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
            raise RuntimeError(f"V3.6 control did not respond: {control_id}")
        responses[control_id] = delta
        _set_semantic(modifier, control_id, original)
    obj.update_tag()
    bpy.context.view_layer.update()
    restored = _max_delta(neutral, _geometry(obj))
    if restored > 1e-5:
        raise RuntimeError(f"V3.6 did not restore its baseline: {restored}")

    measures = _panel(facade, "1. Medidas do indivíduo")
    measure_order = [
        item.name
        for item in facade.interface.items_tree
        if getattr(item, "item_type", "") == "SOCKET" and item.parent == measures
    ]
    expected_measures = [
        "Comprimento do antebraço",
        "Perímetro proximal do antebraço",
        "Perímetro do punho",
        "Punho — largura",
        "Punho — espessura",
        "Punho — comprimento axial",
        "Flexão/extensão do punho",
        "Pronação/supinação da base proximal",
        "Base proximal — largura",
        "Base proximal — espessura",
    ]
    if measure_order[:10] != expected_measures:
        raise RuntimeError(f"Unexpected V3.6 group 1 order: {measure_order}")

    opening = _panel(facade, "4. Punho, abertura e arco da palma")
    opening_order = [
        item.name
        for item in facade.interface.items_tree
        if getattr(item, "item_type", "") == "SOCKET" and item.parent == opening
    ]
    expected_opening = [
        "Flexão/extensão do arco da mão",
        "Desvio radial/ulnar do punho",
        "Base dos metacarpos — avanço/recuo",
        "Base dos metacarpos — altura",
    ]
    if opening_order[:4] != expected_opening:
        raise RuntimeError(f"Unexpected V3.6 group 4 order: {opening_order}")

    return {
        "object": obj.name,
        "facade": facade.name,
        "vertices": neutral["vertices"],
        "edges": neutral["edges"],
        "polygons": neutral["polygons"],
        "baseline_delta": baseline_delta,
        "restored_delta": restored,
        "responses": responses,
        "migrated_controls": len(source_values),
        "group_1_order": measure_order,
        "group_4_order": opening_order,
        "wrist_axial_length_mm": values[AXIAL_ID],
        "metacarpal_base_height_mm": values[HEIGHT_ID],
        "metacarpal_base_setback_mm": values[SETBACK_ID],
    }


def patch_live():
    if bpy.data.objects.get(TARGET_OBJECT):
        raise RuntimeError(f"Target object already exists: {TARGET_OBJECT}")
    for name in (
        TARGET_FACADE,
        TARGET_ADAPTER,
        TARGET_CORE,
        TARGET_FOREARM,
        TARGET_DERIVATION,
        TARGET_FINGER,
    ):
        if bpy.data.node_groups.get(name):
            raise RuntimeError(f"Target group already exists: {name}")

    source = _source()
    values = _semantic_values(source["modifier"])
    axial_length = _current_axial_length(source, values)
    created_groups = []
    created_objects = []
    try:
        forearm = _build_forearm(source["forearm"], axial_length)
        created_groups.append(forearm)
        derivation = _build_derivation(source["derivation"], axial_length)
        created_groups.append(derivation)
        finger = _build_finger(source["finger"])
        created_groups.append(finger)
        core = _build_core(
            source["core"],
            forearm,
            derivation,
            finger,
            axial_length,
        )
        created_groups.append(core)
        adapter = _build_adapter(
            source["adapter"],
            source["core"],
            core,
            axial_length,
        )
        created_groups.append(adapter)
        facade = _build_facade(
            source["facade"],
            source["adapter"],
            adapter,
            axial_length,
        )
        created_groups.append(facade)
        obj, modifier = _build_object(
            source["object"],
            source["facade"],
            facade,
            values,
            axial_length,
        )
        created_objects.append(obj)
        bpy.context.view_layer.update()
        validation = _validate(
            source["object"],
            obj,
            modifier,
            facade,
            values,
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
