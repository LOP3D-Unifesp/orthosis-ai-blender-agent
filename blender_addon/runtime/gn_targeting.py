"""Canonical GN target resolution for one turn."""

from __future__ import annotations

from typing import Any

from ..runtime_planning import TREE_NAME_PATTERN

_CANONICAL_TREE_TOOLS = frozenset(
    {
        "build_tree_structural_memory",
        "classify_tree_phases",
        "map_clinical_parameter_roles",
        "interpret_orthosis_tree_logic",
        "get_node_context",
        "get_selected_nodes_context",
        "get_active_frame_context",
        "get_local_subgraph_context",
        "get_changes_since_last_turn",
        "get_tree_parameters",
        "apply_simulator_payload",
    }
)


def resolve_canonical_gn_target(
    *,
    message: str,
    session: Any,
    gn_hosts: list[dict[str, Any]],
    scene_summary: dict[str, Any] | None = None,
    local_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hosts = [_normalize_host(host) for host in gn_hosts if isinstance(host, dict)]
    hosts = [host for host in hosts if host["tree_name"]]
    if not hosts:
        focus = getattr(session, "focus", None)
        return {
            "status": "missing",
            "question": "Não encontrei nenhum host de Geometry Nodes ativo. Qual objeto/modificador devo usar neste turno?",
            "target": _bundle_from_focus(focus, local_scope),
            "source": "missing",
            "explicit": False,
        }

    explicit_candidates = _explicit_candidates(message, hosts)
    if len(explicit_candidates) == 1:
        return _resolved(explicit_candidates[0], source="explicit", explicit=True, local_scope=local_scope)
    if len(explicit_candidates) > 1:
        return _ambiguous(explicit_candidates, reason="explicit_multiple")

    focus = getattr(session, "focus", None)
    focused = _match_focus_host(focus, hosts)
    if focused is not None:
        return _resolved(focused, source="session_focus", explicit=False, local_scope=local_scope)

    if len(hosts) == 1:
        return _resolved(hosts[0], source="single_host", explicit=False, local_scope=local_scope)

    active_object = str((scene_summary or {}).get("active_object") or "").strip()
    if active_object:
        active_hosts = [host for host in hosts if host["object"] == active_object]
        if len(active_hosts) == 1:
            return _resolved(active_hosts[0], source="active_object", explicit=False, local_scope=local_scope)
        if len(active_hosts) > 1:
            return _ambiguous(active_hosts, reason="active_object_multiple")

    return _ambiguous(hosts, reason="multiple_hosts")


def canonicalize_gn_tool_input(
    tool_name: str,
    tool_input: dict[str, Any] | None,
    canonical_target: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    normalized = dict(tool_input or {})
    if tool_name not in _CANONICAL_TREE_TOOLS or not isinstance(canonical_target, dict):
        return normalized, None

    canonical_tree = str(canonical_target.get("tree_name") or "").strip()
    if not canonical_tree:
        return normalized, None

    requested_tree = str(normalized.get("tree_name") or "").strip()
    if requested_tree and requested_tree != canonical_tree:
        return normalized, {
            "tool_name": tool_name,
            "requested_tree": requested_tree,
            "canonical_tree": canonical_tree,
        }

    normalized["tree_name"] = canonical_tree
    return normalized, None


def format_target_clarification(result: dict[str, Any]) -> str:
    candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
    choices = [
        f"`{item.get('object', '?')} / {item.get('modifier', '?')} / {item.get('tree_name', '?')}`"
        for item in candidates[:4]
        if isinstance(item, dict)
    ]
    if choices:
        return (
            "Encontrei mais de um alvo Geometry Nodes possível neste turno. "
            "Qual deles devo usar?\n"
            + "\n".join(f"- {choice}" for choice in choices)
        )
    return "Não consegui identificar um alvo Geometry Nodes único. Qual objeto/modificador/node group devo usar neste turno?"


def build_target_log_payload(result: dict[str, Any]) -> dict[str, Any]:
    target = result.get("target") if isinstance(result.get("target"), dict) else {}
    return {
        "target": dict(target),
        "source": str(result.get("source") or ""),
        "explicit": bool(result.get("explicit", False)),
    }


def _normalize_host(host: dict[str, Any]) -> dict[str, str]:
    return {
        "object": str(host.get("object") or host.get("object_name") or "").strip(),
        "modifier": str(host.get("modifier") or host.get("modifier_name") or "").strip(),
        "tree_name": str(host.get("node_group") or host.get("group_name") or host.get("tree_name") or "").strip(),
    }


def _explicit_candidates(message: str, hosts: list[dict[str, str]]) -> list[dict[str, str]]:
    msg = str(message or "").strip()
    lowered = msg.lower()
    extracted_tree = ""
    match = TREE_NAME_PATTERN.search(msg)
    if match:
        extracted_tree = str(match.group(1) or "").strip().lower()

    candidates: list[dict[str, str]] = []
    for host in hosts:
        tree_name = host["tree_name"].lower()
        modifier = host["modifier"].lower()
        object_name = host["object"].lower()
        if extracted_tree and tree_name == extracted_tree:
            candidates.append(host)
            continue
        if tree_name and tree_name in lowered:
            candidates.append(host)
            continue
        if modifier and modifier in lowered:
            candidates.append(host)
            continue
        if object_name and object_name in lowered:
            candidates.append(host)
            continue
    return _dedupe_hosts(candidates)


def _match_focus_host(focus: Any, hosts: list[dict[str, str]]) -> dict[str, str] | None:
    if focus is None:
        return None
    focus_tree = str(getattr(focus, "tree_name", "") or "").strip()
    focus_modifier = str(getattr(focus, "modifier_name", "") or "").strip()
    focus_object = str(getattr(focus, "object_name", "") or "").strip()
    matches = [
        host
        for host in hosts
        if (focus_tree and host["tree_name"] == focus_tree)
        or (
            focus_object
            and focus_modifier
            and host["object"] == focus_object
            and host["modifier"] == focus_modifier
        )
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _resolved(
    host: dict[str, str],
    *,
    source: str,
    explicit: bool,
    local_scope: dict[str, Any] | None,
) -> dict[str, Any]:
    target = {
        "object": host["object"],
        "modifier": host["modifier"],
        "tree_name": host["tree_name"],
        "local_focus": _local_focus_for_tree(local_scope, host["tree_name"]),
    }
    return {
        "status": "resolved",
        "target": target,
        "source": source,
        "explicit": explicit,
    }


def _ambiguous(candidates: list[dict[str, str]], *, reason: str) -> dict[str, Any]:
    return {
        "status": "ambiguous",
        "reason": reason,
        "candidates": _dedupe_hosts(candidates),
        "source": "ambiguous",
        "explicit": False,
    }


def _bundle_from_focus(focus: Any, local_scope: dict[str, Any] | None) -> dict[str, Any]:
    object_name = str(getattr(focus, "object_name", "") or "").strip()
    modifier_name = str(getattr(focus, "modifier_name", "") or "").strip()
    tree_name = str(getattr(focus, "tree_name", "") or "").strip()
    return {
        "object": object_name,
        "modifier": modifier_name,
        "tree_name": tree_name,
        "local_focus": _local_focus_for_tree(local_scope, tree_name),
    }


def _local_focus_for_tree(local_scope: dict[str, Any] | None, tree_name: str) -> dict[str, Any] | None:
    scope = dict(local_scope or {})
    if str(scope.get("tree_name") or "").strip() != str(tree_name or "").strip():
        return None
    if str(scope.get("scope_type") or "") == "selected_nodes":
        return {"selected_nodes": list(scope.get("node_names") or [])}
    if str(scope.get("scope_type") or "") == "active_frame":
        return {"active_frame": str(scope.get("frame_name") or "").strip()}
    return None


def _dedupe_hosts(hosts: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, str]] = []
    for host in hosts:
        key = (host["object"], host["modifier"], host["tree_name"])
        if key in seen:
            continue
        seen.add(key)
        out.append(host)
    return out
