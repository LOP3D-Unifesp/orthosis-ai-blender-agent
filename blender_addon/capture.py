"""Scene and Geometry Nodes snapshot capture from Blender.

Adapted from VBv1 addon/context.py. Produces JSON-serializable dicts
matching the schemas expected by the skills layer.

All functions here require bpy and MUST run on Blender's main thread.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import bpy


SCHEMA_VERSION = "0.2"
ADDON_VERSION = "0.1.0"

_MESH_PRIMITIVE_PREFIXES = (
    "Cube", "Plane", "Sphere", "UVSphere", "Icosphere",
    "Cylinder", "Cone", "Torus", "Circle", "Grid", "Monkey", "Suzanne",
)

MAX_NODES_PER_GROUP = 256  # configurável; árvores de ortose realistas têm 100-300 nós


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _context_id(prefix: str = "ctx") -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{ts}-{uuid4().hex[:8]}"


def _vector3(values) -> list[float]:
    return [float(values[0]), float(values[1]), float(values[2])]


def _json_safe_value(raw):
    """Convert Blender values into JSON-safe scalars/lists."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return int(raw)
    if isinstance(raw, float):
        return float(raw)
    if isinstance(raw, str):
        return raw
    if hasattr(raw, "__iter__") and not isinstance(raw, (bytes, bytearray)):
        try:
            return [_json_safe_value(v) for v in raw]
        except Exception:
            return str(raw)
    return str(raw)


# ---------------------------------------------------------------------------
# Scene snapshot
# ---------------------------------------------------------------------------

def _heuristic_class(obj: bpy.types.Object) -> str:
    if obj.type == "LIGHT":
        return "light"
    if obj.type == "CAMERA":
        return "camera"
    if obj.type == "EMPTY":
        return "empty"
    if obj.type == "CURVE":
        return "curve"
    if obj.type == "MESH":
        if obj.name.startswith(_MESH_PRIMITIVE_PREFIXES):
            return "primitive_mesh"
        return "mesh_object"
    return "other_object"


def _primary_collection(obj: bpy.types.Object) -> str | None:
    if obj.users_collection:
        return obj.users_collection[0].name
    return None


def _world_bounding_box(obj: bpy.types.Object) -> dict | None:
    try:
        m = obj.matrix_world
        xs, ys, zs = [], [], []
        for c in obj.bound_box:
            xs.append(m[0][0]*c[0] + m[0][1]*c[1] + m[0][2]*c[2] + m[0][3])
            ys.append(m[1][0]*c[0] + m[1][1]*c[1] + m[1][2]*c[2] + m[1][3])
            zs.append(m[2][0]*c[0] + m[2][1]*c[1] + m[2][2]*c[2] + m[2][3])
        return {
            "min": [round(min(xs), 4), round(min(ys), 4), round(min(zs), 4)],
            "max": [round(max(xs), 4), round(max(ys), 4), round(max(zs), 4)],
        }
    except Exception:
        return None


def _gn_inputs_payload(mod) -> list[dict]:
    """Extract current GN modifier interface input values."""
    if mod.type != "NODES":
        return []
    ng = getattr(mod, "node_group", None)
    if ng is None:
        return []

    payload = []
    try:
        # Blender 4.x
        if hasattr(ng, "interface") and hasattr(ng.interface, "items_tree"):
            for item in ng.interface.items_tree:
                if getattr(item, "item_type", None) != "SOCKET":
                    continue
                if getattr(item, "in_out", None) != "INPUT":
                    continue
                ident = getattr(item, "identifier", "") or item.name
                has_val = ident in mod.keys()
                payload.append({
                    "name": item.name,
                    "identifier": ident,
                    "socket_type": getattr(item, "socket_type", ""),
                    "has_value": has_val,
                    "value": _json_safe_value(mod[ident]) if has_val else None,
                })
        else:
            # Blender 3.x
            for sock in getattr(ng, "inputs", []):
                ident = getattr(sock, "identifier", "") or sock.name
                has_val = ident in mod.keys()
                payload.append({
                    "name": sock.name,
                    "identifier": ident,
                    "socket_type": getattr(sock, "bl_socket_idname", ""),
                    "has_value": has_val,
                    "value": _json_safe_value(mod[ident]) if has_val else None,
                })
    except Exception:
        return []
    return payload


def _modifier_payload(mod) -> dict:
    entry = {"name": mod.name, "type": mod.type, "enabled": bool(mod.show_viewport)}
    if mod.type == "NODES":
        entry["node_group"] = mod.node_group.name if mod.node_group else None
        gn_inputs = _gn_inputs_payload(mod)
        entry["gn_inputs"] = gn_inputs
        entry["gn_input_count"] = len(gn_inputs)
    return entry


def _object_payload(obj: bpy.types.Object) -> dict:
    payload = {
        "name": obj.name,
        "object_type": obj.type,
        "heuristic_class": _heuristic_class(obj),
        "collection": _primary_collection(obj),
        "visible": bool(obj.visible_get()),
        "hidden_render": bool(obj.hide_render),
        "selected": bool(obj.select_get()),
        "transform": {
            "location": _vector3(obj.location),
            "rotation_euler": _vector3(obj.rotation_euler),
            "scale": _vector3(obj.scale),
        },
        "modifiers": [_modifier_payload(mod) for mod in obj.modifiers],
        "materials": [
            slot.material.name for slot in obj.material_slots if slot.material
        ],
    }
    if obj.type == "MESH" and obj.data is not None:
        mesh = obj.data
        payload["mesh"] = {
            "vertex_count": len(mesh.vertices),
            "edge_count": len(mesh.edges),
            "polygon_count": len(mesh.polygons),
        }
        bbox = _world_bounding_box(obj)
        if bbox is not None:
            payload["world_bounding_box"] = bbox
    if obj.type == "CURVE" and obj.data is not None:
        payload["curve"] = {
            "spline_count": len(obj.data.splines),
        }
    return payload


def capture_scene_snapshot() -> dict:
    """Capture a full scene snapshot matching scene_context_inspector input schema."""
    scene = bpy.context.scene
    objects = [_object_payload(obj) for obj in scene.objects]
    return {
        "schema_version": SCHEMA_VERSION,
        "context_id": _context_id("ctx"),
        "generated_at": _utc_now_iso(),
        "blender_version": bpy.app.version_string,
        "source": {
            "generator": "blender_addon.capture",
            "blender_version": bpy.app.version_string,
            "addon_version": ADDON_VERSION,
            "blend_file": bpy.data.filepath or "",
        },
        "scene": {
            "name": scene.name,
            "object_count": len(objects),
            "unit_system": scene.unit_settings.system or "NONE",
            "frame_current": int(scene.frame_current),
            "active_object": (
                bpy.context.active_object.name if bpy.context.active_object else None
            ),
            "selected_objects": [o.name for o in bpy.context.selected_objects],
            "collections": [c.name for c in bpy.data.collections],
        },
        "objects": objects,
    }


# ---------------------------------------------------------------------------
# Node trees snapshot
# ---------------------------------------------------------------------------

def _node_group_interface(ng) -> dict:
    """Extract interface sockets, handling Blender 3.x and 4.x APIs."""
    inputs, outputs = [], []
    try:
        if hasattr(ng, "interface") and hasattr(ng.interface, "items_tree"):
            for item in ng.interface.items_tree:
                if getattr(item, "item_type", None) != "SOCKET":
                    continue
                entry = {
                    "name": item.name,
                    "type": getattr(item, "socket_type", ""),
                    "identifier": getattr(item, "identifier", "") or item.name,
                }
                if getattr(item, "in_out", None) == "INPUT":
                    inputs.append(entry)
                else:
                    outputs.append(entry)
        else:
            for inp in getattr(ng, "inputs", []):
                inputs.append({
                    "name": inp.name,
                    "type": getattr(inp, "bl_socket_idname", ""),
                    "identifier": getattr(inp, "identifier", "") or inp.name,
                })
            for out in getattr(ng, "outputs", []):
                outputs.append({
                    "name": out.name,
                    "type": getattr(out, "bl_socket_idname", ""),
                    "identifier": getattr(out, "identifier", "") or out.name,
                })
    except Exception:
        pass
    return {"inputs": inputs, "outputs": outputs}


def _node_payload(node) -> dict:
    return {
        "name": node.name,
        "label": node.label or "",
        "type": node.bl_idname,
        "location": [round(float(node.location.x), 1), round(float(node.location.y), 1)],
    }


def _node_group_bindings() -> dict[str, list[dict]]:
    """Map node_group_name -> list of modifier bindings with live values."""
    result: dict[str, list[dict]] = {}
    for obj in bpy.context.scene.objects:
        for mod in obj.modifiers:
            if mod.type == "NODES" and mod.node_group is not None:
                result.setdefault(mod.node_group.name, []).append({
                    "object_name": obj.name,
                    "modifier_name": mod.name,
                    "inputs": _gn_inputs_payload(mod),
                })
    return result


def _node_group_payload(ng, bindings_map: dict) -> dict:
    nodes_list = list(ng.nodes)
    bindings = bindings_map.get(ng.name, [])
    used_by = sorted({b["object_name"] for b in bindings if b.get("object_name")})

    # Capture links defensively.
    # Blender 5.x: link.from_socket can be a null C pointer on certain GN
    # interface links, causing an EXCEPTION_ACCESS_VIOLATION in the RNA getter
    # before Python can intercept it. Guard with is_valid (Blender 4.2+) and
    # node/socket None checks to avoid calling the getter on bad links.
    links_list = []
    for link in ng.links:
        try:
            # is_valid prevents calling the C getter on dangling sockets
            if hasattr(link, "is_valid") and not link.is_valid:
                continue
            from_node = link.from_node
            to_node = link.to_node
            if from_node is None or to_node is None:
                continue
            from_socket = link.from_socket
            to_socket = link.to_socket
            if from_socket is None or to_socket is None:
                continue
            links_list.append({
                "from_node": from_node.name,
                "from_socket": from_socket.name,
                "to_node": to_node.name,
                "to_socket": to_socket.name,
            })
        except Exception:
            # Last-resort skip — if C-level access still fails, don't crash
            continue

    truncated = len(nodes_list) > MAX_NODES_PER_GROUP
    payload = {
        "name": ng.name,
        "type": ng.bl_idname,
        "node_count": len(nodes_list),
        "nodes": [_node_payload(n) for n in nodes_list[:MAX_NODES_PER_GROUP]],
        "snapshot_truncated": truncated,
        "links": links_list,
        "interface": _node_group_interface(ng),
        "used_by_objects": used_by,
        "bindings": bindings,
    }
    return payload


def capture_node_trees_snapshot() -> dict:
    """Capture all GeometryNodeTree groups as a JSON-serializable dict."""
    bindings_map = _node_group_bindings()
    node_groups = [
        _node_group_payload(ng, bindings_map)
        for ng in bpy.data.node_groups
        if ng.bl_idname == "GeometryNodeTree"
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "context_id": _context_id("ntx"),
        "generated_at": _utc_now_iso(),
        "blender_version": bpy.app.version_string,
        "source": {
            "generator": "blender_addon.capture",
            "blender_version": bpy.app.version_string,
            "addon_version": ADDON_VERSION,
        },
        "node_groups": node_groups,
    }


def capture_full_snapshot() -> dict:
    """Capture both scene and node trees snapshots in one call."""
    scene = capture_scene_snapshot()
    node_trees = None
    try:
        node_trees = capture_node_trees_snapshot()
    except Exception:
        pass
    return {
        "scene_snapshot": scene,
        "node_trees_snapshot": node_trees,
    }
