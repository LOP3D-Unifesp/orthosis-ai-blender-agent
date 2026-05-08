"""Blender-side command handlers executed on the main thread.

This module is the low-level execution layer used by runtime dispatch.
"""

from __future__ import annotations

import ast
import io
import json
import os
import re
import threading
import time
import traceback
import unicodedata
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import bpy

from .. import capture


_MAIN_THREAD_TIMEOUT = 15.0  # seconds before giving up waiting for Blender main thread


def execute_in_main_thread(func):
    """Run ``func`` on Blender's main thread and block until completion.

    Raises RuntimeError if the main thread does not respond within
    _MAIN_THREAD_TIMEOUT seconds (e.g. blocked by a modal operator).
    """
    result: dict[str, Any] = {}

    def _wrapper():
        try:
            result["data"] = func()
        except Exception as exc:
            result["data"] = {
                "status": "error",
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }

    if threading.current_thread() is threading.main_thread():
        _wrapper()
        return result["data"]

    bpy.app.timers.register(_wrapper)
    deadline = time.monotonic() + _MAIN_THREAD_TIMEOUT
    while "data" not in result:
        if time.monotonic() > deadline:
            return {
                "status": "error",
                "error": "Blender main thread did not respond within "
                         f"{_MAIN_THREAD_TIMEOUT:.0f}s. A modal operator may "
                         "be blocking execution.",
            }
        time.sleep(0.01)
    return result["data"]


# ---------------------------------------------------------------------------
# Capture handlers
# ---------------------------------------------------------------------------


def handle_capture_scene(cmd: dict) -> dict:
    def _do():
        return {"status": "success", "result": capture.capture_scene_snapshot()}

    return execute_in_main_thread(_do)


def handle_capture_node_trees(cmd: dict) -> dict:
    def _do():
        return {"status": "success", "result": capture.capture_node_trees_snapshot()}

    return execute_in_main_thread(_do)


def handle_capture_full(cmd: dict) -> dict:
    def _do():
        return {"status": "success", "result": capture.capture_full_snapshot()}

    return execute_in_main_thread(_do)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def handle_get_node_context(cmd: dict) -> dict:
    """Return local node context for one target node and its neighborhood."""
    tree_name = cmd.get("tree_name", "")
    node_name = cmd.get("node_name", "")
    label = cmd.get("label", "")
    radius = int(cmd.get("radius", 1) or 1)
    radius = max(1, min(radius, 3))

    def _do():
        tree = bpy.data.node_groups.get(tree_name)
        if tree is None:
            available = [ng.name for ng in bpy.data.node_groups if ng.bl_idname == "GeometryNodeTree"]
            return {"status": "error", "error": f"Tree '{tree_name}' not found", "available": available}

        target = None
        if node_name:
            target = tree.nodes.get(node_name)
        if target is None and label:
            for node in tree.nodes:
                if node.label == label or node.name == label:
                    target = node
                    break
        if target is None:
            all_nodes = [{"name": n.name, "label": n.label} for n in tree.nodes]
            return {
                "status": "error",
                "error": f"Node not found: name={node_name!r} label={label!r}",
                "available_nodes": all_nodes,
            }

        visited = {target.name}
        frontier = {target.name}
        for _ in range(radius):
            next_frontier: set[str] = set()
            for link in tree.links:
                try:
                    if hasattr(link, "is_valid") and not link.is_valid:
                        continue
                    from_node = link.from_node
                    to_node = link.to_node
                    if from_node is None or to_node is None:
                        continue
                    if from_node.name in frontier and to_node.name not in visited:
                        next_frontier.add(to_node.name)
                    if to_node.name in frontier and from_node.name not in visited:
                        next_frontier.add(from_node.name)
                except Exception:
                    continue
            visited |= next_frontier
            frontier = next_frontier

        nodes_payload = []
        for node in tree.nodes:
            if node.name not in visited:
                continue
            entry = {
                "name": node.name,
                "label": node.label or "",
                "type": node.bl_idname,
                "location": [round(float(node.location.x), 1), round(float(node.location.y), 1)],
                "is_target": node.name == target.name,
            }
            if node.name == target.name:
                inputs = []
                for sock in node.inputs:
                    sock_data = {"name": sock.name, "type": sock.bl_idname}
                    if hasattr(sock, "default_value"):
                        sock_data["default_value"] = capture._json_safe_value(sock.default_value)
                    inputs.append(sock_data)
                entry["inputs"] = inputs
            nodes_payload.append(entry)

        links_payload = []
        for link in tree.links:
            try:
                if hasattr(link, "is_valid") and not link.is_valid:
                    continue
                from_node = link.from_node
                to_node = link.to_node
                if from_node is None or to_node is None:
                    continue
                if from_node.name in visited and to_node.name in visited:
                    links_payload.append(
                        {
                            "from_node": from_node.name,
                            "from_socket": link.from_socket.name,
                            "to_node": to_node.name,
                            "to_socket": link.to_socket.name,
                        }
                    )
            except Exception:
                continue

        return {
            "status": "success",
            "result": {
                "tree_name": tree_name,
                "target_node": target.name,
                "radius": radius,
                "node_count": len(nodes_payload),
                "nodes": nodes_payload,
                "links": links_payload,
            },
        }

    return execute_in_main_thread(_do)


def _expand_node_neighborhood(tree, seed_names: set[str], radius: int = 1) -> set[str]:
    radius = max(0, min(int(radius or 0), 3))
    visited = set(seed_names)
    frontier = set(seed_names)
    if radius <= 0:
        return visited
    for _ in range(radius):
        next_frontier: set[str] = set()
        for link in tree.links:
            try:
                if hasattr(link, "is_valid") and not link.is_valid:
                    continue
                from_node = link.from_node
                to_node = link.to_node
                if from_node is None or to_node is None:
                    continue
                if from_node.name in frontier and to_node.name not in visited:
                    next_frontier.add(to_node.name)
                if to_node.name in frontier and from_node.name not in visited:
                    next_frontier.add(from_node.name)
            except Exception:
                continue
        if not next_frontier:
            break
        visited |= next_frontier
        frontier = next_frontier
    return visited


def _serialize_nodes_and_links(
    tree,
    node_names: set[str],
    *,
    include_values: bool = True,
    include_properties: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes_payload: list[dict[str, Any]] = []
    for node in tree.nodes:
        if node.name not in node_names:
            continue
        entry: dict[str, Any] = {
            "name": node.name,
            "label": node.label or "",
            "type": node.bl_idname,
            "location": [round(float(node.location.x), 1), round(float(node.location.y), 1)],
            "parent_frame": node.parent.name if getattr(node, "parent", None) else "",
            "is_selected": bool(getattr(node, "select", False)),
        }
        if include_values:
            input_values: list[dict[str, Any]] = []
            for sock in node.inputs:
                sock_data = {"name": sock.name, "type": sock.bl_idname}
                if hasattr(sock, "default_value"):
                    sock_data["default_value"] = capture._json_safe_value(sock.default_value)
                input_values.append(sock_data)
            entry["input_values"] = input_values
        if include_properties:
            properties = {}
            for prop_name in ("operation", "data_type", "domain", "mode", "clamp"):
                if hasattr(node, prop_name):
                    try:
                        properties[prop_name] = capture._json_safe_value(getattr(node, prop_name))
                    except Exception:
                        continue
            if properties:
                entry["properties"] = properties
        nodes_payload.append(entry)

    links_payload: list[dict[str, Any]] = []
    for link in tree.links:
        try:
            if hasattr(link, "is_valid") and not link.is_valid:
                continue
            from_node = link.from_node
            to_node = link.to_node
            if from_node is None or to_node is None:
                continue
            if from_node.name in node_names and to_node.name in node_names:
                links_payload.append(
                    {
                        "from_node": from_node.name,
                        "from_socket": link.from_socket.name,
                        "to_node": to_node.name,
                        "to_socket": link.to_socket.name,
                    }
                )
        except Exception:
            continue

    return nodes_payload, links_payload


def handle_get_selected_nodes_context(cmd: dict) -> dict:
    tree_name = cmd.get("tree_name", "")
    include_neighbors = bool(cmd.get("include_neighbors", True))
    radius = max(1, min(int(cmd.get("radius", 1) or 1), 3))

    def _do():
        tree = bpy.data.node_groups.get(tree_name)
        if tree is None:
            return {"status": "error", "error": f"Tree '{tree_name}' not found"}
        selected = [node for node in tree.nodes if getattr(node, "select", False)]
        if not selected:
            return {"status": "error", "error": f"No selected nodes in tree '{tree_name}'"}

        node_names = {node.name for node in selected}
        if include_neighbors:
            node_names = _expand_node_neighborhood(tree, node_names, radius=radius)
        nodes_payload, links_payload = _serialize_nodes_and_links(tree, node_names)
        return {
            "status": "success",
            "result": {
                "tree_name": tree_name,
                "selected_nodes_count": len(selected),
                "include_neighbors": include_neighbors,
                "radius": radius,
                "nodes": nodes_payload,
                "links": links_payload,
                "summary": {
                    "node_count": len(nodes_payload),
                    "link_count": len(links_payload),
                },
            },
        }

    return execute_in_main_thread(_do)


def handle_get_active_frame_context(cmd: dict) -> dict:
    tree_name = cmd.get("tree_name", "")
    requested_frame = str(cmd.get("frame_name", "")).strip()
    include_neighbors = bool(cmd.get("include_neighbors", False))
    radius = max(1, min(int(cmd.get("radius", 1) or 1), 3))

    def _do():
        tree = bpy.data.node_groups.get(tree_name)
        if tree is None:
            return {"status": "error", "error": f"Tree '{tree_name}' not found"}

        def _frame_identity(value: str) -> str:
            return str(value or "").strip().lower()

        frame = None
        if requested_frame:
            candidate = tree.nodes.get(requested_frame)
            if candidate is not None and candidate.bl_idname == "NodeFrame":
                frame = candidate
        if frame is None and requested_frame:
            wanted = _frame_identity(requested_frame)
            for node in tree.nodes:
                if node.bl_idname != "NodeFrame":
                    continue
                if _frame_identity(node.name) == wanted or _frame_identity(node.label) == wanted:
                    frame = node
                    break
        if frame is None:
            active = getattr(tree.nodes, "active", None)
            if active is not None and active.bl_idname == "NodeFrame":
                frame = active
        if frame is None:
            for node in tree.nodes:
                if node.bl_idname == "NodeFrame" and getattr(node, "select", False):
                    frame = node
                    break
        if frame is None:
            available_frames = [
                {"name": node.name, "label": node.label or ""}
                for node in tree.nodes
                if node.bl_idname == "NodeFrame"
            ]
            return {
                "status": "error",
                "error": f"No active/selected frame found in tree '{tree_name}'",
                "requested_frame": requested_frame,
                "available_frames": available_frames,
            }

        child_names = {node.name for node in tree.nodes if getattr(node, "parent", None) == frame}
        node_names = set(child_names)
        node_names.add(frame.name)
        if include_neighbors:
            node_names = _expand_node_neighborhood(tree, node_names, radius=radius)
        nodes_payload, links_payload = _serialize_nodes_and_links(tree, node_names)

        return {
            "status": "success",
            "result": {
                "tree_name": tree_name,
                "frame_name": frame.name,
                "frame_label": frame.label or frame.name,
                "child_count": len(child_names),
                "include_neighbors": include_neighbors,
                "radius": radius,
                "nodes": nodes_payload,
                "links": links_payload,
                "summary": {
                    "node_count": len(nodes_payload),
                    "link_count": len(links_payload),
                },
            },
        }

    return execute_in_main_thread(_do)


def handle_get_local_subgraph_context(cmd: dict) -> dict:
    tree_name = cmd.get("tree_name", "")
    scope_mode = str(cmd.get("scope_mode", "")).strip().lower()
    include_values = bool(cmd.get("include_values", True))
    include_properties = bool(cmd.get("include_properties", True))
    max_nodes = max(1, min(int(cmd.get("max_nodes", 80) or 80), 2000))

    def _do():
        tree = bpy.data.node_groups.get(tree_name)
        if tree is None:
            return {"status": "error", "error": f"Tree '{tree_name}' not found"}
        node_by_name = {node.name: node for node in tree.nodes}

        selected_names: set[str] = set()
        missing_nodes: list[str] = []
        if scope_mode == "by_nodes":
            names_raw = cmd.get("node_names", [])
            if not isinstance(names_raw, list) or not names_raw:
                return {"status": "error", "error": "scope_mode='by_nodes' requires non-empty node_names list."}
            for item in names_raw:
                name = str(item).strip()
                if not name:
                    continue
                if name in node_by_name:
                    selected_names.add(name)
                else:
                    missing_nodes.append(name)
            if not selected_names:
                return {"status": "error", "error": "None of requested node_names were found", "missing_nodes": missing_nodes}
        elif scope_mode == "neighborhood":
            center_node = str(cmd.get("center_node", "")).strip()
            if not center_node:
                return {"status": "error", "error": "scope_mode='neighborhood' requires center_node."}
            if center_node not in node_by_name:
                return {"status": "error", "error": f"center_node '{center_node}' not found in tree '{tree_name}'"}
            hops = max(1, min(int(cmd.get("hops", 1) or 1), 2))
            selected_names = _expand_node_neighborhood(tree, {center_node}, radius=hops)
        else:
            return {"status": "error", "error": "Invalid scope_mode. Use 'by_nodes' or 'neighborhood'."}

        ordered = [node.name for node in tree.nodes if node.name in selected_names][:max_nodes]
        limited = set(ordered)
        nodes_payload, links_payload = _serialize_nodes_and_links(
            tree,
            limited,
            include_values=include_values,
            include_properties=include_properties,
        )
        return {
            "status": "success",
            "result": {
                "tree_name": tree_name,
                "scope_mode": scope_mode,
                "missing_nodes": missing_nodes,
                "nodes": nodes_payload,
                "links": links_payload,
                "summary": {
                    "node_count": len(nodes_payload),
                    "link_count": len(links_payload),
                    "requested_max_nodes": max_nodes,
                },
            },
        }

    return execute_in_main_thread(_do)


# ---------------------------------------------------------------------------
# Direct-read handlers (sem snapshot pipeline — sem cap de nós)
# ---------------------------------------------------------------------------


def handle_list_tree_nodes(cmd: dict) -> dict:
    """Retorna o inventário completo de nós de uma árvore GN, sem cap.

    Lê diretamente via bpy.data.node_groups — não passa pelo pipeline de
    snapshot. Ideal para árvores com 100+ nós onde o snapshot pode estar
    truncado. Deve ser usado antes de qualquer operação que dependa de nomes
    precisos de nós.
    """
    tree_name = str(cmd.get("tree_name", "")).strip()

    def _do():
        if not tree_name:
            return {"status": "error", "error": "Missing required input: tree_name"}
        tree = bpy.data.node_groups.get(tree_name)
        if tree is None:
            available = [ng.name for ng in bpy.data.node_groups if ng.bl_idname == "GeometryNodeTree"]
            return {
                "status": "error",
                "error": f"Node group '{tree_name}' not found",
                "available_trees": available,
            }
        nodes = []
        for n in tree.nodes:
            nodes.append({
                "name": n.name,
                "bl_idname": n.bl_idname,
                "label": n.label or "",
                "parent_frame": n.parent.name if getattr(n, "parent", None) else None,
            })
        return {
            "status": "success",
            "result": {
                "tree_name": tree_name,
                "node_count": len(nodes),
                "nodes": nodes,
            },
        }

    return execute_in_main_thread(_do)


def handle_find_tree_nodes(cmd: dict) -> dict:
    """Busca nós em uma árvore GN por fragmento de name, label ou bl_idname.

    Lê diretamente via bpy — sem snapshot, sem cap de nós.

    Filtros (todos opcionais, combináveis, case-insensitive):
      - name_contains   : str  — fragmento do nome interno do nó
      - label_contains  : str  — fragmento do label visível no editor
      - bl_idname       : str  — tipo do nó (fragmento OU exato, dep. de bl_idname_exact)
      - bl_idname_exact : bool — se True, match exato de bl_idname (default False)

    Sem filtros: retorna TODOS os nós da árvore (full listing, equivalente a
    list_tree_nodes). O campo ``is_full_listing`` será True nesse caso.

    Retorno (status: "success"):
      {
        "tree_name": str,
        "query": { "name_contains": str, "label_contains": str,
                   "bl_idname": str, "bl_idname_exact": bool },
        "is_full_listing": bool,   # True quando nenhum filtro foi informado
        "match_count": int,
        "matches": [
          { "name": str, "label": str, "bl_idname": str, "parent_frame": str | null }
        ]
      }
    """
    tree_name = str(cmd.get("tree_name", "")).strip()
    name_contains = str(cmd.get("name_contains") or "").strip().lower()
    label_contains = str(cmd.get("label_contains") or "").strip().lower()
    bl_idname_filter = str(cmd.get("bl_idname") or "").strip()
    bl_idname_exact = bool(cmd.get("bl_idname_exact", False))

    query = {
        "name_contains": name_contains,
        "label_contains": label_contains,
        "bl_idname": bl_idname_filter,
        "bl_idname_exact": bl_idname_exact,
    }
    is_full_listing = not any([name_contains, label_contains, bl_idname_filter])

    def _do():
        if not tree_name:
            return {"status": "error", "error": "Missing required input: tree_name"}
        tree = bpy.data.node_groups.get(tree_name)
        if tree is None:
            available = [ng.name for ng in bpy.data.node_groups if ng.bl_idname == "GeometryNodeTree"]
            return {
                "status": "error",
                "error": f"Node group '{tree_name}' not found",
                "available_trees": available,
            }

        matches = []
        for n in tree.nodes:
            node_name_lc = n.name.lower()
            node_label_lc = (n.label or "").lower()
            node_idname = n.bl_idname  # preserve original case for output

            if name_contains and name_contains not in node_name_lc:
                continue
            if label_contains and label_contains not in node_label_lc:
                continue
            if bl_idname_filter:
                if bl_idname_exact:
                    if node_idname != bl_idname_filter:
                        continue
                else:
                    if bl_idname_filter.lower() not in node_idname.lower():
                        continue

            matches.append({
                "name": n.name,
                "label": n.label or "",
                "bl_idname": node_idname,
                "parent_frame": n.parent.name if getattr(n, "parent", None) else None,
            })

        return {
            "status": "success",
            "result": {
                "tree_name": tree_name,
                "query": query,
                "is_full_listing": is_full_listing,
                "match_count": len(matches),
                "matches": matches,
            },
        }

    return execute_in_main_thread(_do)



# ---------------------------------------------------------------------------
# Structured apply handlers
# ---------------------------------------------------------------------------


def handle_apply_renames(cmd: dict) -> dict:
    renames = cmd.get("renames", [])

    def _do():
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

    return execute_in_main_thread(_do)


def handle_apply_collections(cmd: dict) -> dict:
    moves = cmd.get("moves", [])

    def _do():
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

    return execute_in_main_thread(_do)


def _execute_gn_operation(tree, op: str, params: dict) -> dict:
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
            writable = [p.identifier for p in node.bl_rna.properties if not p.is_readonly]
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
    raise ValueError(f"Socket '{name_or_index}' not found. Available: {[s.name for s in sockets]}")


# ---------------------------------------------------------------------------
# Generic code execution + undo
# ---------------------------------------------------------------------------


def handle_execute_code(cmd: dict) -> dict:
    code = cmd.get("code", "")

    def _do():
        buf = io.StringIO()
        try:
            # Use a shared namespace so helper functions defined by the script
            # can resolve top-level variables created earlier in the same exec.
            namespace = {"bpy": bpy, "__builtins__": __builtins__}
            with redirect_stdout(buf):
                exec(code, namespace, namespace)
            return {"status": "success", "stdout": buf.getvalue()}
        except Exception as exc:
            return {
                "status": "error",
                "error": str(exc),
                "stdout": buf.getvalue(),
                "traceback": traceback.format_exc(),
            }

    return execute_in_main_thread(_do)


def handle_query_node_types(cmd: dict) -> dict:
    """Introspect available Geometry Nodes node types in the running Blender version.

    Modes:
    - search="matrix"        → list all GN node type identifiers containing that word
    - node_type="FunctionNodeAlignEulerToVector"
                             → return inputs, outputs, and editable properties for that type
    - api_type="NodeTreeInterface"
                             → inspect any bpy.types.* object: lists its methods,
                               properties, and function signatures. Use this BEFORE
                               execute_code when unsure about Blender API (e.g. how to
                               call interface.new_socket() in this exact Blender version).
    """
    search = (cmd.get("search") or "").strip().lower()
    node_type = (cmd.get("node_type") or "").strip()
    api_type = (cmd.get("api_type") or "").strip()

    def _do():
        import bpy  # noqa: F811

        if api_type:
            # --- API inspection mode: introspect any bpy.types.* RNA type ---
            rna_type = getattr(bpy.types, api_type, None)
            if rna_type is None:
                # Try a case-insensitive search and return candidates
                candidates = [n for n in dir(bpy.types) if api_type.lower() in n.lower()][:20]
                return {
                    "status": "not_found",
                    "api_type": api_type,
                    "candidates": candidates,
                    "hint": f"bpy.types.{api_type} not found. Did you mean one of these?",
                }
            import inspect
            methods = []
            properties = []
            for attr in sorted(dir(rna_type)):
                if attr.startswith("__"):
                    continue
                try:
                    obj = getattr(rna_type, attr)
                except Exception:
                    continue
                if callable(obj):
                    try:
                        sig = str(inspect.signature(obj))
                    except (ValueError, TypeError):
                        sig = "(...)"
                    methods.append({"name": attr, "signature": sig[:120]})
                else:
                    properties.append(attr)
            # Also try to get RNA properties if available
            rna_props = []
            try:
                for p in rna_type.bl_rna.properties:
                    rna_props.append({
                        "identifier": p.identifier,
                        "type": p.type,
                        "description": p.description[:80] if p.description else "",
                    })
            except Exception:
                pass
            return {
                "status": "ok",
                "api_type": f"bpy.types.{api_type}",
                "methods": methods[:40],
                "properties": properties[:40],
                "rna_properties": rna_props[:30],
            }

        if node_type:
            # --- Detail mode: inspect one specific node type ---
            tmp = bpy.data.node_groups.new("__introspect_tmp__", "GeometryNodeTree")
            try:
                node = tmp.nodes.new(node_type)
                inputs = [
                    {"name": s.name, "identifier": s.identifier, "type": s.type}
                    for s in node.inputs
                ]
                outputs = [
                    {"name": s.name, "identifier": s.identifier, "type": s.type}
                    for s in node.outputs
                ]
                props = []
                for p in node.bl_rna.properties:
                    if p.identifier.startswith("_") or p.identifier in {
                        "rna_type", "name", "label", "type", "location",
                        "width", "height", "color", "use_custom_color",
                        "select", "hide", "mute",
                    }:
                        continue
                    props.append(p.identifier)
                    if len(props) >= 20:
                        break
                return {
                    "status": "ok",
                    "node_type": node_type,
                    "inputs": inputs,
                    "outputs": outputs,
                    "properties": props,
                }
            except Exception as exc:
                return {"status": "error", "node_type": node_type, "error": str(exc)}
            finally:
                bpy.data.node_groups.remove(tmp)

        elif search:
            # --- Search mode: list matching GN node type identifiers ---
            matches = []
            for name in sorted(dir(bpy.types)):
                if not (
                    name.startswith("GeometryNode")
                    or name.startswith("FunctionNode")
                    or name.startswith("ShaderNode")
                ):
                    continue
                if search and search not in name.lower():
                    continue
                matches.append(name)
            return {"status": "ok", "search": search, "matches": matches[:60]}

        return {
            "status": "error",
            "error": "Provide 'search' (keyword), 'node_type' (exact type name), or 'api_type' (bpy.types name to inspect).",
        }

    return execute_in_main_thread(_do)


# ---------------------------------------------------------------------------
# Script drafting handlers (staged script drafting mode)
# ---------------------------------------------------------------------------

_DRAFT_REVISION_RE = re.compile(r"^(?P<base>.+)__rev_(?P<version>\d{6})$")
_DRAFT_MIN_LINES = 8
_DRAFT_MIN_CHARS = 300
def _is_placeholder_draft(code: str, description: str = "") -> bool:
    text = f"{description}\n{code}".lower()
    return (
        "aguardando" in text
        or "sessao de draft iniciada" in text
        or "sessÃ£o de draft iniciada" in text
    )


def _iter_text_blocks():
    try:
        return list(bpy.data.texts)
    except Exception:
        return []


def _draft_revision_blocks(block_name: str) -> list[Any]:
    blocks: list[Any] = []
    prefix = f"{block_name}__rev_"
    for text in _iter_text_blocks():
        name = str(getattr(text, "name", "") or "")
        if not name.startswith(prefix):
            continue
        if str(text.get("_draft_base_block_name", "") or block_name) != block_name:
            continue
        blocks.append(text)
    return blocks


def _draft_block_version(text_block: Any) -> int:
    try:
        version = int(text_block.get("_draft_version", 0) or 0)
    except Exception:
        version = 0
    if version > 0:
        return version
    match = _DRAFT_REVISION_RE.match(str(getattr(text_block, "name", "") or ""))
    if match:
        try:
            return int(match.group("version"))
        except Exception:
            return 0
    return 0


def _infer_draft_revision_validity(code: str, description: str = "") -> str:
    text = str(code or "")
    if _is_placeholder_draft(text, description):
        return "quarantined"
    stripped = text.strip()
    if not stripped:
        return "broken"
    try:
        compile(stripped, "<script_draft_revision>", "exec")
    except SyntaxError:
        return "broken"
    line_count = len(stripped.splitlines())
    char_count = len(stripped)
    if line_count < _DRAFT_MIN_LINES or char_count < _DRAFT_MIN_CHARS:
        return "partial"
    return "valid"


def _draft_revision_reject_reason(code: str, description: str = "") -> str:
    text = str(code or "")
    if _is_placeholder_draft(text, description):
        return "placeholder_draft"
    stripped = text.strip()
    if not stripped:
        return "empty_script"
    try:
        compile(stripped, "<script_draft_revision>", "exec")
    except SyntaxError as exc:
        return f"syntax_error:{exc.msg}"
    line_count = len(stripped.splitlines())
    char_count = len(stripped)
    if line_count < _DRAFT_MIN_LINES:
        return f"too_few_lines:{line_count}<{_DRAFT_MIN_LINES}"
    if char_count < _DRAFT_MIN_CHARS:
        return f"too_few_chars:{char_count}<{_DRAFT_MIN_CHARS}"
    return ""


def _attribute_chain(node: ast.AST) -> list[str]:
    parts: list[str] = []
    current: ast.AST | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return list(reversed(parts))


def _is_nodes_expr(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "nodes"
    if isinstance(node, ast.Attribute):
        return node.attr == "nodes" or _is_nodes_expr(node.value)
    return False


def _has_geometry_nodes_operations(code: str) -> bool:
    try:
        parsed = ast.parse(str(code or ""))
    except SyntaxError:
        return False

    class GeometryNodesOperationVisitor(ast.NodeVisitor):
        found = False

        def visit_Attribute(self, node: ast.Attribute) -> Any:
            chain = _attribute_chain(node)
            if chain[-3:] == ["bpy", "data", "node_groups"]:
                self.found = True
                return
            if node.attr in {"nodes", "links", "interface"}:
                self.found = True
                return
            self.generic_visit(node)

        def visit_Subscript(self, node: ast.Subscript) -> Any:
            if _is_nodes_expr(node.value):
                self.found = True
                return
            if isinstance(node.value, ast.Name) and node.value.id == "modifiers":
                self.found = True
                return
            if isinstance(node.value, ast.Attribute) and node.value.attr == "modifiers":
                self.found = True
                return
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> Any:
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {"get", "new"} and _is_nodes_expr(func.value):
                self.found = True
                return
            self.generic_visit(node)

    visitor = GeometryNodesOperationVisitor()
    visitor.visit(parsed)
    return visitor.found


def _extract_referenced_node_names(code: str) -> list[str]:
    try:
        parsed = ast.parse(str(code or ""))
    except SyntaxError:
        return []

    names: list[str] = []

    def add_name(value: str) -> None:
        name = str(value or "").strip()
        if name and name not in names:
            names.append(name)

    class NodeReferenceVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.bindings: dict[str, list[str]] = {}

        def _resolve_strings(self, node: ast.AST) -> list[str]:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return [node.value]
            if isinstance(node, ast.Name):
                return list(self.bindings.get(node.id, []))
            if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                values: list[str] = []
                for item in node.elts:
                    values.extend(self._resolve_strings(item))
                return values
            return []

        @staticmethod
        def _is_nodes_expr(node: ast.AST) -> bool:
            return _is_nodes_expr(node)

        def _bind_assignment(self, target: ast.AST, value: ast.AST) -> None:
            if isinstance(target, ast.Name):
                resolved = self._resolve_strings(value)
                if resolved:
                    self.bindings[target.id] = resolved

        def visit_Assign(self, node: ast.Assign) -> Any:
            for target in node.targets:
                self._bind_assignment(target, node.value)
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
            if node.value is not None:
                self._bind_assignment(node.target, node.value)
            self.generic_visit(node)

        def visit_For(self, node: ast.For) -> Any:
            previous: list[str] | None = None
            target_name = node.target.id if isinstance(node.target, ast.Name) else ""
            if target_name:
                previous = self.bindings.get(target_name)
                values = self._resolve_strings(node.iter)
                if values:
                    self.bindings[target_name] = values
            for item in node.body:
                self.visit(item)
            if target_name:
                if previous is None:
                    self.bindings.pop(target_name, None)
                else:
                    self.bindings[target_name] = previous
            for item in node.orelse:
                self.visit(item)

        def visit_Call(self, node: ast.Call) -> Any:
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and self._is_nodes_expr(func.value)
                and node.args
            ):
                for value in self._resolve_strings(node.args[0]):
                    add_name(value)
            self.generic_visit(node)

        def visit_Subscript(self, node: ast.Subscript) -> Any:
            if self._is_nodes_expr(node.value):
                for value in self._resolve_strings(node.slice):
                    add_name(value)
            self.generic_visit(node)

    NodeReferenceVisitor().visit(parsed)
    return names


def _semantic_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def _semantic_compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _semantic_text(value))


def _coerce_str_list(value: Any, *, limit: int = 12) -> list[str]:
    raw_items = value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                raw_items = json.loads(stripped)
            except Exception:
                raw_items = [value]
        elif stripped:
            raw_items = [value]
        else:
            raw_items = []
    if not isinstance(raw_items, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item or "").strip()
        key = _semantic_compact(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _text_block_str_list(text_block: Any, key: str, *, limit: int = 12) -> list[str]:
    if text_block is None:
        return []
    try:
        value = text_block.get(key, [])
    except Exception:
        value = []
    return _coerce_str_list(value, limit=limit)


def _text_block_json_dict(text_block: Any, key: str) -> dict[str, Any]:
    if text_block is None:
        return {}
    try:
        value = text_block.get(key, {})
    except Exception:
        value = {}
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _semantic_term_present(code: str, term: str) -> bool:
    text = _semantic_text(code)
    compact_text = _semantic_compact(code)
    term_text = _semantic_text(term).strip()
    term_compact = _semantic_compact(term)
    if not term_text or not term_compact:
        return False
    variants = {
        term_text,
        term_text.replace(" ", "_"),
        term_text.replace(" ", "-"),
        term_compact,
    }
    return any(
        variant and (variant in text or _semantic_compact(variant) in compact_text)
        for variant in variants
    )


def _matched_semantic_terms(code: str, expected_terms: list[str], *, limit: int = 8) -> list[str]:
    matches: list[str] = []
    seen: set[str] = set()
    for term in expected_terms:
        text = str(term or "").strip()
        key = _semantic_compact(text)
        if not text or not key or key in seen:
            continue
        if _semantic_term_present(code, text):
            seen.add(key)
            matches.append(text)
            if len(matches) >= limit:
                break
    return matches


def _draft_semantic_regression_reason(
    candidate_code: str,
    *,
    previous_code: str = "",
    previous_tree_name: str = "",
    candidate_tree_name: str = "",
    allow_tree_change: bool = False,
    allow_capability_regression: bool = False,
    expected_parameter_refs: list[str] | None = None,
    expected_focus_regions: list[str] | None = None,
) -> tuple[str, dict[str, list[str]]]:
    details = {
        "previous_live_node_refs": [],
        "candidate_live_node_refs": [],
        "previous_parameter_refs": [],
        "candidate_parameter_refs": [],
        "previous_focus_regions": [],
        "candidate_focus_regions": [],
    }
    previous = str(previous_code or "").strip()
    candidate = str(candidate_code or "").strip()
    if not previous or not candidate:
        return "", details

    prev_tree = str(previous_tree_name or "").strip()
    next_tree = str(candidate_tree_name or "").strip()
    if prev_tree and next_tree and prev_tree != next_tree and not allow_tree_change:
        return f"target_tree_changed:{prev_tree}->{next_tree}", details

    prev_live_refs = _extract_referenced_node_names(previous)
    details["previous_live_node_refs"] = prev_live_refs[:8]
    if prev_live_refs and not allow_capability_regression:
        next_live_refs = _extract_referenced_node_names(candidate)
        details["candidate_live_node_refs"] = next_live_refs[:8]
        if not next_live_refs:
            return "regression_lost_live_node_refs", details

        prev_ref_set = set(prev_live_refs)
        next_ref_set = set(next_live_refs)
        if not prev_ref_set.intersection(next_ref_set):
            return "regression_replaced_live_node_refs:" + ", ".join(prev_live_refs[:6]), details

    parameter_refs = _coerce_str_list(expected_parameter_refs or [], limit=12)
    if parameter_refs and not allow_capability_regression:
        prev_parameter_refs = _matched_semantic_terms(previous, parameter_refs)
        details["previous_parameter_refs"] = prev_parameter_refs[:8]
        if prev_parameter_refs:
            next_parameter_refs = _matched_semantic_terms(candidate, parameter_refs)
            details["candidate_parameter_refs"] = next_parameter_refs[:8]
            if not next_parameter_refs:
                return "regression_lost_expected_parameters:" + ", ".join(prev_parameter_refs[:6]), details
            if not set(prev_parameter_refs).intersection(set(next_parameter_refs)):
                return "regression_replaced_expected_parameters:" + ", ".join(prev_parameter_refs[:6]), details

    focus_regions = [
        region for region in _coerce_str_list(expected_focus_regions or [], limit=12)
        if not _is_generic_focus_region(region)
    ]
    if focus_regions and not allow_capability_regression:
        prev_focus_regions = _matched_semantic_terms(previous, focus_regions)
        details["previous_focus_regions"] = prev_focus_regions[:8]
        if prev_focus_regions:
            next_focus_regions = _matched_semantic_terms(candidate, focus_regions)
            details["candidate_focus_regions"] = next_focus_regions[:8]
            if not next_focus_regions:
                return "regression_lost_focus_regions:" + ", ".join(prev_focus_regions[:6]), details
            if not set(prev_focus_regions).intersection(set(next_focus_regions)):
                return "regression_replaced_focus_regions:" + ", ".join(prev_focus_regions[:6]), details

    prev_len = len(previous)
    next_len = len(candidate)
    if (
        prev_len >= 900
        and next_len < max(_DRAFT_MIN_CHARS, int(prev_len * 0.55))
        and not allow_capability_regression
    ):
        return f"regression_candidate_too_small_vs_existing:{next_len}<{int(prev_len * 0.55)}", details

    return "", details


def _is_generic_focus_region(region: str) -> bool:
    text = str(region or "").strip().lower()
    if not text:
        return True
    if text == "frame" or re.fullmatch(r"frame(?:\.\d+)?", text):
        return True
    if text in {
        "unknown_structural_region",
        "geometry_join_or_assembly_region",
    }:
        return True
    return False


def _draft_domain_reject_reason(code: str, *, tree_name: str = "") -> str:
    stripped = str(code or "").strip()
    if not stripped:
        return ""

    if tree_name:
        tree = bpy.data.node_groups.get(tree_name)
        if tree is None:
            return f"target_tree_missing:{tree_name}"

        if not _has_geometry_nodes_operations(stripped):
            return "no_geometry_nodes_operations_detected"

        referenced_nodes = _extract_referenced_node_names(stripped)
        if referenced_nodes:
            try:
                live_nodes = {node.name for node in tree.nodes}
            except Exception:
                live_nodes = set()
            missing = [name for name in referenced_nodes if name not in live_nodes]
            if missing:
                return f"missing_live_nodes:{', '.join(missing[:6])}"

    return ""


def _draft_revision_validity(text_block: Any) -> str:
    try:
        explicit = str(text_block.get("_draft_revision_validity", "") or "").strip().lower()
    except Exception:
        explicit = ""
    if explicit in {"valid", "partial", "broken", "quarantined", "superseded"}:
        return explicit
    try:
        description = str(text_block.get("_draft_description", "") or "")
    except Exception:
        description = ""
    return _infer_draft_revision_validity(text_block.as_string(), description)


def _latest_draft_block(block_name: str) -> Any | None:
    main = bpy.data.texts.get(block_name)
    if main is not None:
        return main
    candidates = _draft_revision_blocks(block_name)
    if not candidates:
        return None
    return max(candidates, key=_draft_block_version)


def _best_draft_reasoning_block(block_name: str) -> tuple[Any | None, Any | None]:
    main = bpy.data.texts.get(block_name)
    if main is not None:
        return main, main
    candidates = _draft_revision_blocks(block_name)
    if not candidates:
        return None, None
    latest = max(candidates, key=_draft_block_version)
    usable = [
        block for block in candidates
        if _draft_revision_validity(block) in {"valid", "partial"}
    ]
    if not usable:
        return latest, latest
    valid = [block for block in usable if _draft_revision_validity(block) == "valid"]
    pool = valid or usable
    best = max(pool, key=_draft_block_version)
    return best, latest


def _draft_payload_from_block(text_block: Any, *, source: str = "text_block") -> dict:
    content = text_block.as_string()
    validity = _draft_revision_validity(text_block)
    return {
        "block_name": text_block.name,
        "content": content,
        "line_count": len(text_block.lines),
        "char_count": len(content),
        "version": _draft_block_version(text_block),
        "description": str(text_block.get("_draft_description", "") or ""),
        "tree_name": str(text_block.get("_draft_tree_name", "") or ""),
        "revision_created_at": str(text_block.get("_draft_revision_created_at", "") or ""),
        "revision_parent": int(text_block.get("_draft_revision_parent", 0) or 0),
        "revision_kind": str(text_block.get("_draft_revision_kind", "") or ""),
        "revision_changed_from_previous": str(text_block.get("_draft_revision_changed_from_previous", "") or ""),
        "current_revision_validity": validity,
        "revision_validity": validity,
        "last_valid_draft_revision": int(text_block.get("_draft_last_valid_revision", 0) or 0),
        "last_executed_revision": int(text_block.get("_draft_last_executed_revision", 0) or 0),
        "last_failed_revision": int(text_block.get("_draft_last_failed_revision", 0) or 0),
        "live_node_refs": _extract_referenced_node_names(content)[:8],
        "expected_parameter_refs": _text_block_str_list(text_block, "_draft_expected_parameter_refs", limit=12),
        "expected_focus_regions": _text_block_str_list(text_block, "_draft_expected_focus_regions", limit=12),
        "edit_mode": str(text_block.get("_draft_edit_mode", "") or ""),
        "goal_mode": str(text_block.get("_draft_goal_mode", "") or ""),
        "goal_guidance": _text_block_json_dict(text_block, "_draft_goal_guidance"),
        "draft_archive_path": str(text_block.get("_draft_archive_path", "") or ""),
        "source": source,
    }


def _safe_draft_filename_part(value: str, *, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", ascii_text).strip("._")
    return safe[:80] or fallback


def _archive_script_draft(
    *,
    code: str,
    block_name: str,
    version: int,
    created_at: str,
    description: str,
    tree_name: str,
    session_id: str,
    project_root: str,
) -> tuple[str, str]:
    """Persist a full draft revision as a .py file for postmortems and reuse."""
    safe_session = _safe_draft_filename_part(session_id, fallback="unsessioned")
    safe_block = _safe_draft_filename_part(block_name, fallback="GN_Agent_Draft")
    try:
        root = Path(project_root).expanduser().resolve() if project_root else None
    except Exception:
        root = None
    if root is None:
        try:
            from .project_paths import resolve_project_root

            root = resolve_project_root()
        except Exception as exc:
            return "", f"project_root_unavailable:{exc}"

    archive_dir = root / "runtime" / "draft_history" / safe_session
    filename = f"r{int(version):06d}_{safe_block}.py"
    target = archive_dir / filename
    tmp = archive_dir / f".{filename}.tmp"
    header = (
        "# GN Agent draft archive\n"
        f"# session_id: {session_id or 'unsessioned'}\n"
        f"# block_name: {block_name}\n"
        f"# revision: {int(version)}\n"
        f"# created_at: {created_at}\n"
        f"# tree_name: {tree_name}\n"
        f"# description: {description[:300]}\n\n"
    )
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(header)
            handle.write(code)
            if not code.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        return str(target), ""
    except Exception as exc:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return "", str(exc)


def handle_write_script_draft(cmd: dict) -> dict:
    """Write a Python/bpy script to a Blender Text Editor block.

    The script is NOT executed. It is placed in bpy.data.texts so the user
    can review, modify, and run it manually from the Scripting workspace.

    Parameters:
        block_name : str — name of the text block (default "GN_Agent_Draft")
        code       : str — the complete Python script to write
        description: str — what this script does (for metadata)
        tree_name  : str — optional target GN tree name
    """
    block_name = str(cmd.get("block_name") or "GN_Agent_Draft").strip()
    code = str(cmd.get("code") or "")
    description = str(cmd.get("description") or "").strip()
    tree_name = str(cmd.get("tree_name") or "").strip()
    allow_tree_change = bool(cmd.get("allow_tree_change", False))
    allow_capability_regression = bool(cmd.get("allow_capability_regression", False))
    edit_mode = str(cmd.get("edit_mode") or "").strip()
    goal_mode = str(cmd.get("goal_mode") or "").strip()
    goal_guidance = cmd.get("goal_guidance", {}) if isinstance(cmd.get("goal_guidance"), dict) else {}
    expected_parameter_refs = _coerce_str_list(cmd.get("expected_parameter_refs", []), limit=12)
    expected_focus_regions = _coerce_str_list(cmd.get("expected_focus_regions", []), limit=12)
    session_id = str(cmd.get("session_id") or "").strip()
    project_root = str(cmd.get("project_root") or "").strip()

    def _do():
        if not code.strip():
            return {"status": "error", "error": "Empty script — nothing to write."}

        existing_latest = _latest_draft_block(block_name)
        if (
            existing_latest is not None
            and _is_placeholder_draft(code, description)
            and not _is_placeholder_draft(
                existing_latest.as_string(),
                str(existing_latest.get("_draft_description", "") or ""),
            )
        ):
            payload = _draft_payload_from_block(existing_latest, source="revision_backup")
            payload["block_name"] = block_name
            payload["skipped_placeholder_write"] = True
            payload["edit_mode"] = edit_mode
            payload["goal_mode"] = goal_mode
            payload["goal_guidance"] = goal_guidance
            return {"status": "success", "result": payload}

        existing_version = _draft_block_version(existing_latest) if existing_latest is not None else 0
        next_version = existing_version + 1
        created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        inferred_validity = _infer_draft_revision_validity(code, description)
        requested_validity = str(cmd.get("revision_validity") or "").strip().lower()
        validity_rank = {"valid": 0, "partial": 1, "broken": 2, "quarantined": 3}
        if requested_validity in validity_rank and validity_rank[requested_validity] > validity_rank[inferred_validity]:
            revision_validity = requested_validity
        else:
            revision_validity = inferred_validity
        if revision_validity != "valid":
            reject_reason = _draft_revision_reject_reason(code, description) or revision_validity
            return {
                "status": "blocked",
                "error": (
                    "Draft write blocked: the candidate script is not a complete valid revision "
                    f"({reject_reason}). write_script_draft must receive the full corrected script."
                ),
                "result": {
                    "block_name": block_name,
                    "current_revision": existing_version,
                    "candidate_char_count": len(code),
                    "candidate_line_count": len(code.strip().splitlines()) if code.strip() else 0,
                    "candidate_revision_validity": revision_validity,
                    "reject_reason": reject_reason,
                    "edit_mode": edit_mode,
                    "goal_mode": goal_mode,
                    "goal_guidance": goal_guidance,
                },
            }
        domain_reject_reason = _draft_domain_reject_reason(code, tree_name=tree_name)
        if domain_reject_reason:
            return {
                "status": "blocked",
                "error": (
                    "Draft write blocked: the candidate script did not pass live Geometry Nodes validation "
                    f"({domain_reject_reason})."
                ),
                "result": {
                    "block_name": block_name,
                    "current_revision": existing_version,
                    "candidate_char_count": len(code),
                    "candidate_line_count": len(code.strip().splitlines()) if code.strip() else 0,
                    "candidate_revision_validity": revision_validity,
                    "reject_reason": domain_reject_reason,
                    "tree_name": tree_name,
                    "edit_mode": edit_mode,
                    "goal_mode": goal_mode,
                    "goal_guidance": goal_guidance,
                },
            }
        previous_tree_name = ""
        previous_code = ""
        previous_validity = ""
        previous_parameter_refs: list[str] = []
        previous_focus_regions: list[str] = []
        if existing_latest is not None:
            previous_code = str(existing_latest.as_string() or "")
            previous_tree_name = str(existing_latest.get("_draft_tree_name", "") or "")
            previous_validity = _draft_revision_validity(existing_latest)
            previous_parameter_refs = _text_block_str_list(existing_latest, "_draft_expected_parameter_refs", limit=12)
            previous_focus_regions = _text_block_str_list(existing_latest, "_draft_expected_focus_regions", limit=12)
        semantic_reject_reason = ""
        semantic_details: dict[str, list[str]] = {
            "previous_live_node_refs": [],
            "candidate_live_node_refs": [],
            "previous_parameter_refs": [],
            "candidate_parameter_refs": [],
            "previous_focus_regions": [],
            "candidate_focus_regions": [],
        }
        if previous_validity == "valid":
            semantic_reject_reason, semantic_details = _draft_semantic_regression_reason(
                code,
                previous_code=previous_code,
                previous_tree_name=previous_tree_name,
                candidate_tree_name=tree_name or previous_tree_name,
                allow_tree_change=allow_tree_change,
                allow_capability_regression=allow_capability_regression,
                expected_parameter_refs=expected_parameter_refs or previous_parameter_refs,
                expected_focus_regions=expected_focus_regions or previous_focus_regions,
            )
        if semantic_reject_reason:
            return {
                "status": "blocked",
                "error": (
                    "Draft write blocked: the candidate script regressed capabilities that the current living draft "
                    f"already had ({semantic_reject_reason})."
                ),
                "result": {
                    "block_name": block_name,
                    "current_revision": existing_version,
                    "candidate_char_count": len(code),
                    "candidate_line_count": len(code.strip().splitlines()) if code.strip() else 0,
                    "candidate_revision_validity": revision_validity,
                    "reject_reason": semantic_reject_reason,
                    "tree_name": tree_name or previous_tree_name,
                    "previous_tree_name": previous_tree_name,
                    "previous_live_node_refs": semantic_details.get("previous_live_node_refs", []),
                    "candidate_live_node_refs": semantic_details.get("candidate_live_node_refs", []),
                    "previous_parameter_refs": semantic_details.get("previous_parameter_refs", []),
                    "candidate_parameter_refs": semantic_details.get("candidate_parameter_refs", []),
                    "previous_focus_regions": semantic_details.get("previous_focus_regions", []),
                    "candidate_focus_regions": semantic_details.get("candidate_focus_regions", []),
                    "edit_mode": edit_mode,
                    "goal_mode": goal_mode,
                    "goal_guidance": goal_guidance,
                },
            }
        previous_best, _previous_latest = _best_draft_reasoning_block(block_name)
        previous_valid_revision = 0
        if previous_best is not None and _draft_revision_validity(previous_best) == "valid":
            previous_valid_revision = _draft_block_version(previous_best)
        last_valid_revision = next_version if revision_validity == "valid" else previous_valid_revision

        # Create or reuse the text block.
        text_block = bpy.data.texts.get(block_name)
        created = text_block is None
        if text_block is None:
            text_block = bpy.data.texts.new(block_name)
        else:
            text_block.clear()

        text_block.write(code)

        # Store metadata as custom properties on the text block.
        text_block["_draft_description"] = description[:500]
        text_block["_draft_tree_name"] = tree_name
        text_block["_draft_version"] = next_version
        text_block["_draft_revision_created_at"] = created_at
        text_block["_draft_revision_parent"] = existing_version
        text_block["_draft_revision_kind"] = str(cmd.get("revision_kind") or ("create" if existing_version <= 0 else "refine"))
        text_block["_draft_revision_changed_from_previous"] = str(cmd.get("revision_changed_from_previous") or "")[:500]
        text_block["_draft_revision_validity"] = revision_validity
        text_block["_draft_last_valid_revision"] = last_valid_revision
        text_block["_draft_last_executed_revision"] = int(cmd.get("last_executed_revision", 0) or 0)
        text_block["_draft_last_failed_revision"] = int(cmd.get("last_failed_revision", 0) or 0)
        text_block["_draft_expected_parameter_refs"] = json.dumps(expected_parameter_refs, ensure_ascii=False)
        text_block["_draft_expected_focus_regions"] = json.dumps(expected_focus_regions, ensure_ascii=False)
        text_block["_draft_edit_mode"] = edit_mode
        text_block["_draft_goal_mode"] = goal_mode
        text_block["_draft_goal_guidance"] = json.dumps(goal_guidance, ensure_ascii=False)
        draft_archive_path = ""
        draft_archive_error = ""
        if session_id or project_root:
            draft_archive_path, draft_archive_error = _archive_script_draft(
                code=code,
                block_name=text_block.name,
                version=next_version,
                created_at=created_at,
                description=description,
                tree_name=tree_name,
                session_id=session_id,
                project_root=project_root,
            )
        if draft_archive_path:
            text_block["_draft_archive_path"] = draft_archive_path

        return {
            "status": "success",
            "result": {
                "block_name": text_block.name,
                "created": created,
                "line_count": len(text_block.lines),
                "char_count": len(code),
                "version": next_version,
                "description": description[:200],
                "tree_name": tree_name,
                "revision_created_at": created_at,
                "revision_parent": existing_version,
                "revision_kind": str(text_block.get("_draft_revision_kind", "") or ""),
                "revision_changed_from_previous": str(text_block.get("_draft_revision_changed_from_previous", "") or ""),
                "current_revision_validity": revision_validity,
                "revision_validity": revision_validity,
                "last_valid_draft_revision": last_valid_revision,
                "last_executed_revision": int(cmd.get("last_executed_revision", 0) or 0),
                "last_failed_revision": int(cmd.get("last_failed_revision", 0) or 0),
                "expected_parameter_refs": expected_parameter_refs,
                "expected_focus_regions": expected_focus_regions,
                "edit_mode": edit_mode,
                "goal_mode": goal_mode,
                "goal_guidance": goal_guidance,
                "draft_archive_path": draft_archive_path,
                "draft_archive_error": draft_archive_error,
            },
        }

    return execute_in_main_thread(_do)


def handle_read_script_draft(cmd: dict) -> dict:
    """Read the current content of a Blender Text Editor block.

    Parameters:
        block_name : str — name of the text block (default "GN_Agent_Draft")

    Returns the full text content, line count, and metadata.
    """
    block_name = str(cmd.get("block_name") or "GN_Agent_Draft").strip()

    def _do():
        requested_block = bpy.data.texts.get(block_name)
        latest_block = _latest_draft_block(block_name)
        text_block = requested_block or latest_block
        if text_block is None:
            available = [t.name for t in bpy.data.texts]
            return {
                "status": "error",
                "error": f"Text block '{block_name}' not found.",
                "available_text_blocks": available,
            }

        source = "text_block" if text_block is requested_block else "legacy_revision_fallback"
        payload = _draft_payload_from_block(text_block, source=source)
        payload["block_name"] = block_name
        if source == "legacy_revision_fallback":
            payload["legacy_block_name"] = text_block.name
            payload["legacy_fallback_used"] = True
        return {
            "status": "success",
            "result": payload,
        }

    return execute_in_main_thread(_do)


HANDLERS = {
    "capture_scene": handle_capture_scene,
    "capture_node_trees": handle_capture_node_trees,
    "capture_full": handle_capture_full,
    "get_node_context": handle_get_node_context,
    "get_selected_nodes_context": handle_get_selected_nodes_context,
    "get_active_frame_context": handle_get_active_frame_context,
    "get_local_subgraph_context": handle_get_local_subgraph_context,
    "apply_renames": handle_apply_renames,
    "apply_collections": handle_apply_collections,
    "apply_gn_edits": handle_apply_gn_edits,
    "execute_code": handle_execute_code,
    "query_node_types": handle_query_node_types,
    "write_script_draft": handle_write_script_draft,
    "read_script_draft": handle_read_script_draft,
}
