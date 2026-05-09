"""Structured Blender edit tool handlers."""

from __future__ import annotations

import traceback


def handle_apply_renames(cmd: dict) -> dict:
    renames = cmd.get("renames", [])

    def _do():
        import bpy

        applied = []
        errors = []
        for entry in renames:
            old_name = entry.get("from", "")
            new_name = entry.get("to", "")
            obj = bpy.data.objects.get(old_name)
            if obj is None:
                errors.append({"from": old_name, "to": new_name, "error": f"Object '{old_name}' not found"})
                continue
            obj.name = new_name
            applied.append({"from": old_name, "to": obj.name, "requested": new_name})
        return {"status": "success", "applied": applied, "errors": errors}

    from .handlers import execute_in_main_thread

    return execute_in_main_thread(_do)


def handle_apply_collections(cmd: dict) -> dict:
    moves = cmd.get("moves", [])

    def _do():
        import bpy

        applied = []
        errors = []
        for entry in moves:
            obj_name = entry.get("object", "")
            col_name = entry.get("collection", "")
            obj = bpy.data.objects.get(obj_name)
            if obj is None:
                errors.append({"object": obj_name, "error": f"Object '{obj_name}' not found"})
                continue

            col = bpy.data.collections.get(col_name)
            if col is None:
                col = bpy.data.collections.new(col_name)
                bpy.context.scene.collection.children.link(col)

            for old_col in list(obj.users_collection):
                old_col.objects.unlink(obj)
            col.objects.link(obj)
            applied.append({"object": obj_name, "collection": col_name})

        return {"status": "success", "applied": applied, "errors": errors}

    from .handlers import execute_in_main_thread

    return execute_in_main_thread(_do)


def handle_apply_gn_edits(cmd: dict) -> dict:
    """Apply GN graph operations.

    If ``transactional`` is true, performs a best-effort rollback via Blender undo
    when any step fails.
    """
    tree_name = cmd.get("target_tree", "")
    operations = cmd.get("operations", [])
    transactional = bool(cmd.get("transactional", False))

    def _do():
        import bpy

        tree = bpy.data.node_groups.get(tree_name)
        if tree is None:
            return {"status": "error", "error": f"Node tree '{tree_name}' not found"}

        applied = []
        errors = []
        rollback_performed = False

        if transactional:
            try:
                bpy.ops.ed.undo_push(message=f"Runtime GN transaction ({tree_name})")
            except Exception:
                pass

        for idx, op_entry in enumerate(operations):
            op = op_entry.get("op", "")
            params = op_entry.get("params", {})
            try:
                result = _execute_gn_operation(tree, op, params)
                applied.append({"index": idx, "op": op, "result": result})
            except Exception as exc:
                errors.append(
                    {
                        "index": idx,
                        "op": op,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                )
                if transactional:
                    try:
                        bpy.ops.ed.undo()
                        rollback_performed = True
                    except Exception:
                        rollback_performed = False
                break

        return {
            "status": "success" if not errors else "error",
            "applied": applied,
            "errors": errors,
            "transactional": transactional,
            "rolled_back": rollback_performed,
        }

    from .handlers import execute_in_main_thread

    return execute_in_main_thread(_do)


def _execute_gn_operation(tree, op: str, params: dict) -> dict:
    import bpy

    if op == "create_node":
        node_type = params["type"]
        name = params.get("name", "")
        location = params.get("location", [0, 0])
        node = tree.nodes.new(type=node_type)
        if name:
            node.name = name
            node.label = name
        node.location = (location[0], location[1])
        return {"node_name": node.name, "node_type": node.bl_idname}

    if op == "delete_node":
        node_name = params["name"]
        node = tree.nodes.get(node_name)
        if node is None:
            raise ValueError(f"Node '{node_name}' not found in tree '{tree.name}'")
        tree.nodes.remove(node)
        return {"deleted": node_name}

    if op == "connect_nodes":
        from_node = tree.nodes.get(params["from_node"])
        to_node = tree.nodes.get(params["to_node"])
        if from_node is None:
            raise ValueError(f"Source node '{params['from_node']}' not found")
        if to_node is None:
            raise ValueError(f"Target node '{params['to_node']}' not found")
        from_socket = _find_socket(from_node.outputs, params["from_socket"])
        to_socket = _find_socket(to_node.inputs, params["to_socket"])
        tree.links.new(from_socket, to_socket)
        return {"link": f"{from_node.name}:{from_socket.name} -> {to_node.name}:{to_socket.name}"}

    if op == "disconnect_nodes":
        from_node = tree.nodes.get(params["from_node"])
        to_node = tree.nodes.get(params["to_node"])
        if from_node is None or to_node is None:
            raise ValueError("Source or target node not found")
        from_socket = _find_socket(from_node.outputs, params["from_socket"])
        to_socket = _find_socket(to_node.inputs, params["to_socket"])
        for link in list(tree.links):
            if link.from_socket == from_socket and link.to_socket == to_socket:
                tree.links.remove(link)
                return {"disconnected": True}
        return {"disconnected": False, "note": "Link not found"}

    if op == "set_node_value":
        node = tree.nodes.get(params["node"])
        if node is None:
            raise ValueError(f"Node '{params['node']}' not found")
        socket = _find_socket(node.inputs, params["socket"])
        socket.default_value = params["value"]
        return {"node": node.name, "socket": socket.name, "value": str(socket.default_value)}

    if op == "set_node_property":
        node = tree.nodes.get(params["node"])
        if node is None:
            raise ValueError(f"Node '{params['node']}' not found")
        prop_name = params["property"]
        value = params["value"]
        if not hasattr(node, prop_name):
            writable = [prop.identifier for prop in node.bl_rna.properties if not prop.is_readonly]
            raise ValueError(
                f"Node '{node.name}' ({node.bl_idname}) has no property '{prop_name}'. "
                f"Writable properties: {writable}"
            )
        prop_rna = node.bl_rna.properties.get(prop_name)
        if prop_rna and prop_rna.is_readonly:
            raise ValueError(f"Property '{prop_name}' on '{node.name}' is read-only.")
        setattr(node, prop_name, value)
        new_val = getattr(node, prop_name)
        try:
            if hasattr(new_val, "__iter__") and not isinstance(new_val, str):
                new_val_out = list(new_val)
            else:
                new_val_out = new_val
        except Exception:
            new_val_out = str(new_val)
        return {"node": node.name, "property": prop_name, "value": new_val_out}

    if op == "move_node":
        node = tree.nodes.get(params["name"])
        if node is None:
            raise ValueError(f"Node '{params['name']}' not found")
        location = params["location"]
        node.location = (location[0], location[1])
        return {"moved": node.name, "location": location}

    if op == "create_frame":
        name = params.get("name", "Frame")
        location = params.get("location", [0, 0])
        frame = tree.nodes.new(type="NodeFrame")
        frame.name = name
        frame.label = params.get("label", name)
        frame.location = (location[0], location[1])
        for child_name in params.get("children", []):
            child = tree.nodes.get(child_name)
            if child is not None:
                child.parent = frame
        return {"frame_name": frame.name}

    if op == "insert_existing_group":
        group_name = params["group_name"]
        node_group = bpy.data.node_groups.get(group_name)
        if node_group is None:
            raise ValueError(f"Node group '{group_name}' not found")
        node = tree.nodes.new(type="GeometryNodeGroup")
        node.node_tree = node_group
        node.name = params.get("name", group_name)
        location = params.get("location", [0, 0])
        node.location = (location[0], location[1])
        return {"node_name": node.name, "group": node_group.name}

    raise ValueError(f"Unknown GN operation: {op}")


def _find_socket(sockets, name_or_index):
    if isinstance(name_or_index, int):
        if 0 <= name_or_index < len(sockets):
            return sockets[name_or_index]
        raise ValueError(f"Socket index {name_or_index} out of range (0-{len(sockets)-1})")
    for sock in sockets:
        if sock.name == name_or_index:
            return sock
    raise ValueError(f"Socket '{name_or_index}' not found. Available: {[sock.name for sock in sockets]}")


__all__ = [
    "handle_apply_collections",
    "handle_apply_gn_edits",
    "handle_apply_renames",
]
