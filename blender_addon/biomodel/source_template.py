"""Canonical biomodel source template for the migration prototype."""

from __future__ import annotations

import textwrap


BIOMODEL_SOURCE_BLOCK = "GN_Biomodel_Source"
GENERATED_TREE_NAME = "VB_Biomodel_Generated"
SOURCE_TEMPLATE_VERSION = "0.1.0"


# Contrato reconciliado 2026-06-16 com a arvore viva `Biomodelo` (63 sockets, 4 dedos
# individuais + sistema MCP; inclui ajuste lateral MCP por dedo, Socket_118-122). Fonte de verdade canonica: presets/biomodel_sockets_live.json.
# Defaults = valores vivos no momento da reconciliacao (estado do modelo, NAO medidas reais).
# Campo 'region' = painel da interface. NOTA: o derivador antropometrico (anthropometry.py)
# ainda mapeia o contrato antigo de 2 cadeias; reconciliar a DERIVACAO e trabalho de calibracao
# (PARADA). Ver docs/SOCKET_CONTRACT_RECONCILE_2026-06-16.md.
PARAMETERS: tuple[tuple[str, str, float, str], ...] = (
    # --- Geral ---
    ('Largura Dedo', 'Socket_80', 17.25, 'width_finger'),
    # --- Medidas (tamanho) ---
    ('Comp Antebraço', 'Socket_21', 270.35, 'length_forearm'),
    ('Perímetro Cotovelo', 'Socket_22', 234.3628, 'perimeter_elbow'),
    ('Perímetro Punho', 'Socket_23', 139.0, 'perimeter_wrist'),
    ('Comp Metacarpo', 'Socket_29', 90.42, 'length_metacarpal'),
    ('Largura Metacarpo', 'Socket_30', 84.28, 'width_metacarpal'),
    ('Espessura da Palma', 'Socket_31', 29.56, 'thickness_da_palm'),
    ('Comp Metacarpo Polegar', 'Socket_33', 60.73, 'length_metacarpal_thumb'),
    ('Comp Falange Prox Polegar', 'Socket_40', 27.8, 'length_phalange_prox_thumb'),
    ('Comp Falange Dist Polegar', 'Socket_43', 20.53, 'length_phalange_dist_thumb'),
    # --- Movimento (pose) ---
    ('Desvio Rad/Ulnar Punho', 'Socket_24', -5.38, 'deviation_radial_ulnar_wrist'),
    ('Flex/Ext Punho', 'Socket_25', 0.0, 'flexion_wrist'),
    ('Curva Palma Metacarpo 1', 'Socket_27', 0.0, 'curve_palm_metacarpal_1'),
    ('Curva Palma Metacarpo 2', 'Socket_28', 0.0, 'curve_palm_metacarpal_2'),
    ('Flex/Ext Polegar', 'Socket_36', 6.2, 'flexion_thumb'),
    ('Abdução Polegar', 'Socket_37', 11.82, 'abduction_thumb'),
    ('Flex/Ext Falange Prox Polegar', 'Socket_38', 3.77, 'flexion_phalange_prox_thumb'),
    ('Flex/Ext Falange Dist Polegar', 'Socket_39', -19.0, 'flexion_phalange_dist_thumb'),
    # --- Dedos - Abduções ---
    ('Dedos - Abdução geral', 'Socket_99', 0.0, 'fingers_abduction_general'),
    ('Indicador - Abdução', 'Socket_76', -12.35, 'index_abduction'),
    ('Médio - Abdução', 'Socket_87', 0.16, 'middle_abduction'),
    ('Anelar - Abdução', 'Socket_77', -18.8, 'ring_abduction'),
    ('Mindinho - Abdução', 'Socket_88', -34.63, 'pinky_abduction'),
    # --- Dedos - Comprimentos ---
    ('Indicador - Comp. falange proximal', 'Socket_50', 20.76, 'index_length_phalange_proximal'),
    ('Indicador - Comp. falange média', 'Socket_53', 18.96, 'index_length_phalange_middle'),
    ('Indicador - Comp. falange distal', 'Socket_56', 25.15, 'index_length_phalange_distal'),
    ('Médio - Comp. falange proximal', 'Socket_81', 25.61, 'middle_length_phalange_proximal'),
    ('Médio - Comp. falange média', 'Socket_82', 25.4, 'middle_length_phalange_middle'),
    ('Médio - Comp. falange distal', 'Socket_83', 27.66, 'middle_length_phalange_distal'),
    ('Anelar - Comp. falange proximal', 'Socket_63', 22.38, 'ring_length_phalange_proximal'),
    ('Anelar - Comp. falange média', 'Socket_66', 25.79, 'ring_length_phalange_middle'),
    ('Anelar - Comp. falange distal', 'Socket_69', 23.61, 'ring_length_phalange_distal'),
    ('Mindinho - Comp. falange proximal', 'Socket_84', 18.36, 'pinky_length_phalange_proximal'),
    ('Mindinho - Comp. falange média', 'Socket_85', 21.48, 'pinky_length_phalange_middle'),
    ('Mindinho - Comp. falange distal', 'Socket_86', 20.3, 'pinky_length_phalange_distal'),
    # --- Dedos - Movimento ---
    ('Dedos - Flex/Ext proximal geral', 'Socket_100', 0.0, 'fingers_flexion_proximal_general'),
    ('Dedos - Flex/Ext média geral', 'Socket_101', 0.0, 'fingers_flexion_middle_general'),
    ('Dedos - Flex/Ext distal geral', 'Socket_102', 0.0, 'fingers_flexion_distal_general'),
    ('Indicador - Flex/Ext proximal', 'Socket_47', 0.0, 'index_flexion_proximal'),
    ('Indicador - Flex/Ext média', 'Socket_48', 0.0, 'index_flexion_middle'),
    ('Indicador - Flex/Ext distal', 'Socket_49', 0.0, 'index_flexion_distal'),
    ('Médio - Flex/Ext proximal', 'Socket_92', 0.0, 'middle_flexion_proximal'),
    ('Médio - Flex/Ext média', 'Socket_93', 0.0, 'middle_flexion_middle'),
    ('Médio - Flex/Ext distal', 'Socket_94', 0.0, 'middle_flexion_distal'),
    ('Anelar - Flex/Ext proximal', 'Socket_60', 0.0, 'ring_flexion_proximal'),
    ('Anelar - Flex/Ext média', 'Socket_61', 0.0, 'ring_flexion_middle'),
    ('Anelar - Flex/Ext distal', 'Socket_62', 0.0, 'ring_flexion_distal'),
    ('Mindinho - Flex/Ext proximal', 'Socket_95', 0.0, 'pinky_flexion_proximal'),
    ('Mindinho - Flex/Ext média', 'Socket_96', 0.0, 'pinky_flexion_middle'),
    ('Mindinho - Flex/Ext distal', 'Socket_97', 0.0, 'pinky_flexion_distal'),
    # --- Dedos - MCP / Pivôs ---
    ('Dedos - Avanço MCP geral', 'Socket_110', 8.54, 'fingers_advance_mcp_general'),
    ('Dedos - Curvatura arco MCP', 'Socket_111', 0.32, 'fingers_curvature_arch_mcp'),
    ('Indicador - Avanço MCP', 'Socket_112', 3.24, 'index_advance_mcp'),
    ('Médio - Avanço MCP', 'Socket_113', 0.19, 'middle_advance_mcp'),
    ('Anelar - Avanço MCP', 'Socket_114', 0.23, 'ring_advance_mcp'),
    ('Mindinho - Avanço MCP', 'Socket_115', -1.37, 'pinky_advance_mcp'),
    ('Dedos - Lateral MCP geral', 'Socket_118', 0.0, 'fingers_lateral_mcp_general'),
    ('Indicador - Lateral MCP', 'Socket_119', 0.0, 'index_lateral_mcp'),
    ('Médio - Lateral MCP', 'Socket_120', 0.0, 'middle_lateral_mcp'),
    ('Anelar - Lateral MCP', 'Socket_121', 0.0, 'ring_lateral_mcp'),
    ('Mindinho - Lateral MCP', 'Socket_122', 0.0, 'pinky_lateral_mcp'),
    ('MCP - Visual coroa', 'Socket_116', 0.58, 'mcp_visual_crown'),
    ('MCP - Raio cabeças', 'Socket_117', 9.6, 'mcp_radius_heads'),
)


REGIONS: tuple[tuple[str, str], ...] = (
    ('PANEL_GENERAL', 'Geral'),
    ('PANEL_MEDIDAS_TAMANHO', 'Medidas (tamanho)'),
    ('PANEL_MOVIMENTO_POSE', 'Movimento (pose)'),
    ('PANEL_FINGERS_ABDUES', 'Dedos - Abduções'),
    ('PANEL_FINGERS_COMPRIMENTOS', 'Dedos - Comprimentos'),
    ('PANEL_FINGERS_MOVIMENTO', 'Dedos - Movimento'),
    ('PANEL_FINGERS_MCP_PIVS', 'Dedos - MCP / Pivôs'),
)


def build_biomodel_source_template() -> str:
    """Return the phase-1 canonical source script.

    The generated source is intended to be written to a Blender Text block
    named ``GN_Biomodel_Source``. Running it in Blender creates a separate
    ``VB_Biomodel_Generated`` Geometry Nodes tree.
    """

    return textwrap.dedent(
        f'''\
        # GN_Biomodel_Source
        # Template version: {SOURCE_TEMPLATE_VERSION}
        #
        # This is the canonical-source migration prototype.
        # It creates/replaces only {GENERATED_TREE_NAME!r}.
        # It intentionally does not mutate the current clinical/reference tree.

        import bpy


        SOURCE_TEMPLATE_VERSION = {SOURCE_TEMPLATE_VERSION!r}
        GENERATED_TREE_NAME = {GENERATED_TREE_NAME!r}

        PARAMETERS = {PARAMETERS!r}

        REGIONS = {REGIONS!r}


        def clear_generated_tree():
            existing = bpy.data.node_groups.get(GENERATED_TREE_NAME)
            if existing is not None:
                bpy.data.node_groups.remove(existing)
            tree = bpy.data.node_groups.new(GENERATED_TREE_NAME, "GeometryNodeTree")
            tree.use_fake_user = True
            return tree


        def set_default(socket, value):
            if socket is None or not hasattr(socket, "default_value"):
                return
            try:
                socket.default_value = value
            except Exception:
                pass


        def socket_by_name(sockets, *names):
            wanted = {{str(name) for name in names if str(name)}}
            for name in wanted:
                try:
                    return sockets[name]
                except Exception:
                    pass
            for socket in sockets:
                if socket.name in wanted or getattr(socket, "identifier", "") in wanted:
                    return socket
            return None


        def link(tree, from_socket, to_socket):
            if from_socket is None or to_socket is None:
                return None
            try:
                return tree.links.new(from_socket, to_socket, handle_dynamic_sockets=True)
            except TypeError:
                return tree.links.new(from_socket, to_socket)


        def new_node(tree, node_type, name, label="", location=(0, 0), parent=None):
            node = tree.nodes.new(type=node_type)
            node.name = name
            node.label = label or name
            node.location = location
            if parent is not None:
                node.parent = parent
            return node


        def add_float_parameter(tree, name, identifier, default, role):
            item = tree.interface.new_socket(
                name=name,
                in_out="INPUT",
                socket_type="NodeSocketFloat",
            )
            item.description = f"role={{role}} legacy_identifier={{identifier}}"
            if hasattr(item, "default_value"):
                item.default_value = float(default)
            return item


        def build_interface(tree):
            for name, identifier, default, role in PARAMETERS:
                add_float_parameter(tree, name, identifier, default, role)
            tree.interface.new_socket(
                name="Geometry",
                in_out="OUTPUT",
                socket_type="NodeSocketGeometry",
            )


        def build_region_frames(tree):
            frames = {{}}
            x = -900
            y = 500
            for index, (name, label) in enumerate(REGIONS):
                frame = new_node(tree, "NodeFrame", name, label, (x + index * 280, y))
                frames[label] = frame
            return frames


        def input_socket(group_input, name):
            return socket_by_name(group_input.outputs, name)


        def add_cone_forearm(tree, group_input, frames):
            frame = frames["Antebraço"]
            cone = new_node(tree, "GeometryNodeMeshCone", "SRC_Forearm_Cone", "Antebraço cone", (-700, 360), frame)
            transform = new_node(tree, "GeometryNodeTransform", "XFORM_Forearm", "Forearm transform", (-440, 360), frame)

            set_default(socket_by_name(cone.inputs, "Vertices"), 48)
            # NOTE: protótipo mínimo — usa o perímetro direto como raio (sem ÷2π).
            # A árvore canônica `Biomodelo` é que faz a conversão perímetro→raio.
            link(tree, input_socket(group_input, "Perímetro Cotovelo"), socket_by_name(cone.inputs, "Radius Top"))
            link(tree, input_socket(group_input, "Perímetro Punho"), socket_by_name(cone.inputs, "Radius Bottom"))
            link(tree, input_socket(group_input, "Comp Antebraço"), socket_by_name(cone.inputs, "Depth"))
            link(tree, socket_by_name(cone.outputs, "Mesh", "Geometry"), socket_by_name(transform.inputs, "Geometry"))
            return transform


        def add_wrist_sphere(tree, group_input, frames):
            frame = frames["Antebraço"]
            sphere = new_node(tree, "GeometryNodeMeshUVSphere", "SRC_Wrist_Sphere", "Punho/carpo sphere", (-700, 80), frame)
            transform = new_node(tree, "GeometryNodeTransform", "XFORM_Wrist", "Wrist transform", (-440, 80), frame)

            set_default(socket_by_name(sphere.inputs, "Segments"), 32)
            set_default(socket_by_name(sphere.inputs, "Rings"), 16)
            link(tree, input_socket(group_input, "Perímetro Punho"), socket_by_name(sphere.inputs, "Radius"))
            set_default(socket_by_name(transform.inputs, "Translation"), (0.0, -120.0, 0.0))
            link(tree, socket_by_name(sphere.outputs, "Mesh", "Geometry"), socket_by_name(transform.inputs, "Geometry"))
            return transform


        def add_metacarpal_box(tree, group_input, frames):
            frame = frames["Metacarpos"]
            cube = new_node(tree, "GeometryNodeMeshCube", "SRC_Metacarpal_Box", "Representative metacarpal", (-700, -220), frame)
            scale = new_node(tree, "ShaderNodeCombineXYZ", "VEC_Metacarpal_Size", "Metacarpal size vector", (-470, -310), frame)
            transform = new_node(tree, "GeometryNodeTransform", "XFORM_Metacarpal", "Metacarpal transform", (-220, -220), frame)

            set_default(socket_by_name(cube.inputs, "Size"), 1.0)
            link(tree, input_socket(group_input, "Largura Metacarpo"), socket_by_name(scale.inputs, "X"))
            link(tree, input_socket(group_input, "Comp Metacarpo"), socket_by_name(scale.inputs, "Y"))
            link(tree, input_socket(group_input, "Espessura da Palma"), socket_by_name(scale.inputs, "Z"))
            set_default(socket_by_name(transform.inputs, "Translation"), (0.0, -210.0, 0.0))
            link(tree, socket_by_name(cube.outputs, "Mesh", "Geometry"), socket_by_name(transform.inputs, "Geometry"))
            link(tree, socket_by_name(scale.outputs, "Vector"), socket_by_name(transform.inputs, "Scale"))
            return transform


        def add_thumb_placeholder(tree, frames):
            frame = frames["Polegar"]
            cube = new_node(tree, "GeometryNodeMeshCube", "SRC_Thumb_Placeholder", "Thumb placeholder", (-700, -500), frame)
            transform = new_node(tree, "GeometryNodeTransform", "XFORM_Thumb_Placeholder", "Thumb transform", (-440, -500), frame)

            set_default(socket_by_name(cube.inputs, "Size"), 28.0)
            set_default(socket_by_name(transform.inputs, "Translation"), (42.0, -160.0, 0.0))
            set_default(socket_by_name(transform.inputs, "Rotation"), (0.0, 0.0, 0.45))
            link(tree, socket_by_name(cube.outputs, "Mesh", "Geometry"), socket_by_name(transform.inputs, "Geometry"))
            return transform


        def build_tree():
            tree = clear_generated_tree()
            build_interface(tree)

            group_input = new_node(tree, "NodeGroupInput", "Group Input", "Generated interface", (-1100, 0))
            group_output = new_node(tree, "NodeGroupOutput", "Group Output", "Generated output", (500, 0))
            frames = build_region_frames(tree)

            forearm = add_cone_forearm(tree, group_input, frames)
            wrist = add_wrist_sphere(tree, group_input, frames)
            metacarpal = add_metacarpal_box(tree, group_input, frames)
            thumb = add_thumb_placeholder(tree, frames)

            join = new_node(tree, "GeometryNodeJoinGeometry", "JOIN_Biomodel_Minimal", "Biomodel minimal assembly", (160, 40))
            for part in (forearm, wrist, metacarpal, thumb):
                link(tree, socket_by_name(part.outputs, "Geometry"), socket_by_name(join.inputs, "Geometry"))
            link(tree, socket_by_name(join.outputs, "Geometry"), socket_by_name(group_output.inputs, "Geometry"))

            print(f"{{GENERATED_TREE_NAME}} generated with {{len(tree.nodes)}} nodes and {{len(tree.links)}} links.")
            return tree


        if __name__ == "__main__":
            build_tree()
        else:
            build_tree()
        '''
    )


__all__ = [
    "BIOMODEL_SOURCE_BLOCK",
    "GENERATED_TREE_NAME",
    "PARAMETERS",
    "REGIONS",
    "SOURCE_TEMPLATE_VERSION",
    "build_biomodel_source_template",
]

