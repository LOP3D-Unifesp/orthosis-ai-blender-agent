"""Validation and typed-mutation handlers for the bridge.

These close the two biggest gaps in the incremental workflow:

* seeing the result of a change (``render_viewport``) and measuring it
  numerically (``evaluate_geometry``);
* mutating the tree with typed primitives that validate sockets up front
  (``set_param``, ``set_node_input``, ``link_sockets``, ``add_node``) instead of
  hand-writing ``execute_code`` strings, plus label-based addressing
  (``resolve_node``) so callers stop depending on churny ``node.name`` values.

All handlers run on the Blender main thread via ``execute_in_main_thread``.
"""

from __future__ import annotations

import os
from typing import Any

import bpy

from .. import capture


def _main(func):
    from .handlers import execute_in_main_thread

    return execute_in_main_thread(func)


# ---------------------------------------------------------------------------
# Geometry evaluation
# ---------------------------------------------------------------------------


def _evaluated_world_points(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    mesh = ev.to_mesh()
    mw = obj.matrix_world
    xs, ys, zs = [], [], []
    try:
        for v in mesh.vertices:
            w = mw @ v.co
            xs.append(w.x)
            ys.append(w.y)
            zs.append(w.z)
    finally:
        ev.to_mesh_clear()
    return xs, ys, zs


def handle_evaluate_geometry(cmd: dict) -> dict:
    """Evaluate an object's final (modifier-applied) mesh and return stats.

    Returns vertex count and the world-space bounding box. Optionally returns a
    few sampled world points (``sample`` = N) for spot-checking that a transform
    moved geometry where expected.
    """
    obj_name = str(cmd.get("object", "")).strip()
    sample = int(cmd.get("sample", 0) or 0)

    def _do():
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            meshes = [o.name for o in bpy.data.objects if o.type == "MESH"]
            return {"status": "error", "error": f"Object '{obj_name}' not found", "available": meshes}
        xs, ys, zs = _evaluated_world_points(obj)
        if not xs:
            return {"status": "success", "result": {"object": obj_name, "vertex_count": 0}}
        result = {
            "object": obj_name,
            "vertex_count": len(xs),
            "bbox_min": [round(min(xs), 3), round(min(ys), 3), round(min(zs), 3)],
            "bbox_max": [round(max(xs), 3), round(max(ys), 3), round(max(zs), 3)],
            "bbox_size": [round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3), round(max(zs) - min(zs), 3)],
        }
        if sample > 0:
            step = max(1, len(xs) // sample)
            result["samples"] = [
                [round(xs[i], 2), round(ys[i], 2), round(zs[i], 2)] for i in range(0, len(xs), step)
            ][:sample]
        return {"status": "success", "result": result}

    return _main(_do)


# ---------------------------------------------------------------------------
# Viewport render
# ---------------------------------------------------------------------------

_VIEW_DIRS = {
    "top": (0.0, 0.0, 1.0),
    "bottom": (0.0, 0.0, -1.0),
    "front": (0.0, -1.0, 0.0),
    "back": (0.0, 1.0, 0.0),
    "side": (1.0, 0.0, 0.0),
    "iso": (1.0, 0.4, 0.6),
}


def handle_render_viewport(cmd: dict) -> dict:
    """Render one object with the Workbench engine and write a PNG to disk.

    Frames the object's evaluated bounds with an orthographic camera looking
    from ``view`` (top/front/side/iso/...). Other meshes are hidden for the
    render so the target is isolated. Returns the absolute PNG path for the
    caller to read.
    """
    obj_name = str(cmd.get("object", "")).strip()
    view = str(cmd.get("view", "iso")).strip().lower()
    out_path = str(cmd.get("path", "")).strip()
    res = int(cmd.get("resolution", 640) or 640)

    def _do():
        from mathutils import Vector

        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            return {"status": "error", "error": f"Object '{obj_name}' not found"}
        direction = Vector(_VIEW_DIRS.get(view, _VIEW_DIRS["iso"]))

        xs, ys, zs = _evaluated_world_points(obj)
        if not xs:
            return {"status": "error", "error": f"Object '{obj_name}' has no evaluated geometry"}
        center = Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2))
        size = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) or 1.0

        others = [o for o in bpy.data.objects if o.type == "MESH" and o is not obj]
        saved = {o.name: o.hide_render for o in others}
        for o in others:
            o.hide_render = True

        cam = bpy.data.objects.get("_bridge_cam")
        if cam is None:
            cam_data = bpy.data.cameras.new("_bridge_cam")
            cam = bpy.data.objects.new("_bridge_cam", cam_data)
            bpy.context.scene.collection.objects.link(cam)
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = size * 1.2
        cam.location = center + direction.normalized() * size * 2
        cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()

        scene = bpy.context.scene
        scene.camera = cam
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.resolution_x = res
        scene.render.resolution_y = res
        scene.render.image_settings.file_format = "PNG"
        if not out_path:
            root = os.path.dirname(bpy.data.filepath) or os.getcwd()
            path = os.path.join(root, "runtime", f"_render_{obj_name}_{view}.png")
        else:
            path = out_path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        scene.render.filepath = path

        try:
            rr = bpy.ops.render.render(write_still=True)
            ok = "FINISHED" in rr
        finally:
            for o in others:
                o.hide_render = saved[o.name]

        if not ok:
            return {"status": "error", "error": "render did not finish"}
        return {"status": "success", "result": {"path": path, "view": view, "object": obj_name}}

    return _main(_do)


# ---------------------------------------------------------------------------
# Typed mutations
# ---------------------------------------------------------------------------


def handle_set_param(cmd: dict) -> dict:
    """Set a Geometry Nodes modifier input on an object by socket identifier."""
    obj_name = str(cmd.get("object", "")).strip()
    identifier = str(cmd.get("identifier", "")).strip()
    value = cmd.get("value")

    def _do():
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            return {"status": "error", "error": f"Object '{obj_name}' not found"}
        mod = next((m for m in obj.modifiers if m.type == "NODES" and m.node_group), None)
        if mod is None:
            return {"status": "error", "error": f"Object '{obj_name}' has no Geometry Nodes modifier"}
        if identifier not in mod.keys():
            avail = [k for k in mod.keys() if k.startswith("Socket")]
            return {"status": "error", "error": f"Identifier '{identifier}' not on modifier", "available": avail}
        before = capture._json_safe_value(mod[identifier])
        try:
            mod[identifier] = value
        except Exception as exc:
            return {"status": "error", "error": f"could not set value: {exc}"}
        obj.update_tag()
        bpy.context.view_layer.update()
        return {
            "status": "success",
            "result": {
                "object": obj_name,
                "identifier": identifier,
                "before": before,
                "after": capture._json_safe_value(mod[identifier]),
            },
        }

    return _main(_do)


def _resolve_node(tree, ref: str):
    """Find a node by exact name first, then exact label, then label substring."""
    node = tree.nodes.get(ref)
    if node is not None:
        return node
    for n in tree.nodes:
        if (n.label or "") == ref:
            return n
    low = ref.lower()
    for n in tree.nodes:
        if low in (n.label or "").lower():
            return n
    return None


def handle_resolve_node(cmd: dict) -> dict:
    """Resolve a node reference (name OR label) to its canonical name.

    Lets callers address nodes by the stable visible label instead of the churny
    internal ``node.name`` (which Blender suffixes with .001, .002, ...).
    """
    tree_name = str(cmd.get("tree_name", "")).strip()
    ref = str(cmd.get("ref", "")).strip()

    def _do():
        tree = bpy.data.node_groups.get(tree_name)
        if tree is None:
            return {"status": "error", "error": f"Tree '{tree_name}' not found"}
        node = _resolve_node(tree, ref)
        if node is None:
            return {"status": "error", "error": f"No node matching ref '{ref}'"}
        return {
            "status": "success",
            "result": {
                "name": node.name,
                "label": node.label or "",
                "type": node.bl_idname,
                "inputs": [s.name for s in node.inputs],
                "outputs": [s.name for s in node.outputs],
            },
        }

    return _main(_do)


def handle_set_node_input(cmd: dict) -> dict:
    """Set a node's unlinked input socket default by node ref + socket name/index."""
    tree_name = str(cmd.get("tree_name", "")).strip()
    ref = str(cmd.get("node", "")).strip()
    socket = cmd.get("socket")
    value = cmd.get("value")

    def _do():
        tree = bpy.data.node_groups.get(tree_name)
        if tree is None:
            return {"status": "error", "error": f"Tree '{tree_name}' not found"}
        node = _resolve_node(tree, ref)
        if node is None:
            return {"status": "error", "error": f"Node '{ref}' not found"}
        try:
            sock = node.inputs[socket]
        except Exception:
            names = [s.name for s in node.inputs]
            return {"status": "error", "error": f"Socket '{socket}' not on node", "inputs": names}
        if sock.is_linked:
            return {"status": "error", "error": f"Socket '{sock.name}' is linked; unlink before setting a default"}
        if not hasattr(sock, "default_value"):
            return {"status": "error", "error": f"Socket '{sock.name}' has no default_value"}
        try:
            sock.default_value = value
        except Exception as exc:
            return {"status": "error", "error": f"could not set value: {exc}"}
        return {
            "status": "success",
            "result": {"node": node.name, "socket": sock.name, "value": capture._json_safe_value(sock.default_value)},
        }

    return _main(_do)


def handle_link_sockets(cmd: dict) -> dict:
    """Create a link between two nodes' sockets, addressed by name/label."""
    tree_name = str(cmd.get("tree_name", "")).strip()
    from_ref = str(cmd.get("from_node", "")).strip()
    from_socket = cmd.get("from_socket", 0)
    to_ref = str(cmd.get("to_node", "")).strip()
    to_socket = cmd.get("to_socket", 0)

    def _do():
        tree = bpy.data.node_groups.get(tree_name)
        if tree is None:
            return {"status": "error", "error": f"Tree '{tree_name}' not found"}
        a = _resolve_node(tree, from_ref)
        b = _resolve_node(tree, to_ref)
        if a is None or b is None:
            return {"status": "error", "error": f"node not found (from={from_ref!r} to={to_ref!r})"}
        try:
            out_sock = a.outputs[from_socket]
            in_sock = b.inputs[to_socket]
        except Exception as exc:
            return {"status": "error", "error": f"socket lookup failed: {exc}"}
        link = tree.links.new(out_sock, in_sock)
        return {
            "status": "success",
            "result": {
                "from": f"{a.name}.{out_sock.name}",
                "to": f"{b.name}.{in_sock.name}",
                "valid": bool(getattr(link, "is_valid", True)),
            },
        }

    return _main(_do)


def handle_add_node(cmd: dict) -> dict:
    """Add a node of ``bl_idname`` with an optional name/label/location/parent."""
    tree_name = str(cmd.get("tree_name", "")).strip()
    bl_idname = str(cmd.get("bl_idname", "")).strip()
    name = str(cmd.get("name", "")).strip()
    label = str(cmd.get("label", "")).strip()
    location = cmd.get("location") or [0, 0]
    operation = cmd.get("operation")
    parent = str(cmd.get("parent", "")).strip()

    def _do():
        tree = bpy.data.node_groups.get(tree_name)
        if tree is None:
            return {"status": "error", "error": f"Tree '{tree_name}' not found"}
        try:
            node = tree.nodes.new(type=bl_idname)
        except Exception as exc:
            return {"status": "error", "error": f"could not create '{bl_idname}': {exc}"}
        if name:
            node.name = name
        if label:
            node.label = label
        try:
            node.location = (float(location[0]), float(location[1]))
        except Exception:
            pass
        if operation and hasattr(node, "operation"):
            try:
                node.operation = operation
            except Exception:
                pass
        if parent:
            frame = _resolve_node(tree, parent)
            if frame is not None and frame.bl_idname == "NodeFrame":
                node.parent = frame
        return {
            "status": "success",
            "result": {"name": node.name, "label": node.label or "", "type": node.bl_idname},
        }

    return _main(_do)


__all__ = [
    "handle_evaluate_geometry",
    "handle_render_viewport",
    "handle_set_param",
    "handle_resolve_node",
    "handle_set_node_input",
    "handle_link_sockets",
    "handle_add_node",
]
