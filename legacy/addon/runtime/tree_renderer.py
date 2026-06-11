"""Compact renderers for Geometry Nodes tree context.

The runtime has richer structural memory than the model can safely receive as
raw JSON.  This module turns either a captured tree snapshot or a
tree_structural_memory payload into a compact, human-readable prompt block.
"""

from __future__ import annotations

from typing import Any


def render_compact_tree(snapshot_dict: dict[str, Any], max_chars: int = 6000) -> str:
    """Render a compact tree map suitable for the system prompt.

    Accepts both raw capture payloads (``nodes``/``links``/``interface``) and
    structural-memory payloads (``major_regions``/``marker``/``parameters``).
    The output prioritizes frame membership and exact node names over prose.
    """
    data = snapshot_dict if isinstance(snapshot_dict, dict) else {}
    if not data:
        return ""

    tree_name = _text(data.get("tree_name") or data.get("name"))
    nodes = _list(data.get("nodes"))
    links = _list(data.get("links"))
    interface = data.get("interface") if isinstance(data.get("interface"), dict) else {}
    regions = _list(data.get("major_regions") or data.get("frames"))
    marker = data.get("marker") if isinstance(data.get("marker"), dict) else {}
    params = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}

    node_count = _int(data.get("node_count") or data.get("total_nodes") or len(nodes) or len(_list(marker.get("node_names"))))
    snapshot_truncated = bool(data.get("snapshot_truncated")) or bool(
        (data.get("freshness") if isinstance(data.get("freshness"), dict) else {}).get("snapshot_truncated")
    )
    large_tree = node_count > 200

    lines: list[str] = ["[Tree Snapshot Render]"]
    header = tree_name or "(unknown tree)"
    counts: list[str] = []
    if node_count:
        counts.append(f"{node_count} nodes")
    frame_count = _int(data.get("frame_count") or len([n for n in nodes if _text(n.get("type")) == "NodeFrame"]) or len(regions))
    if frame_count:
        counts.append(f"{frame_count} frames/regions")
    group_count = _int(data.get("group_count"))
    if group_count:
        counts.append(f"{group_count} groups")
    if snapshot_truncated:
        counts.append("snapshot_truncated=True")
    if counts:
        header += " | " + " | ".join(counts)
    lines.append(header)

    bindings = _list(data.get("bindings"))
    if bindings:
        binding_bits: list[str] = []
        for item in bindings[:3]:
            if not isinstance(item, dict):
                continue
            obj = _text(item.get("object_name"))
            mod = _text(item.get("modifier_name"))
            if obj or mod:
                binding_bits.append(f"{obj or '?'} / {mod or '?'}")
        if binding_bits:
            lines.append("Bindings: " + "; ".join(binding_bits))

    region_lines = _render_regions(regions, nodes)
    if region_lines:
        lines.append("Regions:")
        lines.extend(region_lines)

    node_lines = _render_nodes(nodes, marker, regions, large_tree=large_tree)
    if node_lines:
        lines.append("Nodes:")
        lines.extend(node_lines)

    socket_lines = _render_interface(interface)
    if socket_lines:
        lines.append("Group interface sockets:")
        lines.extend(socket_lines)

    param_lines = _render_parameters(params)
    if param_lines:
        lines.append("Modifier parameters:")
        lines.extend(param_lines)

    if not large_tree:
        link_lines = _render_links(links, marker)
        if link_lines:
            lines.append("Key links:")
            lines.extend(link_lines)
    elif _list(marker.get("links")):
        lines.append("Key links: omitted for tree >200 nodes; use focal read for wiring.")

    text = "\n".join(line for line in lines if line is not None)
    return _fit_chars(text, max_chars=max_chars)


def compact_tree_summary_for_baseline(memory: dict[str, Any]) -> dict[str, Any]:
    """Return the persisted subset needed to render tree context next turn."""
    data = memory if isinstance(memory, dict) else {}
    if not data:
        return {}
    marker = data.get("marker") if isinstance(data.get("marker"), dict) else {}
    freshness = data.get("freshness") if isinstance(data.get("freshness"), dict) else {}
    return {
        "schema_version": "tree_prompt_summary.v1",
        "tree_name": _text(data.get("tree_name") or data.get("name")),
        "bound_object": _text(data.get("bound_object")),
        "bound_modifier": _text(data.get("bound_modifier")),
        "bindings": _list(data.get("bindings"))[:3],
        "node_count": _int(data.get("node_count") or data.get("total_nodes")),
        "frame_count": _int(data.get("frame_count")),
        "group_count": _int(data.get("group_count")),
        "phase_dominant": _text(data.get("phase_dominant")),
        "major_regions": _list(data.get("major_regions") or data.get("frames"))[:80],
        "key_joins": [_text(v) for v in _list(data.get("key_joins")) if _text(v)][:16],
        "key_outputs": [_text(v) for v in _list(data.get("key_outputs")) if _text(v)][:16],
        "parameters": data.get("parameters") if isinstance(data.get("parameters"), dict) else {},
        "marker": {
            "tree_hash": _text(marker.get("tree_hash")),
            "node_names": [_text(v) for v in _list(marker.get("node_names")) if _text(v)][:260],
            "links": [_text(v) for v in _list(marker.get("links")) if _text(v)][:80],
        },
        "freshness": {
            "snapshot_truncated": bool(freshness.get("snapshot_truncated", data.get("snapshot_truncated", False))),
        },
        "structural_hash": _text(data.get("structural_hash")),
        "built_at": _text(data.get("built_at")),
    }


def _render_regions(regions: list[Any], nodes: list[Any]) -> list[str]:
    if regions:
        rendered: list[str] = []
        for item in regions[:18]:
            if not isinstance(item, dict):
                continue
            name = _text(item.get("name"))
            label = _text(item.get("label"))
            display = _display_name(name, label)
            keys = [_text(v) for v in _list(item.get("key_nodes")) if _text(v)]
            suffix = f": [{', '.join(keys)}]" if keys else ""
            fn = _text(item.get("probable_function"))
            if fn:
                suffix += f" ({fn})"
            if display:
                rendered.append(f"- {display}{suffix}")
        return rendered

    frames = [n for n in nodes if isinstance(n, dict) and _text(n.get("type")) == "NodeFrame"]
    if not frames:
        return []
    by_parent: dict[str, list[str]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        parent = _text(node.get("parent_frame"))
        name = _text(node.get("name"))
        if parent and name:
            by_parent.setdefault(parent, []).append(name)
    rendered = []
    for frame in frames[:18]:
        name = _text(frame.get("name"))
        label = _text(frame.get("label"))
        keys = by_parent.get(name, [])
        rendered.append(f"- {_display_name(name, label)}: [{', '.join(keys[:14])}]")
    return rendered


def _render_nodes(nodes: list[Any], marker: dict[str, Any], regions: list[Any], *, large_tree: bool) -> list[str]:
    rendered: list[str] = []
    seen: set[str] = set()
    limit = 120 if large_tree else 180
    for node in nodes[:limit]:
        if not isinstance(node, dict):
            continue
        name = _text(node.get("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        label = _text(node.get("label"))
        node_type = _short_type(_text(node.get("type")))
        rendered.append(f"- {_display_name(name, label)}" + (f" ({node_type})" if node_type else ""))

    if not rendered:
        for region in regions:
            if not isinstance(region, dict):
                continue
            for name in [_text(v) for v in _list(region.get("key_nodes")) if _text(v)]:
                if name and name not in seen:
                    seen.add(name)
                    rendered.append(f"- {name}")
                    if len(rendered) >= limit:
                        break
            if len(rendered) >= limit:
                break

    for name in [_text(v) for v in _list(marker.get("node_names")) if _text(v)]:
        if name not in seen:
            seen.add(name)
            rendered.append(f"- {name}")
            if len(rendered) >= limit:
                break
    return rendered


def _render_interface(interface: dict[str, Any]) -> list[str]:
    rendered: list[str] = []
    for direction, label in (("inputs", "IN"), ("outputs", "OUT")):
        sockets = _list(interface.get(direction))
        for sock in sockets[:24]:
            if not isinstance(sock, dict):
                continue
            name = _text(sock.get("name"))
            identifier = _text(sock.get("identifier"))
            sock_type = _short_type(_text(sock.get("type")))
            if name or identifier:
                rendered.append(f"- {label} {name or '?'} id={identifier or '?'}" + (f" type={sock_type}" if sock_type else ""))
    return rendered


def _render_parameters(params: dict[str, Any]) -> list[str]:
    rendered: list[str] = []
    for key in ("measures", "positioning", "other"):
        values = _list(params.get(key))
        for item in values[:8]:
            if not isinstance(item, dict):
                continue
            name = _text(item.get("name") or item.get("identifier"))
            identifier = _text(item.get("identifier"))
            value = item.get("value", item.get("default_value", ""))
            if name or identifier:
                rendered.append(f"- {name or identifier} id={identifier or '?'} value={_text(value)}")
    if rendered:
        return rendered[:24]
    values = _list(params.get("inputs") or params.get("parameters"))
    for item in values[:24]:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name") or item.get("identifier"))
        identifier = _text(item.get("identifier"))
        value = item.get("value", item.get("default_value", ""))
        if name or identifier:
            rendered.append(f"- {name or identifier} id={identifier or '?'} value={_text(value)}")
    return rendered


def _render_links(links: list[Any], marker: dict[str, Any]) -> list[str]:
    rendered: list[str] = []
    for link in links:
        if isinstance(link, dict):
            src = _text(link.get("from_node"))
            out = _text(link.get("from_socket"))
            dst = _text(link.get("to_node"))
            inp = _text(link.get("to_socket"))
            if src and dst:
                rendered.append(f"- {src}:{out or '?'} -> {dst}:{inp or '?'}")
        elif isinstance(link, str) and link.strip():
            rendered.append(f"- {link.strip()}")
        if len(rendered) >= 200:
            rendered.append("[links truncated at 200]")
            return rendered
    for sig in [_text(v) for v in _list(marker.get("links")) if _text(v)]:
        if sig and f"- {sig}" not in rendered:
            rendered.append(f"- {sig}")
        if len(rendered) >= 30:
            break
    return rendered


def _fit_chars(text: str, *, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    marker = "\n[Tree Snapshot Render truncated]"
    return text[: max(0, max_chars - len(marker))].rstrip() + marker


def _display_name(name: str, label: str) -> str:
    if label and label != name:
        return f"{name} label={label}"
    return name


def _short_type(value: str) -> str:
    text = _text(value)
    for prefix in ("GeometryNode", "ShaderNode", "FunctionNode"):
        if text.startswith(prefix):
            return text[len(prefix):] or text
    return text


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value).strip()


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
