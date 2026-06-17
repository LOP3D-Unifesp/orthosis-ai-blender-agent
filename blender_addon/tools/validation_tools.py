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


def _undo_push(message: str) -> None:
    """Register an undo step so bridge mutations land in Blender's undo history.

    Without this, edits applied from the bridge are not on the undo stack and a
    user Ctrl+Z can silently revert a whole batch of them at once. Best-effort:
    if the operator context isn't available we just skip it.
    """
    try:
        bpy.ops.ed.undo_push(message=message)
    except Exception:
        pass


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


def _eval_points(obj):
    """World-space evaluated vertices of ``obj`` as a list of (x,y,z) tuples."""
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    me = ev.to_mesh()
    mw = obj.matrix_world
    pts = [tuple(mw @ v.co) for v in me.vertices]
    ev.to_mesh_clear()
    return pts


def _bbox_stats(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; zs = [p[2] for p in pts]
    return {
        "count": len(pts),
        "bbox_min": [round(min(xs), 3), round(min(ys), 3), round(min(zs), 3)],
        "bbox_max": [round(max(xs), 3), round(max(ys), 3), round(max(zs), 3)],
        "bbox_size": [round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3), round(max(zs) - min(zs), 3)],
    }


_AXIS = {"x": 0, "y": 1, "z": 2}


def handle_evaluate_geometry(cmd: dict) -> dict:
    """Evaluate an object's final mesh and return measurable stats.

    Beyond bbox + samples, supports the measurements calibration actually needs:

    * ``region`` {"axis","min","max"} — restrict to verts inside an axis range
      (e.g. just the fingers) before any stat.
    * ``diff``   {"params_a":{Socket:val}, "params_b":{...}, "threshold":5} —
      evaluate at two GN-parameter states and keep only verts that moved more
      than ``threshold`` mm (e.g. the fingers between flex 0 and 90). Params are
      restored afterwards. Stats then describe the moved set (in state A).
    * ``clusters`` {"axis":"x","k":4} — split the working set into k equal-count
      groups along an axis and report per-group centroid + per-axis min/max
      (e.g. per-finger top Z to detect a staircase). Returns ``cluster_spread``
      per axis = max(group max) - min(group min) helper for that axis.
    """
    obj_name = str(cmd.get("object", "")).strip()
    sample = int(cmd.get("sample", 0) or 0)
    region = cmd.get("region") or None
    diff = cmd.get("diff") or None
    clusters = cmd.get("clusters") or None

    def _apply(mod, params):
        saved = {}
        for k, v in (params or {}).items():
            if mod is not None and k in mod.keys():
                saved[k] = mod[k]
                mod[k] = v
        return saved

    def _region_filter(pts):
        if not (region and isinstance(region, dict)):
            return pts
        ax = _AXIS.get(str(region.get("axis", "y")).lower(), 1)
        lo = float(region.get("min", -1e18)); hi = float(region.get("max", 1e18))
        return [p for p in pts if lo <= p[ax] <= hi]

    def _do():
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            meshes = [o.name for o in bpy.data.objects if o.type == "MESH"]
            return {"status": "error", "error": f"Object '{obj_name}' not found", "available": meshes}
        mod = next((m for m in obj.modifiers if m.type == "NODES" and m.node_group), None)

        moved_meta = None
        if diff and isinstance(diff, dict):
            thr = float(diff.get("threshold", 5))
            sa = _apply(mod, diff.get("params_a") or {})
            obj.update_tag(); bpy.context.view_layer.update()
            pa = _eval_points(obj)
            sb = _apply(mod, diff.get("params_b") or {})
            obj.update_tag(); bpy.context.view_layer.update()
            pb = _eval_points(obj)
            # restore (b first then a so originals win)
            for k, v in sb.items(): mod[k] = v
            for k, v in sa.items(): mod[k] = v
            obj.update_tag(); bpy.context.view_layer.update()
            n = min(len(pa), len(pb))
            idx = [i for i in range(n) if sum((pb[i][j] - pa[i][j]) ** 2 for j in range(3)) ** 0.5 > thr]
            pts = [pa[i] for i in idx]
            moved_meta = {"moved_count": len(idx), "threshold": thr, "total": n}
        else:
            pts = _eval_points(obj)

        pts = _region_filter(pts)
        if not pts:
            return {"status": "success", "result": {"object": obj_name, "vertex_count": 0, "note": "no verts after region/diff"}}

        result = {"object": obj_name, "vertex_count": len(pts)}
        result.update(_bbox_stats(pts))
        if moved_meta:
            result["diff"] = moved_meta
        if sample > 0:
            step = max(1, len(pts) // sample)
            result["samples"] = [[round(p[0], 2), round(p[1], 2), round(p[2], 2)] for p in pts[::step]][:sample]
        if clusters and isinstance(clusters, dict):
            ax = _AXIS.get(str(clusters.get("axis", "x")).lower(), 0)
            k = max(1, min(int(clusters.get("k", 4) or 4), 12))
            sp = sorted(pts, key=lambda p: p[ax])
            step = len(sp) // k if len(sp) >= k else 1
            groups = []
            for j in range(k):
                g = sp[j * step:(j + 1) * step if j < k - 1 else None]
                if not g:
                    continue
                gx = [p[0] for p in g]; gy = [p[1] for p in g]; gz = [p[2] for p in g]
                groups.append({
                    "n": len(g),
                    "centroid": [round(sum(gx) / len(g), 1), round(sum(gy) / len(g), 1), round(sum(gz) / len(g), 1)],
                    "min": [round(min(gx), 1), round(min(gy), 1), round(min(gz), 1)],
                    "max": [round(max(gx), 1), round(max(gy), 1), round(max(gz), 1)],
                })
            spread = {}
            for axn, axi in _AXIS.items():
                mxs = [grp["max"][axi] for grp in groups]; mns = [grp["min"][axi] for grp in groups]
                if mxs:
                    spread["max_" + axn] = round(max(mxs) - min(mxs), 1)
            result["clusters"] = {"axis": clusters.get("axis", "x"), "k": k, "groups": groups, "cluster_spread": spread}
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
    """Render an object (Workbench) and write a PNG to disk for spot-checking.

    Frames the target's evaluated bounds with an orthographic camera from
    ``view`` (top/front/side/iso). Beyond the basic isolate-and-shoot, supports
    the things real validation needs:

    * ``focus``   {"axis": "x"|"y"|"z", "min": float, "max": float} — frame only
      the verts of the target inside that axis range (e.g. just the fingers),
      so the forearm doesn't shrink the subject to nothing.
    * ``overlay`` [obj, ...] — extra objects kept visible (e.g. the scan), and
      ``xray``/``xray_alpha`` to make everything semi-transparent so the target
      shows through the reference.
    * ``keep``    [obj, ...] — explicit visible set (overrides isolate logic).
    * ``resolution_x``/``resolution_y`` — non-square frames.
    * ``params``  {"Socket_N": value} — apply to the target's GN modifier for a
      transient pose; restored after the render unless ``restore`` is false.

    Scene camera / engine / resolution / shading are restored afterwards.
    """
    obj_name = str(cmd.get("object", "")).strip()
    view = str(cmd.get("view", "iso")).strip().lower()
    out_path = str(cmd.get("path", "")).strip()
    res = int(cmd.get("resolution", 640) or 640)
    res_x = int(cmd.get("resolution_x", res) or res)
    res_y = int(cmd.get("resolution_y", res) or res)
    focus = cmd.get("focus") or None
    overlay = cmd.get("overlay") or []
    keep = cmd.get("keep") or None
    xray = bool(cmd.get("xray", bool(overlay)))
    xray_alpha = float(cmd.get("xray_alpha", 0.45))
    params = cmd.get("params") or {}
    restore = bool(cmd.get("restore", True))
    if isinstance(overlay, str):
        overlay = [overlay]

    def _do():
        from mathutils import Vector

        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            return {"status": "error", "error": f"Object '{obj_name}' not found"}
        direction = Vector(_VIEW_DIRS.get(view, _VIEW_DIRS["iso"]))
        scene = bpy.context.scene

        # transient pose
        mod = next((m for m in obj.modifiers if m.type == "NODES" and m.node_group), None)
        saved_params = {}
        if params and mod is not None:
            for k, v in params.items():
                if k in mod.keys():
                    saved_params[k] = mod[k]
                    mod[k] = v
            obj.update_tag()
            bpy.context.view_layer.update()

        # evaluated points (optionally focus-filtered for framing)
        deps = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(deps)
        me = ev.to_mesh()
        mw = obj.matrix_world
        pts = [mw @ v.co for v in me.vertices]
        ev.to_mesh_clear()
        if not pts:
            return {"status": "error", "error": f"Object '{obj_name}' has no evaluated geometry"}
        framing = pts
        if focus and isinstance(focus, dict):
            ax = {"x": 0, "y": 1, "z": 2}.get(str(focus.get("axis", "y")).lower(), 1)
            lo = float(focus.get("min", -1e18))
            hi = float(focus.get("max", 1e18))
            framing = [p for p in pts if lo <= p[ax] <= hi] or pts
        xs = [p.x for p in framing]; ys = [p.y for p in framing]; zs = [p.z for p in framing]
        center = Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2))
        size = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) or 1.0

        # visibility
        visible = {obj_name}
        if keep:
            visible = set(keep) | {obj_name}
        elif overlay:
            visible |= set(overlay)
        meshes = [o for o in bpy.data.objects if o.type == "MESH"]
        saved_vis = {o.name: o.hide_render for o in meshes}
        for o in meshes:
            o.hide_render = o.name not in visible

        cam = bpy.data.objects.get("_bridge_render_cam")
        if cam is None:
            cam_data = bpy.data.cameras.new("_bridge_render_cam")
            cam = bpy.data.objects.new("_bridge_render_cam", cam_data)
            scene.collection.objects.link(cam)
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = size * 1.18
        cam.location = center + direction.normalized() * (size * 2 + 100)
        cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()

        # save scene render state
        prev = {
            "camera": scene.camera, "engine": scene.render.engine,
            "rx": scene.render.resolution_x, "ry": scene.render.resolution_y,
            "filepath": scene.render.filepath,
        }
        prev_xray = getattr(scene.display.shading, "show_xray", False)
        prev_xray_a = getattr(scene.display.shading, "xray_alpha", 1.0)
        scene.camera = cam
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.resolution_x = res_x
        scene.render.resolution_y = res_y
        scene.render.image_settings.file_format = "PNG"
        try:
            scene.display.shading.light = "STUDIO"
            scene.display.shading.show_cavity = True
            scene.display.shading.color_type = "SINGLE"
            scene.display.shading.show_xray = xray
            scene.display.shading.xray_alpha = xray_alpha
        except Exception:
            pass
        if not out_path:
            root = os.path.dirname(bpy.data.filepath) or os.getcwd()
            path = os.path.join(root, "runtime", f"_render_{obj_name}_{view}.png")
        else:
            path = out_path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        scene.render.filepath = path

        bbox = {"min": [round(min(xs), 1), round(min(ys), 1), round(min(zs), 1)],
                "max": [round(max(xs), 1), round(max(ys), 1), round(max(zs), 1)]}
        try:
            rr = bpy.ops.render.render(write_still=True)
            ok = "FINISHED" in rr
        finally:
            for name, hv in saved_vis.items():
                bpy.data.objects[name].hide_render = hv
            scene.camera = prev["camera"]
            scene.render.engine = prev["engine"]
            scene.render.resolution_x = prev["rx"]
            scene.render.resolution_y = prev["ry"]
            scene.render.filepath = prev["filepath"]
            try:
                scene.display.shading.show_xray = prev_xray
                scene.display.shading.xray_alpha = prev_xray_a
            except Exception:
                pass
            if params and mod is not None and restore:
                for k, v in saved_params.items():
                    mod[k] = v
                obj.update_tag()

        if not ok:
            return {"status": "error", "error": "render did not finish"}
        return {"status": "success", "result": {"path": path, "view": view, "object": obj_name, "framed_bbox": bbox}}

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
        _undo_push(f"bridge set_param {identifier}")
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
        _undo_push(f"bridge set_node_input {node.name}.{sock.name}")
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
        _undo_push(f"bridge link {a.name}->{b.name}")
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
        _undo_push(f"bridge add_node {node.name}")
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
