"""Canonical biomodel source template for the migration prototype."""

from __future__ import annotations

import textwrap


BIOMODEL_SOURCE_BLOCK = "GN_Biomodel_Source"
GENERATED_TREE_NAME = "VB_Biomodel_Generated"
SOURCE_TEMPLATE_VERSION = "0.1.0"


PARAMETERS: tuple[tuple[str, str, float, str], ...] = (
    ("Comp Antebraço", "Socket_21", 223.8100128173828, "forearm_length"),
    ("Raio Cotovelo", "Socket_22", 37.29999923706055, "elbow_radius"),
    ("Raio Punho", "Socket_23", 24.799999237060547, "wrist_radius"),
    ("Desvio Rad/Ulnar Punho", "Socket_24", -2.6000001430511475, "wrist_radial_ulnar_deviation"),
    ("Flex/Ext Punho", "Socket_25", 0.0, "wrist_flexion_extension"),
    ("Curva Palma Metacarpo 1", "Socket_27", 0.0, "palm_curve_1"),
    ("Curva Palma Metacarpo 2", "Socket_28", 0.0, "palm_curve_2"),
    ("Comp Metacarpo", "Socket_29", 95.27001953125, "metacarpal_length"),
    ("Largura Metacarpo", "Socket_30", 30.829992294311523, "metacarpal_width"),
    ("Espessura Metacarpo", "Socket_31", 35.62999725341797, "metacarpal_thickness"),
    ("Comp Metacarpo Polegar", "Socket_33", 0.0, "thumb_metacarpal_length"),
    ("Largura Metacarpo Polegar", "Socket_34", 0.0, "thumb_metacarpal_width"),
    ("Espessura Metacarpo Polegar", "Socket_35", 0.0, "thumb_metacarpal_thickness"),
    ("Flex/Ext Polegar", "Socket_36", 3.5899999141693115, "thumb_flexion_extension"),
    ("Abdução Polegar", "Socket_37", 15.0, "thumb_abduction"),
    ("Flex/Ext Falange Prox Polegar", "Socket_38", 0.0, "thumb_proximal_flexion_extension"),
    ("Flex/Ext Falange Dist Polegar", "Socket_39", 0.0, "thumb_distal_flexion_extension"),
    ("Comp Falange Prox Polegar", "Socket_40", 0.0, "thumb_proximal_length"),
    ("Espessura Falange Prox Polegar", "Socket_42", 0.0, "thumb_proximal_thickness"),
    ("Comp Falange Dist Polegar", "Socket_43", 0.0, "thumb_distal_length"),
    ("Espessura Falange Dist Polegar", "Socket_45", 0.0, "thumb_distal_thickness"),
    ("Abdução Dedo 1", "Socket_76", 28.6, "finger_1_abduction"),
    ("Flex/Ext Falange Prox 1", "Socket_47", 0.0, "finger_1_proximal_flexion_extension"),
    ("Flex/Ext Falange Media 1", "Socket_48", 0.0, "finger_1_middle_flexion_extension"),
    ("Flex/Ext Falange Dist 1", "Socket_49", 0.0, "finger_1_distal_flexion_extension"),
    ("Comp Falange Prox 1", "Socket_50", 0.0, "finger_1_proximal_length"),
    ("Espessura Falange Prox 1", "Socket_52", 0.0, "finger_1_proximal_thickness"),
    ("Comp Falange Media 1", "Socket_53", 0.0, "finger_1_middle_length"),
    ("Espessura Falange Media 1", "Socket_55", 0.0, "finger_1_middle_thickness"),
    ("Comp Falange Dist 1", "Socket_56", 0.0, "finger_1_distal_length"),
    ("Espessura Falange Dist 1", "Socket_58", 0.0, "finger_1_distal_thickness"),
    ("Abdução Dedo 2", "Socket_77", 10.0, "finger_2_abduction"),
    ("Flex/Ext Falange Prox 2", "Socket_60", 0.0, "finger_2_proximal_flexion_extension"),
    ("Flex/Ext Falange Media 2", "Socket_61", 0.0, "finger_2_middle_flexion_extension"),
    ("Flex/Ext Falange Dist 2", "Socket_62", 0.0, "finger_2_distal_flexion_extension"),
    ("Comp Falange Prox 2", "Socket_63", 0.0, "finger_2_proximal_length"),
    ("Espessura Falange Prox 2", "Socket_65", 0.0, "finger_2_proximal_thickness"),
    ("Comp Falange Media 2", "Socket_66", 0.0, "finger_2_middle_length"),
    ("Espessura Falange Media 2", "Socket_68", 0.0, "finger_2_middle_thickness"),
    ("Comp Falange Dist 2", "Socket_69", 0.0, "finger_2_distal_length"),
    ("Espessura Falange Dist 2", "Socket_71", 0.0, "finger_2_distal_thickness"),
)


REGIONS: tuple[tuple[str, str], ...] = (
    ("REGION_FOREARM", "Antebraço"),
    ("REGION_THUMB_SEGMENTS", "Polegar"),
    ("REGION_THUMB_POSE", "Flex/Ext e Abd Polegar"),
    ("REGION_WRIST_POSE", "Desvio e Ext/Flex Punho"),
    ("REGION_FINGER_CHAIN_1", "Falanges1"),
    ("REGION_FINGER_CHAIN_2", "Falanges 2"),
    ("REGION_METACARPALS", "Metacarpos"),
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
            link(tree, input_socket(group_input, "Raio Cotovelo"), socket_by_name(cone.inputs, "Radius Top"))
            link(tree, input_socket(group_input, "Raio Punho"), socket_by_name(cone.inputs, "Radius Bottom"))
            link(tree, input_socket(group_input, "Comp Antebraço"), socket_by_name(cone.inputs, "Depth"))
            link(tree, socket_by_name(cone.outputs, "Mesh", "Geometry"), socket_by_name(transform.inputs, "Geometry"))
            return transform


        def add_wrist_sphere(tree, group_input, frames):
            frame = frames["Antebraço"]
            sphere = new_node(tree, "GeometryNodeMeshUVSphere", "SRC_Wrist_Sphere", "Punho/carpo sphere", (-700, 80), frame)
            transform = new_node(tree, "GeometryNodeTransform", "XFORM_Wrist", "Wrist transform", (-440, 80), frame)

            set_default(socket_by_name(sphere.inputs, "Segments"), 32)
            set_default(socket_by_name(sphere.inputs, "Rings"), 16)
            link(tree, input_socket(group_input, "Raio Punho"), socket_by_name(sphere.inputs, "Radius"))
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
            link(tree, input_socket(group_input, "Espessura Metacarpo"), socket_by_name(scale.inputs, "Z"))
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

