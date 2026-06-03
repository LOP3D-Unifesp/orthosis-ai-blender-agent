"""Focal and direct Geometry Nodes read tool handlers."""

from __future__ import annotations

from typing import Any

import bpy

from .. import capture


def execute_in_main_thread(func):
    from .handlers import execute_in_main_thread as _execute_in_main_thread

    return _execute_in_main_thread(func)


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


def _serialize_tree_interface(tree) -> dict[str, list[dict[str, Any]]]:
    interface = {"inputs": [], "outputs": [], "panels": []}
    items_tree = getattr(getattr(tree, "interface", None), "items_tree", [])
    for item in items_tree:
        try:
            item_type = str(getattr(item, "item_type", "") or "")
            if item_type == "PANEL":
                interface["panels"].append({
                    "name": str(getattr(item, "name", "") or ""),
                    "identifier": str(getattr(item, "identifier", "") or ""),
                })
                continue
            in_out = str(getattr(item, "in_out", "") or "")
            if in_out not in {"INPUT", "OUTPUT"}:
                continue
            entry = {
                "name": str(getattr(item, "name", "") or ""),
                "identifier": str(getattr(item, "identifier", "") or ""),
                "socket_type": str(getattr(item, "socket_type", "") or ""),
                "description": str(getattr(item, "description", "") or ""),
            }
            if hasattr(item, "default_value"):
                entry["default_value"] = capture._json_safe_value(getattr(item, "default_value"))
            if hasattr(item, "min_value"):
                entry["min_value"] = capture._json_safe_value(getattr(item, "min_value"))
            if hasattr(item, "max_value"):
                entry["max_value"] = capture._json_safe_value(getattr(item, "max_value"))
            if getattr(item, "parent", None) is not None:
                entry["parent_panel"] = str(getattr(item.parent, "name", "") or "")
            target = "inputs" if in_out == "INPUT" else "outputs"
            interface[target].append(entry)
        except Exception:
            continue
    return interface


def handle_get_tree_inventory(cmd: dict) -> dict:
    """Return a full direct inventory of one Geometry Nodes tree.

    Unlike prompt-oriented structural memory, this intentionally reads all
    nodes and links from the live tree and leaves paging/compaction to the
    caller. It is meant for source/DSL extraction, not for one-shot prompt
    injection.
    """
    tree_name = str(cmd.get("tree_name", "")).strip()
    include_values = bool(cmd.get("include_values", True))
    include_properties = bool(cmd.get("include_properties", True))

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

        node_names = {node.name for node in tree.nodes}
        nodes_payload, links_payload = _serialize_nodes_and_links(
            tree,
            node_names,
            include_values=include_values,
            include_properties=include_properties,
        )
        frames = [node for node in nodes_payload if node.get("type") == "NodeFrame"]
        groups = [
            node for node in nodes_payload
            if str(node.get("type", "")).lower() in {"geometrynodegroup", "nodegroup"}
        ]
        unframed = [
            node for node in nodes_payload
            if not node.get("parent_frame") and node.get("type") != "NodeFrame"
        ]
        return {
            "status": "success",
            "result": {
                "schema_version": "tree_direct_inventory.v1",
                "tree_name": tree_name,
                "node_count": len(nodes_payload),
                "link_count": len(links_payload),
                "frame_count": len(frames),
                "group_count": len(groups),
                "unframed_count": len(unframed),
                "interface": _serialize_tree_interface(tree),
                "nodes": nodes_payload,
                "links": links_payload,
            },
        }

    return execute_in_main_thread(_do)


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

__all__ = [
    "handle_get_tree_inventory",
    "handle_get_node_context",
    "handle_get_selected_nodes_context",
    "handle_get_active_frame_context",
    "handle_get_local_subgraph_context",
    "handle_list_tree_nodes",
    "handle_find_tree_nodes",
]
