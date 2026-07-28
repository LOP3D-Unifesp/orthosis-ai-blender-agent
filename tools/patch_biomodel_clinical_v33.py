"""Build the clinical V3.3 from the active V3.2 fitting instance."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import bpy


TARGET_OBJECT = "BM_AJUSTE_SCAN_BASE_v3_3"
TARGET_FACADE = "BM_AjusteScan_v3_3"
TARGET_ADAPTER = "BM_AS_Nucleo_Clinico_v3_3"
TARGET_CORE = "Biomodelo_v3_3"
TARGET_FOREARM = "BM_Antebraco_Punho_v3_3"

PRONATION_ID = "forearm_pronation"
ASPECT_ID = "forearm_base_aspect"
PRONATION_INTERNAL = "V33::forearm_pronation"
ASPECT_INTERNAL = "V33::forearm_base_aspect"


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
    identifier = _semantic_map(modifier.node_group)[control_id]
    _modifier_set(modifier, identifier, value)


def _unlink(tree, socket):
    for link in list(socket.links):
        tree.links.remove(link)


def _group_input(tree, preferred_name=None):
    if preferred_name:
        node = tree.nodes.get(preferred_name)
        if node and node.bl_idname == "NodeGroupInput":
            return node
    return next(node for node in tree.nodes if node.bl_idname == "NodeGroupInput")


def _find_nested_group_node(tree, target_tree=None, name_prefix=None):
    candidates = [
        node
        for node in tree.nodes
        if node.bl_idname == "GeometryNodeGroup" and node.node_tree
    ]
    if target_tree is not None:
        for node in candidates:
            if node.node_tree == target_tree:
                return node
    if name_prefix:
        for node in candidates:
            if node.name.startswith(name_prefix):
                return node
    if len(candidates) == 1:
        return candidates[0]
    raise RuntimeError(f"Could not resolve nested group node in {tree.name}")


def _active_source():
    def clinical_modifier(obj):
        if obj is None:
            return None
        return next(
            (
                modifier
                for modifier in obj.modifiers
                if modifier.type == "NODES"
                and modifier.node_group
                and modifier.node_group.name.startswith("BM_AjusteScan_v3_2")
            ),
            None,
        )

    obj = bpy.context.view_layer.objects.active
    modifier = clinical_modifier(obj)
    if modifier is None:
        audited = bpy.data.objects.get("BM_AJUSTE_SCAN_BASE_v3_2.001")
        audited_modifier = clinical_modifier(audited)
        if audited_modifier is not None:
            obj = audited
            modifier = audited_modifier
    if modifier is None:
        candidates = [
            (candidate, clinical_modifier(candidate))
            for candidate in bpy.data.objects
            if candidate.name != "BM_AJUSTE_SCAN_BASE_v3_2"
        ]
        candidates = [
            (candidate, candidate_modifier)
            for candidate, candidate_modifier in candidates
            if candidate_modifier is not None
        ]
        if len(candidates) == 1:
            obj, modifier = candidates[0]
    if modifier is None:
        raise RuntimeError("Could not resolve the audited V3.2 fitting instance")
    facade = modifier.node_group
    adapter_node = _find_nested_group_node(facade, name_prefix="Nucleo_Clinico")
    adapter = adapter_node.node_tree
    core_node = _find_nested_group_node(adapter, name_prefix="Nucleo_Biomodelo")
    core = core_node.node_tree
    forearm_node = core.nodes.get("M01_Antebraco_Punho")
    if forearm_node is None or forearm_node.node_tree is None:
        raise RuntimeError("Forearm node not found in active V3.2 core")
    return {
        "object": obj,
        "modifier": modifier,
        "facade": facade,
        "adapter": adapter,
        "adapter_node": adapter_node,
        "core": core,
        "core_node": core_node,
        "forearm": forearm_node.node_tree,
    }


def _new_float_input(
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
    item.description = description
    return item


def _math(tree, name, operation, label, location):
    node = tree.nodes.new("ShaderNodeMath")
    node.name = name
    node.label = label
    node.operation = operation
    node.location = location
    return node


def _build_forearm(source_tree):
    tree = source_tree.copy()
    tree.name = TARGET_FOREARM
    tree.use_fake_user = True
    tree.description = (
        "Antebraço V3.3: twist proximal progressivo e razão elíptica proximal "
        "com perímetro aproximadamente preservado."
    )

    _new_float_input(
        tree,
        "Pronação/supinação proximal",
        0.0,
        -180.0,
        180.0,
        "Graus de rotação da seção proximal; o punho permanece fixo.",
    )
    _new_float_input(
        tree,
        "Razão proximal largura/espessura",
        1.25,
        0.6,
        2.2,
        "Razão largura/espessura da elipse proximal, preservando o perímetro.",
    )

    group_input = tree.nodes.new("NodeGroupInput")
    group_input.name = "GI_V33_Antebraco"
    group_input.label = "V3.3 — rotação e proporção proximal"
    group_input.location = (-920, -760)

    position = tree.nodes.new("GeometryNodeInputPosition")
    position.name = "V33_Position"
    position.location = (-920, -420)
    separate = tree.nodes.new("ShaderNodeSeparateXYZ")
    separate.name = "V33_SeparatePosition"
    separate.location = (-740, -420)
    tree.links.new(position.outputs["Position"], separate.inputs["Vector"])

    half = _math(
        tree,
        "V33_HalfLength",
        "MULTIPLY",
        "metade do comprimento",
        (-920, -180),
    )
    half.inputs[1].default_value = 0.5
    negative_half = _math(
        tree,
        "V33_NegativeHalfLength",
        "MULTIPLY",
        "punho = −L/2",
        (-720, -180),
    )
    negative_half.inputs[1].default_value = -1.0
    tree.links.new(group_input.outputs["Comp Antebraço"], half.inputs[0])
    tree.links.new(half.outputs[0], negative_half.inputs[0])

    progress = tree.nodes.new("ShaderNodeMapRange")
    progress.name = "V33_ProximalProgress"
    progress.label = "0 no punho → 1 na base proximal"
    progress.data_type = "FLOAT"
    progress.interpolation_type = "LINEAR"
    progress.clamp = True
    progress.location = (-500, -300)
    progress.inputs["To Min"].default_value = 0.0
    progress.inputs["To Max"].default_value = 1.0
    tree.links.new(separate.outputs["Y"], progress.inputs["Value"])
    tree.links.new(negative_half.outputs[0], progress.inputs["From Min"])
    tree.links.new(half.outputs[0], progress.inputs["From Max"])

    # Ramanujan ellipse: for q=a/b and circular reference r=P/(2π),
    # b/r = 2 / [3(q+1) - sqrt((3q+1)(q+3))], a/r = q*b/r.
    q_plus_1 = _math(tree, "V33_QPlus1", "ADD", "q + 1", (-920, 120))
    q_plus_1.inputs[1].default_value = 1.0
    three_q_plus_1_mul = _math(
        tree, "V33_ThreeQ", "MULTIPLY", "3q", (-920, 260)
    )
    three_q_plus_1_mul.inputs[1].default_value = 3.0
    three_q_plus_1 = _math(
        tree, "V33_ThreeQPlus1", "ADD", "3q + 1", (-720, 260)
    )
    three_q_plus_1.inputs[1].default_value = 1.0
    q_plus_3 = _math(tree, "V33_QPlus3", "ADD", "q + 3", (-720, 400))
    q_plus_3.inputs[1].default_value = 3.0
    product = _math(
        tree,
        "V33_RamanujanProduct",
        "MULTIPLY",
        "(3q+1)(q+3)",
        (-500, 330),
    )
    root = _math(
        tree,
        "V33_RamanujanRoot",
        "SQRT",
        "raiz de Ramanujan",
        (-300, 330),
    )
    triple_sum = _math(
        tree,
        "V33_TripleQPlus1",
        "MULTIPLY",
        "3(q+1)",
        (-500, 120),
    )
    triple_sum.inputs[1].default_value = 3.0
    denominator = _math(
        tree,
        "V33_RamanujanDenominator",
        "SUBTRACT",
        "denominador elíptico",
        (-100, 200),
    )
    b_scale = _math(
        tree,
        "V33_ThicknessScaleAbsolute",
        "DIVIDE",
        "escala absoluta da espessura",
        (100, 200),
    )
    b_scale.inputs[0].default_value = 2.0
    a_scale = _math(
        tree,
        "V33_WidthScaleAbsolute",
        "MULTIPLY",
        "escala absoluta da largura",
        (300, 310),
    )
    z_relative = _math(
        tree,
        "V33_ThicknessScaleRelative",
        "DIVIDE",
        "relativo ao achatamento antigo 0,8",
        (300, 120),
    )
    z_relative.inputs[1].default_value = 0.8

    q_output = group_input.outputs["Razão proximal largura/espessura"]
    tree.links.new(q_output, q_plus_1.inputs[0])
    tree.links.new(q_output, three_q_plus_1_mul.inputs[0])
    tree.links.new(three_q_plus_1_mul.outputs[0], three_q_plus_1.inputs[0])
    tree.links.new(q_output, q_plus_3.inputs[0])
    tree.links.new(three_q_plus_1.outputs[0], product.inputs[0])
    tree.links.new(q_plus_3.outputs[0], product.inputs[1])
    tree.links.new(product.outputs[0], root.inputs[0])
    tree.links.new(q_plus_1.outputs[0], triple_sum.inputs[0])
    tree.links.new(triple_sum.outputs[0], denominator.inputs[0])
    tree.links.new(root.outputs[0], denominator.inputs[1])
    tree.links.new(denominator.outputs[0], b_scale.inputs[1])
    tree.links.new(q_output, a_scale.inputs[0])
    tree.links.new(b_scale.outputs[0], a_scale.inputs[1])
    tree.links.new(b_scale.outputs[0], z_relative.inputs[0])

    def progressive_scale(prefix, factor_socket, y_location):
        delta = _math(
            tree,
            f"V33_{prefix}Delta",
            "SUBTRACT",
            "fator − 1",
            (500, y_location),
        )
        delta.inputs[1].default_value = 1.0
        weighted = _math(
            tree,
            f"V33_{prefix}Weighted",
            "MULTIPLY",
            "progressão proximal",
            (700, y_location),
        )
        final = _math(
            tree,
            f"V33_{prefix}Final",
            "ADD",
            "escala local final",
            (900, y_location),
        )
        final.inputs[1].default_value = 1.0
        tree.links.new(factor_socket, delta.inputs[0])
        tree.links.new(delta.outputs[0], weighted.inputs[0])
        tree.links.new(progress.outputs["Result"], weighted.inputs[1])
        tree.links.new(weighted.outputs[0], final.inputs[0])
        return final

    x_factor = progressive_scale("Width", a_scale.outputs[0], 330)
    z_factor = progressive_scale("Thickness", z_relative.outputs[0], 80)
    new_x = _math(
        tree, "V33_ScaledX", "MULTIPLY", "X elíptico", (1120, 330)
    )
    new_z = _math(
        tree, "V33_ScaledZ", "MULTIPLY", "Z elíptico", (1120, 80)
    )
    tree.links.new(separate.outputs["X"], new_x.inputs[0])
    tree.links.new(x_factor.outputs[0], new_x.inputs[1])
    tree.links.new(separate.outputs["Z"], new_z.inputs[0])
    tree.links.new(z_factor.outputs[0], new_z.inputs[1])

    combine = tree.nodes.new("ShaderNodeCombineXYZ")
    combine.name = "V33_ScaledPosition"
    combine.label = "posição com elipse proximal"
    combine.location = (1320, 220)
    tree.links.new(new_x.outputs[0], combine.inputs["X"])
    tree.links.new(separate.outputs["Y"], combine.inputs["Y"])
    tree.links.new(new_z.outputs[0], combine.inputs["Z"])

    radians = _math(
        tree,
        "V33_PronationRadians",
        "RADIANS",
        "graus → radianos",
        (920, -220),
    )
    angle = _math(
        tree,
        "V33_ProgressiveTwistAngle",
        "MULTIPLY",
        "rotação × progressão",
        (1120, -220),
    )
    tree.links.new(
        group_input.outputs["Pronação/supinação proximal"],
        radians.inputs[0],
    )
    tree.links.new(radians.outputs[0], angle.inputs[0])
    tree.links.new(progress.outputs["Result"], angle.inputs[1])

    rotate = tree.nodes.new("ShaderNodeVectorRotate")
    rotate.name = "V33_ProgressiveTwist"
    rotate.label = "torção proximal em torno do eixo do antebraço"
    rotate.rotation_type = "AXIS_ANGLE"
    rotate.invert = False
    rotate.location = (1510, 130)
    rotate.inputs["Center"].default_value = (0.0, 0.0, 0.0)
    rotate.inputs["Axis"].default_value = (0.0, 1.0, 0.0)
    tree.links.new(combine.outputs["Vector"], rotate.inputs["Vector"])
    tree.links.new(angle.outputs[0], rotate.inputs["Angle"])

    set_position = tree.nodes.new("GeometryNodeSetPosition")
    set_position.name = "V33_SetForearmPosition"
    set_position.label = "aplica proporção + pronação/supinação"
    set_position.location = (1740, 100)
    forearm_transform = tree.nodes["TF_Antebraco"]
    join = tree.nodes["Join_Antebraco_Carpo"]
    for link in list(join.inputs["Geometry"].links):
        if link.from_node == forearm_transform:
            tree.links.remove(link)
    tree.links.new(
        forearm_transform.outputs["Geometry"],
        set_position.inputs["Geometry"],
    )
    tree.links.new(rotate.outputs["Vector"], set_position.inputs["Position"])
    tree.links.new(set_position.outputs["Geometry"], join.inputs["Geometry"])

    tree["pronation_semantics"] = "progressive_twist_wrist_fixed"
    tree["proximal_aspect_semantics"] = "ellipse_perimeter_preserved_ramanujan"
    tree["wrist_aspect_baseline"] = 1.25
    return tree


def _build_core(source_tree, forearm_tree):
    tree = source_tree.copy()
    tree.name = TARGET_CORE
    tree.use_fake_user = True
    tree.description = (
        "Biomodelo V3.3 with parameterized proximal forearm twist and aspect."
    )
    _new_float_input(
        tree,
        "Antebraço - Pronação/supinação proximal",
        0.0,
        -180.0,
        180.0,
    )
    _new_float_input(
        tree,
        "Antebraço - Razão proximal largura/espessura",
        1.25,
        0.6,
        2.2,
    )

    forearm_node = tree.nodes["M01_Antebraco_Punho"]
    forearm_node.node_tree = forearm_tree
    group_input = tree.nodes.new("NodeGroupInput")
    group_input.name = "GI_V33_Antebraco"
    group_input.label = "V3.3 — controles proximais do antebraço"
    group_input.location = (-820, 1180)
    tree.links.new(
        group_input.outputs["Antebraço - Pronação/supinação proximal"],
        forearm_node.inputs["Pronação/supinação proximal"],
    )
    tree.links.new(
        group_input.outputs["Antebraço - Razão proximal largura/espessura"],
        forearm_node.inputs["Razão proximal largura/espessura"],
    )
    tree["schema_version"] = 12
    return tree


def _build_adapter(source_tree, old_core, core):
    tree = source_tree.copy()
    tree.name = TARGET_ADAPTER
    tree.use_fake_user = True
    tree.description = "Clinical V3.3 adapter with proximal forearm parameters."

    pronation = _new_float_input(
        tree,
        PRONATION_INTERNAL,
        0.0,
        -180.0,
        180.0,
    )
    aspect = _new_float_input(
        tree,
        ASPECT_INTERNAL,
        1.25,
        0.6,
        2.2,
    )
    group_input = _group_input(tree, "Entradas_Clinicas")
    core_node = _find_nested_group_node(tree, target_tree=old_core)
    core_node.node_tree = core
    core_node.name = "Nucleo_Biomodelo_v3_3"
    core_node.label = "Núcleo V3.3"
    tree.links.new(
        group_input.outputs[pronation.name],
        core_node.inputs["Antebraço - Pronação/supinação proximal"],
    )
    tree.links.new(
        group_input.outputs[aspect.name],
        core_node.inputs["Antebraço - Razão proximal largura/espessura"],
    )
    tree["schema_version"] = 12
    return tree


def _build_facade(source_tree, old_adapter, adapter):
    tree = source_tree.copy()
    tree.name = TARGET_FACADE
    tree.use_fake_user = True
    tree.description = (
        "Painel clínico V3.3: sequência antebraço→punho e parâmetros "
        "proximais de pronação/supinação e proporção."
    )
    measures = _panel(tree, "1. Medidas do indivíduo")
    pronation = _new_float_input(
        tree,
        "Pronação/supinação da base proximal",
        0.0,
        -180.0,
        180.0,
        (
            "Gira progressivamente a seção proximal do antebraço; "
            "o punho e a mão permanecem fixos."
        ),
    )
    aspect = _new_float_input(
        tree,
        "Base proximal — largura/espessura",
        1.25,
        0.6,
        2.2,
        (
            "Razão da largura pela espessura palmar-dorsal. "
            "1 é circular; valores maiores deixam a base mais larga/achatada."
        ),
    )
    tree.interface.move_to_parent(pronation, measures, 10_000)
    tree.interface.move_to_parent(aspect, measures, 10_000)

    mapping = _semantic_map(tree)
    mapping[PRONATION_ID] = pronation.identifier
    mapping[ASPECT_ID] = aspect.identifier
    tree["semantic_input_identifiers"] = json.dumps(
        mapping,
        ensure_ascii=False,
        sort_keys=True,
    )

    wrist_flexion = _semantic_item(tree, "wrist_flexion_legacy")
    wrist_flexion.name = "Flexão/extensão do punho"
    wrist_flexion.min_value = -180.0
    wrist_flexion.max_value = 180.0
    wrist_flexion.description = (
        "Rotação da mão em graus. Intervalo ampliado para não travar "
        "o alinhamento anatômico; 0 é o neutro espalmado."
    )

    ordered = (
        _semantic_item(tree, "forearm_length"),
        _semantic_item(tree, "elbow_perimeter"),
        _semantic_item(tree, "wrist_perimeter"),
        wrist_flexion,
        pronation,
        aspect,
        _semantic_item(tree, "left_member"),
        _semantic_item(tree, "wrist_to_mcp"),
        _semantic_item(tree, "palm_width"),
        _semantic_item(tree, "palm_thickness"),
    )
    for index, item in enumerate(ordered):
        tree.interface.move_to_parent(item, measures, index)

    group_input = _group_input(tree)
    adapter_node = _find_nested_group_node(tree, target_tree=old_adapter)
    adapter_node.node_tree = adapter
    adapter_node.name = "Nucleo_Clinico_V3_3"
    adapter_node.label = "Derivações clínicas V3.3"
    tree.links.new(
        group_input.outputs[pronation.name],
        adapter_node.inputs[PRONATION_INTERNAL],
    )
    tree.links.new(
        group_input.outputs[aspect.name],
        adapter_node.inputs[ASPECT_INTERNAL],
    )
    tree["schema_version"] = 12
    tree["architecture"] = "clinical_scan_facade_v3_3"
    tree["adapter"] = TARGET_ADAPTER
    tree["model_core"] = TARGET_CORE
    tree["contract_file"] = "presets/biomodel_clinical_patch_v3_3.json"
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


def _delta_stats(reference, tested):
    if len(reference["coords"]) != len(tested["coords"]):
        return {"max": math.inf, "changed": len(tested["coords"]), "unchanged": 0}
    deltas = [
        math.dist(point_a, point_b)
        for point_a, point_b in zip(reference["coords"], tested["coords"])
    ]
    return {
        "max": max(deltas),
        "changed": sum(delta > 1e-6 for delta in deltas),
        "unchanged": sum(delta <= 1e-6 for delta in deltas),
    }


def _build_object(source, facade, old_facade, values):
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
        raise RuntimeError("Copied active clinical modifier not found")
    modifier.node_group = facade
    modifier.name = "Painel Clínico V3.3"

    for control_id, value in values.items():
        if control_id in _semantic_map(facade):
            _set_semantic(modifier, control_id, value)
    _set_semantic(modifier, PRONATION_ID, 0.0)
    _set_semantic(modifier, ASPECT_ID, 1.25)

    obj["bm_version"] = "3.3"
    obj["bm_schema_version"] = 12
    obj["bm_facade"] = TARGET_FACADE
    obj["bm_adapter"] = TARGET_ADAPTER
    obj["bm_core"] = TARGET_CORE
    obj["bm_source_object"] = source.name
    obj["bm_created_utc"] = datetime.now(timezone.utc).isoformat()
    obj["bm_forearm_pronation"] = "progressive_twist_wrist_fixed"
    obj["bm_forearm_aspect"] = "ramanujan_ellipse_perimeter_preserved"
    return obj, modifier


def _validate(obj, modifier, facade):
    obj.update_tag()
    bpy.context.view_layer.update()
    neutral = _geometry(obj)
    if neutral["vertices"] != 1762 or neutral["polygons"] != 1812:
        raise RuntimeError(
            "V3.3 changed topology unexpectedly: "
            f"{neutral['vertices']} vertices, {neutral['polygons']} polygons"
        )

    original = {
        PRONATION_ID: _semantic_values(modifier)[PRONATION_ID],
        ASPECT_ID: _semantic_values(modifier)[ASPECT_ID],
        "wrist_flexion_legacy": _semantic_values(modifier)[
            "wrist_flexion_legacy"
        ],
    }
    tests = (
        (PRONATION_ID, 35.0),
        (ASPECT_ID, 1.0),
        ("wrist_flexion_legacy", 150.0),
    )
    responses = {}
    for control_id, value in tests:
        _set_semantic(modifier, control_id, value)
        obj.update_tag()
        bpy.context.view_layer.update()
        stats = _delta_stats(neutral, _geometry(obj))
        if not math.isfinite(stats["max"]) or stats["max"] <= 1e-6:
            raise RuntimeError(f"V3.3 control did not respond: {control_id}")
        if control_id == PRONATION_ID and stats["unchanged"] == 0:
            raise RuntimeError("Pronation unexpectedly moved the entire model")
        responses[control_id] = stats
        _set_semantic(modifier, control_id, original[control_id])

    obj.update_tag()
    bpy.context.view_layer.update()
    restored = _delta_stats(neutral, _geometry(obj))
    if restored["max"] > 1e-5:
        raise RuntimeError(f"V3.3 tests did not restore the model: {restored}")

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
        "Base proximal — largura/espessura",
    ]
    if order[:6] != expected:
        raise RuntimeError(f"Unexpected group 1 order: {order}")
    wrist = _semantic_item(facade, "wrist_flexion_legacy")
    if wrist.min_value > -180.0 or wrist.max_value < 180.0:
        raise RuntimeError("Wrist flexion range was not expanded")

    return {
        "object": obj.name,
        "facade": facade.name,
        "vertices": neutral["vertices"],
        "edges": neutral["edges"],
        "polygons": neutral["polygons"],
        "group_1_order": order,
        "wrist_flexion_range": [wrist.min_value, wrist.max_value],
        "responses": responses,
        "restored_delta": restored["max"],
    }


def patch_live():
    if bpy.data.objects.get(TARGET_OBJECT):
        raise RuntimeError(f"Target object already exists: {TARGET_OBJECT}")
    for name in (TARGET_FACADE, TARGET_ADAPTER, TARGET_CORE, TARGET_FOREARM):
        if bpy.data.node_groups.get(name):
            raise RuntimeError(f"Target group already exists: {name}")

    source = _active_source()
    current_values = _semantic_values(source["modifier"])
    created_groups = []
    created_objects = []
    try:
        forearm = _build_forearm(source["forearm"])
        created_groups.append(forearm)
        core = _build_core(source["core"], forearm)
        created_groups.append(core)
        adapter = _build_adapter(source["adapter"], source["core"], core)
        created_groups.append(adapter)
        facade = _build_facade(source["facade"], source["adapter"], adapter)
        created_groups.append(facade)
        obj, modifier = _build_object(
            source["object"],
            facade,
            source["facade"],
            current_values,
        )
        created_objects.append(obj)
        validation = _validate(obj, modifier, facade)

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
        validation["source_object"] = source["object"].name
        validation["source_hidden_as_rollback"] = True
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
