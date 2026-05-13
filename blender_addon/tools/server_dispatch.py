"""Shared runtime dispatch for product chat and MCP adapter routes."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import draft, execution, handlers, query, reads, snapshots, tree_analysis as _ta
from ..project_paths import canonical_project_root


# ---------------------------------------------------------------------------
# Skill router (inlined from skill_router.py)
# ---------------------------------------------------------------------------

OutputMode = str


def _candidate_repo_roots() -> list[Path]:
    candidates: list[Path] = [canonical_project_root()]
    this_file = Path(__file__).resolve()
    for parent in this_file.parents:
        candidates.append(parent)
        if parent.name == "blender_addon":
            candidates.append(parent.parent)

    seen: set[str] = set()
    ordered: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(candidate)
    return ordered


def _ensure_skills_importable() -> None:
    if importlib.util.find_spec("skills") is not None:
        return

    tried: list[str] = []
    for root in _candidate_repo_roots():
        try:
            resolved = root.resolve()
        except Exception:
            continue
        skills_dir = resolved / "skills"
        if not skills_dir.is_dir():
            continue
        tried.append(str(resolved))
        root_text = str(resolved)
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
        if importlib.util.find_spec("skills") is not None:
            return

    tried_text = ", ".join(tried) if tried else "no candidates with /skills found"
    raise ModuleNotFoundError(
        "No module named 'skills'. Set Add-on Preferences -> Project Root Path "
        "to the project root folder (contains skills/ and blender_addon/). "
        f"Tried: {tried_text}"
    )


def _import_skill_functions():
    try:
        _ensure_skills_importable()

        from skills.gn_scene_state_interpreter.scripts import build_report as build_gn_report
        from skills.scene_context_inspector.scripts import build_report as build_scene_report

        return build_gn_report, build_scene_report
    except Exception:
        return _build_local_gn_report, _build_local_scene_report


def _collect_gn_hosts(scene_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    hosts: list[dict[str, Any]] = []
    for obj in scene_snapshot.get("objects", []):
        if not isinstance(obj, dict):
            continue
        for mod in obj.get("modifiers", []):
            if not isinstance(mod, dict) or mod.get("type") != "NODES":
                continue
            hosts.append(
                {
                    "object_name": obj.get("name", ""),
                    "modifier_name": mod.get("name", ""),
                    "group_name": mod.get("node_group", ""),
                    "enabled": bool(mod.get("enabled", True)),
                    "input_count": int(mod.get("gn_input_count", 0) or 0),
                }
            )
    return hosts


def _build_local_scene_report(
    *,
    scene_snapshot: dict[str, Any],
    node_trees_snapshot: dict | None = None,
    current_goal: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    scene_meta = scene_snapshot.get("scene", {}) if isinstance(scene_snapshot.get("scene"), dict) else {}
    objects = [obj for obj in scene_snapshot.get("objects", []) if isinstance(obj, dict)]
    gn_hosts = _collect_gn_hosts(scene_snapshot)
    relevant_objects = [
        {
            "name": obj.get("name", ""),
            "type": obj.get("object_type", ""),
            "heuristic_class": obj.get("heuristic_class", ""),
            "has_gn": any(
                isinstance(mod, dict) and mod.get("type") == "NODES"
                for mod in obj.get("modifiers", [])
            ),
            "selected": bool(obj.get("selected", False)),
            "visible": bool(obj.get("visible", True)),
        }
        for obj in objects
    ]
    relevant_objects.sort(
        key=lambda item: (
            not item["has_gn"],
            not item["selected"],
            not item["visible"],
            str(item["name"]).lower(),
        )
    )

    risk_signals: list[dict[str, Any]] = []
    if not gn_hosts:
        risk_signals.append(
            {
                "severity": "medium",
                "signal": "no_geometry_nodes_hosts",
                "message": "Nenhum modificador Geometry Nodes foi detectado na cena.",
            }
        )
    if not scene_meta.get("active_object"):
        risk_signals.append(
            {
                "severity": "low",
                "signal": "no_active_object",
                "message": "Nao ha objeto ativo definido na cena.",
            }
        )

    selected_names = scene_meta.get("selected_objects", [])
    phase_estimate = "scene_review"
    if gn_hosts:
        phase_estimate = "gn_editing"
    if selected_names and gn_hosts:
        phase_estimate = "focused_gn_editing"

    follow_up_recs: list[str] = []
    if gn_hosts and not selected_names:
        follow_up_recs.append("Selecione o objeto hospedeiro do Geometry Nodes antes de editar.")
    if gn_hosts and not scene_meta.get("active_object"):
        follow_up_recs.append("Defina um objeto ativo para ancorar o contexto da sessao.")
    if not gn_hosts:
        follow_up_recs.append("Use get_gn_hosts ou adicione um modificador Geometry Nodes ao objeto alvo.")

    return {
        "schema_version": scene_snapshot.get("schema_version", "local-fallback"),
        "context_id": scene_snapshot.get("context_id", ""),
        "query_used": query or "summarize_scene_for_current_round",
        "scene_summary": {
            "scene_name": scene_meta.get("name", ""),
            "object_count": int(scene_meta.get("object_count", len(objects)) or 0),
            "active_object": scene_meta.get("active_object"),
            "selected_objects": list(selected_names) if isinstance(selected_names, list) else [],
            "collections": (
                list(scene_meta.get("collections", []))
                if isinstance(scene_meta.get("collections"), list)
                else []
            ),
            "current_goal": current_goal or "",
        },
        "workflow_signals": {
            "phase_estimate": phase_estimate,
            "orthosis_gn_output_detected": bool(gn_hosts),
            "orthosis_gn_output_suspected_empty": False,
        },
        "gn_report": {
            "gn_objects_count": len({host.get("object_name", "") for host in gn_hosts if host.get("object_name")}),
            "risk_signals": risk_signals,
        },
        "relevant_objects": relevant_objects[:8],
        "ambiguities": [] if scene_meta.get("active_object") else ["Nenhum objeto ativo definido no momento."],
        "follow_up_recs": follow_up_recs[:5],
        "screenshot_recs": [],
    }


def _build_local_gn_report(
    *,
    scene_snapshot: dict[str, Any],
    node_trees_snapshot: dict | None = None,
    current_goal: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    node_groups = []
    if isinstance(node_trees_snapshot, dict):
        node_groups = [group for group in node_trees_snapshot.get("node_groups", []) if isinstance(group, dict)]

    gn_hosts = _collect_gn_hosts(scene_snapshot)
    structural_flags: list[dict[str, Any]] = []
    node_trees: list[dict[str, Any]] = []
    node_inventory: list[dict[str, Any]] = []
    link_inventory: list[dict[str, Any]] = []
    group_interfaces: list[dict[str, Any]] = []
    domain_hypotheses: list[dict[str, Any]] = []

    for group in node_groups:
        group_name = str(group.get("name", "") or "")
        nodes = [node for node in group.get("nodes", []) if isinstance(node, dict)]
        links = [link for link in group.get("links", []) if isinstance(link, dict)]
        interface = group.get("interface", {}) if isinstance(group.get("interface"), dict) else {}
        inputs = [item for item in interface.get("inputs", []) if isinstance(item, dict)]
        outputs = [item for item in interface.get("outputs", []) if isinstance(item, dict)]
        bindings = [item for item in group.get("bindings", []) if isinstance(item, dict)]

        warnings: list[str] = []
        if not bindings:
            warnings.append("Node group sem objeto/modifier vinculado.")
            structural_flags.append(
                {
                    "severity": "medium",
                    "flag": "unbound_node_group",
                    "group_name": group_name,
                    "message": f"O grupo '{group_name}' nao esta vinculado a nenhum objeto.",
                }
            )
        if int(group.get("node_count", 0) or 0) == 0:
            warnings.append("Node group vazio.")
            structural_flags.append(
                {
                    "severity": "high",
                    "flag": "empty_node_group",
                    "group_name": group_name,
                    "message": f"O grupo '{group_name}' nao possui nos.",
                }
            )
        if not outputs:
            warnings.append("Sem saidas de interface.")
        if group.get("truncated"):
            warnings.append("Snapshot truncado para caber no limite de captura.")

        node_trees.append(
            {
                "group_name": group_name,
                "node_count": int(group.get("node_count", len(nodes)) or 0),
                "link_count": len(links),
                "structural_warnings": warnings[:4],
            }
        )
        group_interfaces.append(
            {
                "group_name": group_name,
                "inputs": inputs,
                "outputs": outputs,
            }
        )
        for node in nodes:
            node_inventory.append(
                {
                    "group_name": group_name,
                    "node_name": node.get("name", ""),
                    "label": node.get("label", ""),
                    "node_type": node.get("type", ""),
                }
            )
        for link in links:
            item = dict(link)
            item["group_name"] = group_name
            link_inventory.append(item)

        used_by = list(group.get("used_by_objects", [])) if isinstance(group.get("used_by_objects"), list) else []
        domain_hypotheses.append(
            {
                "group_name": group_name,
                "used_by_objects": used_by,
                "node_count": int(group.get("node_count", len(nodes)) or 0),
                "current_goal": current_goal or "",
            }
        )

    if not node_groups:
        structural_flags.append(
            {
                "severity": "medium",
                "flag": "no_geometry_node_groups",
                "group_name": "",
                "message": "Nenhum GeometryNodeTree foi capturado no snapshot atual.",
            }
        )

    return {
        "schema_version": (
            node_trees_snapshot.get("schema_version", scene_snapshot.get("schema_version", "local-fallback"))
            if isinstance(node_trees_snapshot, dict)
            else scene_snapshot.get("schema_version", "local-fallback")
        ),
        "context_id": scene_snapshot.get("context_id", ""),
        "query_used": query or "inspect_deep_structure",
        "gn_hosts": gn_hosts,
        "domain_hypotheses": domain_hypotheses[:8],
        "node_trees": node_trees,
        "node_inventory": node_inventory,
        "link_inventory": link_inventory,
        "group_interfaces": group_interfaces,
        "structural_flags": structural_flags,
        "visual_capture_recommendations": [],
        "follow_up_inspection_suggestions": (
            ["Defina tree_name para focar em um grupo especifico antes de mutar."]
            if len(node_trees) > 1
            else []
        ),
    }


class SkillRouter:
    """Thin adapter around analytical skills with compact output defaults."""

    def __init__(self):
        self.supported_output_modes = {"compact", "verbose", "debug"}

    def _normalize_output_mode(self, output_mode: str | None) -> OutputMode:
        mode = (output_mode or "compact").strip().lower()
        if mode not in self.supported_output_modes:
            return "compact"
        return mode

    def analyze_scene(
        self,
        *,
        scene_snapshot: dict,
        node_trees_snapshot: dict | None = None,
        current_goal: str | None = None,
        query: str | None = None,
        output_mode: str | None = "compact",
    ) -> dict[str, Any]:
        _, build_scene_report = _import_skill_functions()
        mode = self._normalize_output_mode(output_mode)
        report = build_scene_report(
            scene_snapshot=scene_snapshot,
            node_trees_snapshot=node_trees_snapshot,
            current_goal=current_goal,
            query=query or "summarize_scene_for_current_round",
        )
        if mode == "verbose":
            return report
        compact = self._compact_scene_report(report)
        if mode == "debug":
            compact["debug"] = {"full_report": report}
        return compact

    def _compact_scene_report(self, report: dict[str, Any]) -> dict[str, Any]:
        relevant = report.get("relevant_objects", [])[:8]
        gn_report = report.get("gn_report", {})
        return {
            "schema_version": report.get("schema_version"),
            "context_id": report.get("context_id"),
            "query_used": report.get("query_used"),
            "scene_summary": report.get("scene_summary", {}),
            "workflow_phase": report.get("workflow_signals", {}).get("phase_estimate", "unknown"),
            "gn_status": {
                "gn_objects_count": gn_report.get("gn_objects_count", 0),
                "risk_signal_count": len(gn_report.get("risk_signals", [])),
                "orthosis_output_detected": report.get("workflow_signals", {}).get("orthosis_gn_output_detected", False),
                "orthosis_output_suspected_empty": report.get("workflow_signals", {}).get(
                    "orthosis_gn_output_suspected_empty", False
                ),
            },
            "relevant_objects": relevant,
            "top_ambiguities": report.get("ambiguities", [])[:5],
            "follow_up_recs": report.get("follow_up_recs", [])[:5],
            "screenshot_recs": report.get("screenshot_recs", [])[:3],
        }


def _json_error(message: str, **extra: Any) -> dict[str, Any]:
    payload = {"status": "error", "error": message}
    payload.update(extra)
    return payload


class RuntimeDispatcher:
    """Canonical runtime tool surface executed inside Blender."""

    _VALID_DRAFT_GOAL_MODES = {"diagnose_only", "focal_correction", "functional_expansion", "feedback_fix"}

    # Tool name → bound handler method name.  Each handler has the uniform
    # signature (self, tool_input, *, output_mode, session_state) -> dict.
    _TOOL_HANDLERS: dict[str, str] = {
        "get_scene_summary":           "_tool_get_scene_summary",
        "get_gn_hosts":                "_tool_get_gn_hosts",
        "get_tree_parameters":         "_tool_get_tree_parameters",
        "prepare_draft_context":       "_tool_prepare_draft_context",
        "resolve_gn_workspace":        "_tool_resolve_gn_workspace",
        "build_tree_structural_memory": "_tool_build_tree_structural_memory",
        "classify_tree_phases":        "_tool_classify_tree_phases",
        "map_clinical_parameter_roles": "_tool_map_clinical_parameter_roles",
        "get_node_context":            "_tool_get_node_context",
        "get_selected_nodes_context":  "_tool_get_selected_nodes_context",
        "get_active_frame_context":    "_tool_get_active_frame_context",
        "get_local_subgraph_context":  "_tool_get_local_subgraph_context",
        "get_changes_since_last_turn": "_tool_get_changes_since_last_turn",
        "analyze_scene":               "_tool_analyze_scene",
        "list_tree_nodes":             "_tool_list_tree_nodes",
        "find_tree_nodes":             "_tool_find_tree_nodes",
        "capture_screenshot":          "_tool_capture_screenshot",
        "execute_code":                "_tool_execute_code",
        "query_node_types":            "_tool_query_node_types",
        "write_script_draft":          "_tool_write_script_draft",
        "read_script_draft":           "_tool_read_script_draft",
    }

    def __init__(self):
        self.skill_router = SkillRouter()
        self._gn_analysis_cache: dict[str, tuple[str, dict[str, Any]]] = {}

    def execute(
        self,
        tool_name: str,
        tool_input: dict[str, Any] | None = None,
        *,
        output_mode: str = "compact",
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tool_input = tool_input or {}
        handler_name = self._TOOL_HANDLERS.get(tool_name)
        if handler_name is None:
            return _json_error(f"Unknown tool: {tool_name}")
        try:
            return getattr(self, handler_name)(
                tool_input,
                output_mode=output_mode,
                session_state=session_state,
            )
        except KeyError as exc:
            return _json_error(f"Missing required input: {exc.args[0]}")
        except Exception as exc:
            return _json_error(f"Tool execution failed: {exc}")

    # ------------------------------------------------------------------
    # Per-tool handlers — uniform signature (tool_input, *, output_mode,
    # session_state).  Unused kwargs absorbed via **_.
    # ------------------------------------------------------------------

    def _tool_get_scene_summary(self, tool_input, **_):
        return self._get_scene_summary()

    def _tool_get_gn_hosts(self, tool_input, **_):
        return self._get_gn_hosts()

    def _tool_get_tree_parameters(self, tool_input, **_):
        tree_name = tool_input.get("tree_name")
        if not tree_name:
            return _json_error("Missing required input: tree_name")
        return self._get_tree_parameters(tree_name)

    def _tool_prepare_draft_context(self, tool_input, *, session_state=None, **_):
        return self._prepare_draft_context(tool_input, session_state=session_state)

    def _tool_resolve_gn_workspace(self, tool_input, *, session_state=None, **_):
        return self._resolve_gn_workspace(tool_input, session_state=session_state)

    def _tool_build_tree_structural_memory(self, tool_input, *, session_state=None, **_):
        return self._build_tree_structural_memory(tool_input, session_state=session_state)

    def _tool_classify_tree_phases(self, tool_input, *, session_state=None, **_):
        return self._classify_tree_phases(tool_input, session_state=session_state)

    def _tool_map_clinical_parameter_roles(self, tool_input, *, session_state=None, **_):
        return self._map_clinical_parameter_roles(tool_input, session_state=session_state)

    def _tool_get_node_context(self, tool_input, **_):
        if not tool_input.get("tree_name"):
            return _json_error("Missing required input: tree_name")
        return reads.handle_get_node_context(tool_input)

    def _tool_get_selected_nodes_context(self, tool_input, **_):
        if not tool_input.get("tree_name"):
            return _json_error("Missing required input: tree_name")
        return reads.handle_get_selected_nodes_context(tool_input)

    def _tool_get_active_frame_context(self, tool_input, **_):
        if not tool_input.get("tree_name"):
            return _json_error("Missing required input: tree_name")
        return reads.handle_get_active_frame_context(tool_input)

    def _tool_get_local_subgraph_context(self, tool_input, **_):
        if not tool_input.get("tree_name"):
            return _json_error("Missing required input: tree_name")
        return reads.handle_get_local_subgraph_context(tool_input)

    def _tool_get_changes_since_last_turn(self, tool_input, *, session_state=None, **_):
        return self._get_changes_since_last_turn(tool_input, session_state=session_state)

    def _tool_analyze_scene(self, tool_input, *, output_mode="compact", **_):
        return self._analyze_scene(tool_input, output_mode=output_mode)

    def _tool_capture_screenshot(self, tool_input, **_):
        return self._capture_screenshot(tool_input)

    def _tool_execute_code(self, tool_input, **_):
        code = tool_input.get("code", "")
        if not code and tool_input.get("script"):
            code = tool_input.get("script", "")
        if not code:
            return _json_error("Missing required input: code")
        return execution.handle_execute_code({"code": code})

    def _tool_query_node_types(self, tool_input, **_):
        return query.handle_query_node_types(tool_input)

    def _tool_list_tree_nodes(self, tool_input, **_):
        tree_name = tool_input.get("tree_name", "")
        if not tree_name:
            return _json_error("Missing required input: tree_name")
        return reads.handle_list_tree_nodes(tool_input)

    def _tool_find_tree_nodes(self, tool_input, **_):
        tree_name = tool_input.get("tree_name", "")
        if not tree_name:
            return _json_error("Missing required input: tree_name")
        return reads.handle_find_tree_nodes(tool_input)

    def _tool_write_script_draft(self, tool_input, **_):
        return draft.handle_write_script_draft(tool_input)

    def _tool_read_script_draft(self, tool_input, **_):
        return draft.handle_read_script_draft(tool_input)

    @staticmethod
    def _tree_hash(tree_data: dict[str, Any]) -> str:
        payload = json.dumps(
            {"nodes": tree_data.get("nodes", []), "links": tree_data.get("links", [])},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.md5(payload.encode("utf-8")).hexdigest()[:12]

    def _capture_scene(self) -> dict[str, Any]:
        result = snapshots.handle_capture_scene({})
        if result.get("status") != "success":
            return {}
        return result.get("result", {})

    def _capture_node_trees(self) -> dict[str, Any]:
        result = snapshots.handle_capture_node_trees({})
        if result.get("status") != "success":
            return {}
        return result.get("result", {})

    def _capture_full(self) -> dict[str, Any]:
        result = snapshots.handle_capture_full({})
        if result.get("status") != "success":
            return {}
        return result.get("result", {})

    def _get_scene_summary(self) -> dict[str, Any]:
        scene = self._capture_scene()
        if not scene:
            return _json_error("Failed to capture scene")
        objects = scene.get("objects", [])
        summary = {
            "scene_name": scene.get("scene", {}).get("name"),
            "object_count": scene.get("scene", {}).get("object_count", 0),
            "active_object": scene.get("scene", {}).get("active_object"),
            "selected_objects": scene.get("scene", {}).get("selected_objects", []),
            "collections": scene.get("scene", {}).get("collections", []),
            "objects": [
                {
                    "name": obj.get("name"),
                    "type": obj.get("object_type"),
                    "collection": obj.get("collection"),
                    "has_gn": any(mod.get("type") == "NODES" for mod in obj.get("modifiers", [])),
                    "visible": obj.get("visible", True),
                }
                for obj in objects
            ],
        }
        return {"status": "success", "result": summary}

    def _get_gn_hosts(self) -> dict[str, Any]:
        scene = self._capture_scene()
        if not scene:
            return _json_error("Failed to capture scene")
        hosts = []
        for obj in scene.get("objects", []):
            for mod in obj.get("modifiers", []):
                if mod.get("type") != "NODES":
                    continue
                hosts.append(
                    {
                        "object": obj.get("name"),
                        "modifier": mod.get("name"),
                        "node_group": mod.get("node_group"),
                        "enabled": mod.get("enabled", True),
                        "gn_input_count": mod.get("gn_input_count", 0),
                    }
                )
        return {"status": "success", "result": {"gn_hosts": hosts, "count": len(hosts)}}

    def _get_tree_structure(self, tree_name: str) -> dict[str, Any]:
        snap = self._capture_node_trees()
        for node_group in snap.get("node_groups", []):
            if node_group.get("name") == tree_name:
                return {
                    "status": "success",
                    "result": {
                        "name": node_group.get("name"),
                        "node_count": node_group.get("node_count", 0),
                        "nodes": node_group.get("nodes", []),
                        "links": node_group.get("links", []),
                        "interface": node_group.get("interface", {}),
                        "used_by_objects": node_group.get("used_by_objects", []),
                    },
                }
        return _json_error(
            f"Tree '{tree_name}' not found",
            available_trees=[group.get("name") for group in snap.get("node_groups", [])],
        )

    def _get_tree_parameters(self, tree_name: str) -> dict[str, Any]:
        scene = self._capture_scene()
        if not scene:
            return _json_error("Failed to capture scene")
        for obj in scene.get("objects", []):
            for mod in obj.get("modifiers", []):
                if mod.get("type") == "NODES" and mod.get("node_group") == tree_name:
                    return {
                        "status": "success",
                        "result": {
                            "tree": tree_name,
                            "object": obj.get("name"),
                            "modifier": mod.get("name"),
                            "parameters": mod.get("gn_inputs", []),
                        },
                    }
        return _json_error(f"No object found using tree '{tree_name}'.")

    def _draft_context_summary(
        self,
        *,
        goal_mode: str,
        tree_name: str,
        workspace: dict[str, Any],
        memory: dict[str, Any],
        phase: dict[str, Any],
        clinical_roles: dict[str, Any],
        interpretation: dict[str, Any],
        goal_guidance: dict[str, Any],
        write_requirements: dict[str, Any],
        coverage: dict[str, Any],
        warnings: list[str],
    ) -> str:
        lines = ["Prepared deterministic draft context:"]
        lines.append(f"- goal_mode: {goal_mode}")
        binding = workspace.get("selected_binding", {}) if isinstance(workspace.get("selected_binding"), dict) else {}
        if tree_name:
            lines.append(
                f"- target_tree: {tree_name} "
                f"(reason={workspace.get('selection_reason', '') or 'unknown'}, "
                f"confidence={str((workspace.get('confidence') or {}).get('level', 'unknown'))})"
            )
        if binding:
            object_name = str(binding.get("object_name") or "").strip()
            modifier_name = str(binding.get("modifier_name") or "").strip()
            if object_name or modifier_name:
                lines.append(f"- bound_modifier: object={object_name or '?'} modifier={modifier_name or '?'}")
        if memory:
            lines.append(
                f"- structural_memory: nodes={int(memory.get('node_count', 0) or 0)}, "
                f"frames={int(memory.get('frame_count', 0) or 0)}, "
                f"phase_hint={str(memory.get('phase_dominant') or 'unknown')}"
            )
        if phase:
            lines.append(
                f"- workflow_phase: {str(phase.get('tree_phase') or 'unknown')} "
                f"(confidence={str((phase.get('confidence') or {}).get('level', 'unknown'))})"
            )
        clinical_summary = clinical_roles.get("summary", {}) if isinstance(clinical_roles.get("summary"), dict) else {}
        if clinical_summary:
            lines.append(
                f"- clinical_parameters: measurements={int(clinical_summary.get('measurement_count', 0) or 0)}, "
                f"positioning={int(clinical_summary.get('positioning_count', 0) or 0)}, "
                f"uncertain={int(clinical_summary.get('uncertain_count', 0) or 0)}"
            )
        workflow_stage = interpretation.get("workflow_stage_summary", {}) if isinstance(interpretation.get("workflow_stage_summary"), dict) else {}
        if workflow_stage:
            lines.append(
                f"- stage_counts: biomodel={int(workflow_stage.get('biomodel_region_count', 0) or 0)}, "
                f"curve={int(workflow_stage.get('curve_region_count', 0) or 0)}, "
                f"orthosis={int(workflow_stage.get('orthosis_region_count', 0) or 0)}"
            )
        focus_regions = interpretation.get("suggested_focus_regions", []) if isinstance(interpretation.get("suggested_focus_regions"), list) else []
        if focus_regions:
            sample = ", ".join(
                str(item.get("region") or "").strip()
                for item in focus_regions[:4]
                if isinstance(item, dict) and str(item.get("region") or "").strip()
            )
            if sample:
                lines.append(f"- suggested_focus: {sample}")
        next_targets = interpretation.get("next_structural_targets", []) if isinstance(interpretation.get("next_structural_targets"), list) else []
        if next_targets:
            lines.append(f"- next_target: {str(next_targets[0])[:180]}")
        guidance_summary = _ta._norm_text(goal_guidance.get("summary"))
        if guidance_summary:
            lines.append(f"- mode_summary: {guidance_summary}")
        suggested_output = _ta._norm_text(goal_guidance.get("suggested_output"))
        if suggested_output:
            lines.append(f"- suggested_output: {suggested_output}")
        focus_priorities = goal_guidance.get("focus_priorities", []) if isinstance(goal_guidance.get("focus_priorities"), list) else []
        if focus_priorities:
            sample = ", ".join(str(item)[:80] for item in focus_priorities[:4] if _ta._norm_text(item))
            if sample:
                lines.append(f"- focus_priorities: {sample}")
        blockers = write_requirements.get("blockers", []) if isinstance(write_requirements.get("blockers"), list) else []
        lines.append(
            f"- write_gate: can_write_safely={bool(write_requirements.get('can_write_safely', False))} "
            f"blockers={', '.join(str(v) for v in blockers[:4]) if blockers else 'none'}"
        )
        if coverage:
            lines.append(
                f"- coverage_refresh: confirmed_this_turn={bool(coverage.get('coverage_confirmed_this_turn', False))} "
                f"refresh_needed={bool(coverage.get('coverage_refresh_needed', False))}"
            )
        if warnings:
            lines.append(f"- warnings: {' | '.join(str(v) for v in warnings[:3])}")
        return "\n".join(lines)

    def _draft_context_coverage(
        self,
        *,
        live_parameters: dict[str, Any],
        clinical_roles: dict[str, Any],
        interpretation: dict[str, Any],
        structural_memory: dict[str, Any],
        stored_live_node_refs: list[str],
        stored_expected_parameter_refs: list[str],
        stored_expected_focus_regions: list[str],
    ) -> dict[str, Any]:
        confirmed_parameter_refs: list[str] = []
        params = live_parameters.get("parameters", []) if isinstance(live_parameters.get("parameters"), list) else []
        for item in params[:12]:
            if not isinstance(item, dict):
                continue
            for key in ("name", "identifier"):
                value = _ta._norm_text(item.get(key))
                if value and value not in confirmed_parameter_refs:
                    confirmed_parameter_refs.append(value)
        for key in ("measurement_parameters", "positioning_parameters"):
            values = clinical_roles.get(key, []) if isinstance(clinical_roles.get(key), list) else []
            for item in values[:12]:
                if not isinstance(item, dict):
                    continue
                for field in ("name", "identifier", "role"):
                    value = _ta._norm_text(item.get(field))
                    if value and value not in confirmed_parameter_refs:
                        confirmed_parameter_refs.append(value)
        confirmed_focus_regions: list[str] = []
        for key in ("suggested_focus_regions",):
            values = interpretation.get(key, []) if isinstance(interpretation.get(key), list) else []
            for item in values[:12]:
                if not isinstance(item, dict):
                    continue
                for field in ("region", "name", "label"):
                    value = _ta._norm_text(item.get(field))
                    if value and value not in confirmed_focus_regions:
                        confirmed_focus_regions.append(value)
        likely_regions = clinical_roles.get("likely_affected_regions", []) if isinstance(clinical_roles.get("likely_affected_regions"), list) else []
        for item in likely_regions[:12]:
            if not isinstance(item, dict):
                continue
            for field in ("region", "name", "label"):
                value = _ta._norm_text(item.get(field))
                if value and value not in confirmed_focus_regions:
                    confirmed_focus_regions.append(value)
        major_regions = structural_memory.get("major_regions", []) if isinstance(structural_memory.get("major_regions"), list) else []
        for item in major_regions[:12]:
            if not isinstance(item, dict):
                continue
            for field in ("name", "label", "probable_function"):
                value = _ta._norm_text(item.get(field))
                if value and value not in confirmed_focus_regions:
                    confirmed_focus_regions.append(value)
        persisted_live_refs = [_ta._norm_text(item) for item in stored_live_node_refs if _ta._norm_text(item)][:8]
        persisted_parameter_refs = [_ta._norm_text(item) for item in stored_expected_parameter_refs if _ta._norm_text(item)][:10]
        persisted_focus_regions = [_ta._norm_text(item) for item in stored_expected_focus_regions if _ta._norm_text(item)][:10]
        coverage_confirmed_this_turn = bool(confirmed_parameter_refs or confirmed_focus_regions or structural_memory)
        coverage_refresh_needed = bool(
            (persisted_live_refs or persisted_parameter_refs or persisted_focus_regions)
            and not coverage_confirmed_this_turn
        )
        return {
            "confirmed_parameter_refs": confirmed_parameter_refs[:10],
            "confirmed_focus_regions": confirmed_focus_regions[:10],
            "persisted_live_node_refs": persisted_live_refs,
            "persisted_expected_parameter_refs": persisted_parameter_refs,
            "persisted_expected_focus_regions": persisted_focus_regions,
            "coverage_confirmed_this_turn": coverage_confirmed_this_turn,
            "coverage_refresh_needed": coverage_refresh_needed,
        }

    def _draft_goal_guidance(
        self,
        *,
        goal_mode: str,
        clinical_roles: dict[str, Any],
        interpretation: dict[str, Any],
        has_existing_draft: bool,
    ) -> dict[str, Any]:
        focus_priorities: list[str] = []
        suggested_regions = interpretation.get("suggested_focus_regions", []) if isinstance(interpretation.get("suggested_focus_regions"), list) else []
        for item in suggested_regions[:4]:
            if not isinstance(item, dict):
                continue
            region = _ta._norm_text(item.get("region") or item.get("name") or item.get("label"))
            if region and region not in focus_priorities:
                focus_priorities.append(region)
        measurement_parameters = clinical_roles.get("measurement_parameters", []) if isinstance(clinical_roles.get("measurement_parameters"), list) else []
        for item in measurement_parameters[:3]:
            if not isinstance(item, dict):
                continue
            name = _ta._norm_text(item.get("name") or item.get("identifier") or item.get("role"))
            if name and name not in focus_priorities:
                focus_priorities.append(name)
        if goal_mode == "diagnose_only":
            return {
                "summary": "Diagnose the current living draft before proposing a rewrite.",
                "suggested_output": "analysis_with_likely_failure_and_smallest_next_fix",
                "focus_priorities": focus_priorities[:5],
                "preservation_priority": "preserve_current_capabilities_while_explaining_failure",
            }
        if goal_mode == "focal_correction":
            return {
                "summary": "Apply the smallest safe correction to the current living draft.",
                "suggested_output": "single_targeted_revision",
                "focus_priorities": focus_priorities[:5],
                "preservation_priority": "preserve_anchors_tree_and_existing_scope",
            }
        if goal_mode == "feedback_fix":
            return {
                "summary": "Fix the current living draft using the latest execution feedback.",
                "suggested_output": "single_feedback_driven_revision",
                "focus_priorities": focus_priorities[:5],
                "preservation_priority": "preserve_anchors_tree_and_existing_scope",
            }
        return {
            "summary": (
                "Extend the same living draft with the next capability without regressing existing regions."
                if has_existing_draft else
                "Create the first complete living draft from the resolved context."
            ),
            "suggested_output": "incremental_feature_expansion",
            "focus_priorities": focus_priorities[:5],
            "preservation_priority": "preserve_working_regions_while_adding_new_scope",
        }

    def _prepare_draft_context(
        self,
        tool_input: dict[str, Any],
        *,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        goal_mode = self._normalize_draft_goal_mode(tool_input.get("goal_mode"))
        has_existing_draft = bool(tool_input.get("has_existing_draft", False))
        stored_live_node_refs = [
            _ta._norm_text(item) for item in (tool_input.get("stored_live_node_refs") or [])
            if _ta._norm_text(item)
        ][:8]
        stored_expected_parameter_refs = [
            _ta._norm_text(item) for item in (tool_input.get("stored_expected_parameter_refs") or [])
            if _ta._norm_text(item)
        ][:10]
        stored_expected_focus_regions = [
            _ta._norm_text(item) for item in (tool_input.get("stored_expected_focus_regions") or [])
            if _ta._norm_text(item)
        ][:10]
        resolved = self._resolve_gn_workspace(tool_input, session_state=session_state)
        if resolved.get("status") != "success":
            return resolved
        workspace = resolved.get("result", {}) if isinstance(resolved.get("result"), dict) else {}
        requested_tree = _ta._norm_text(tool_input.get("tree_name"))
        tree_name = requested_tree or _ta._norm_text(workspace.get("selected_tree"))

        warnings = [
            str(item)
            for item in workspace.get("warnings", [])
            if str(item).strip()
        ] if isinstance(workspace.get("warnings"), list) else []

        if not tree_name:
            goal_guidance = self._draft_goal_guidance(
                goal_mode=goal_mode,
                clinical_roles={},
                interpretation={},
                has_existing_draft=has_existing_draft,
            )
            write_requirements = {
                "goal_mode": goal_mode,
                "mode_allows_write": goal_mode != "diagnose_only",
                "resolved_target_tree": False,
                "structural_memory_available": False,
                "parameter_context_available": False,
                "workflow_interpretation_available": False,
                "can_write_safely": False,
                "recommended_next_step": (
                    "diagnose_workspace_targeting_before_writing"
                    if goal_mode == "diagnose_only" else
                    "resolve_target_tree_before_writing"
                ),
                "blockers": ["target_tree_unresolved"],
                "validation_checks": [
                    "Resolve a target Geometry Nodes tree before attempting to write a full draft.",
                ],
            }
            return {
                "status": "success",
                "result": {
                    "goal_mode": goal_mode,
                    "goal_guidance": goal_guidance,
                    "tree_name": "",
                    "workspace": workspace,
                    "structural_memory": {},
                    "phase_classification": {},
                    "clinical_parameter_roles": {},
                    "orthosis_interpretation": {},
                    "coverage": {
                        "confirmed_parameter_refs": [],
                        "confirmed_focus_regions": [],
                        "persisted_live_node_refs": stored_live_node_refs,
                        "persisted_expected_parameter_refs": stored_expected_parameter_refs,
                        "persisted_expected_focus_regions": stored_expected_focus_regions,
                        "coverage_confirmed_this_turn": False,
                        "coverage_refresh_needed": bool(
                            stored_live_node_refs
                            or stored_expected_parameter_refs
                            or stored_expected_focus_regions
                        ),
                    },
                    "write_requirements": write_requirements,
                    "context_ready": False,
                    "warnings": warnings,
                    "prompt_context": self._draft_context_summary(
                        goal_mode=goal_mode,
                        tree_name="",
                        workspace=workspace,
                        memory={},
                        phase={},
                        clinical_roles={},
                        interpretation={},
                        goal_guidance=goal_guidance,
                        write_requirements=write_requirements,
                        coverage={
                            "coverage_confirmed_this_turn": False,
                            "coverage_refresh_needed": bool(
                                stored_live_node_refs
                                or stored_expected_parameter_refs
                                or stored_expected_focus_regions
                            ),
                        },
                        warnings=warnings,
                    ),
                },
            }

        contextual_input = dict(tool_input or {})
        contextual_input["tree_name"] = tree_name

        memory, memory_meta, memory_warnings = self._load_tree_structural_memory(
            contextual_input,
            session_state=session_state,
        )
        warnings.extend(str(item) for item in memory_warnings if str(item).strip())

        params_raw = self._get_tree_parameters(tree_name)
        parameters = params_raw.get("result", {}) if params_raw.get("status") == "success" and isinstance(params_raw.get("result"), dict) else {}
        if params_raw.get("status") != "success":
            warnings.append(str(params_raw.get("error") or f"Tree parameters unavailable for '{tree_name}'."))

        phase_raw = self._classify_tree_phases(contextual_input, session_state=session_state)
        phase = phase_raw.get("result", {}) if phase_raw.get("status") == "success" and isinstance(phase_raw.get("result"), dict) else {}
        if phase_raw.get("status") != "success":
            warnings.append(str(phase_raw.get("error") or "Phase classification unavailable."))

        clinical_raw = self._map_clinical_parameter_roles(contextual_input, session_state=session_state)
        clinical_roles = clinical_raw.get("result", {}) if clinical_raw.get("status") == "success" and isinstance(clinical_raw.get("result"), dict) else {}
        if clinical_raw.get("status") != "success":
            warnings.append(str(clinical_raw.get("error") or "Clinical parameter role mapping unavailable."))

        interpretation: dict[str, Any] = {}

        blockers: list[str] = []
        if not memory:
            blockers.append("structural_memory_unavailable")
        if params_raw.get("status") != "success":
            blockers.append("tree_parameters_unavailable")
        if phase_raw.get("status") != "success":
            blockers.append("phase_classification_unavailable")

        recommended_next_step = "revise_existing_draft_using_context"
        if bool(tool_input.get("prefer_from_scratch", False)):
            recommended_next_step = "create_first_complete_draft_from_context"
        if goal_mode == "diagnose_only":
            recommended_next_step = "diagnose_current_draft_before_writing"
        elif goal_mode == "focal_correction":
            recommended_next_step = "apply_smallest_safe_correction_to_existing_draft"
        elif has_existing_draft:
            recommended_next_step = "extend_existing_draft_with_new_capability"
        if blockers:
            recommended_next_step = "collect_missing_context_before_writing"

        phase_summary = {
            "tree_phase": str(phase.get("tree_phase") or memory.get("phase_dominant") or "unknown"),
            "confidence": phase.get("confidence", {}),
            "unresolved_regions": _ta._bounded_list(phase.get("unresolved_regions", []), limit=6),
            "transition_regions": _ta._bounded_list(phase.get("transition_regions", []), limit=6),
        }
        clinical_summary = {
            "summary": clinical_roles.get("summary", {}),
            "measurement_parameters": _ta._bounded_list(clinical_roles.get("measurement_parameters", []), limit=8),
            "positioning_parameters": _ta._bounded_list(clinical_roles.get("positioning_parameters", []), limit=8),
            "likely_affected_regions": _ta._bounded_list(clinical_roles.get("likely_affected_regions", []), limit=8),
        }
        interpretation_summary = {
            "functional_summary": str(interpretation.get("functional_summary") or ""),
            "workflow_stage_summary": interpretation.get("workflow_stage_summary", {}),
            "suggested_focus_regions": _ta._bounded_list(interpretation.get("suggested_focus_regions", []), limit=8),
            "next_structural_targets": _ta._bounded_list(interpretation.get("next_structural_targets", []), limit=5),
            "organization_observations": _ta._bounded_list(interpretation.get("organization_observations", []), limit=6),
        }
        goal_guidance = self._draft_goal_guidance(
            goal_mode=goal_mode,
            clinical_roles=clinical_summary,
            interpretation=interpretation_summary,
            has_existing_draft=has_existing_draft,
        )
        coverage = self._draft_context_coverage(
            live_parameters={
                "tree": str(parameters.get("tree") or tree_name),
                "object": str(parameters.get("object") or ""),
                "modifier": str(parameters.get("modifier") or ""),
                "parameters": _ta._bounded_list(parameters.get("parameters", []), limit=16),
            } if parameters else {},
            clinical_roles=clinical_summary,
            interpretation=interpretation_summary,
            structural_memory={
                "tree_name": memory.get("tree_name", ""),
                "node_count": int(memory.get("node_count", 0) or 0),
                "frame_count": int(memory.get("frame_count", 0) or 0),
                "group_count": int(memory.get("group_count", 0) or 0),
                "phase_dominant": str(memory.get("phase_dominant") or ""),
                "organization_assessment": memory.get("organization_assessment", {}),
                "key_outputs": _ta._bounded_list(memory.get("key_outputs", []), limit=8),
                "key_joins": _ta._bounded_list(memory.get("key_joins", []), limit=8),
                "major_regions": _ta._bounded_list(memory.get("major_regions", []), limit=10),
                "parameters": memory.get("parameters", {}),
            } if memory else {},
            stored_live_node_refs=stored_live_node_refs,
            stored_expected_parameter_refs=stored_expected_parameter_refs,
            stored_expected_focus_regions=stored_expected_focus_regions,
        )
        validation_checks = [
            "Preserve the canonical GN_Agent_Draft as the single evolving draft.",
            "Keep the target tree aligned with the resolved Geometry Nodes workspace.",
            "Prefer edits that preserve already-working regions unless the user asked for a rebuild.",
            "Do not reference live nodes that do not exist in the resolved target tree.",
        ]
        if goal_mode == "diagnose_only":
            validation_checks = [
                "Do not write a new draft revision until the likely failure and smallest next fix are clear.",
                "Base the diagnosis on the resolved target tree, structural memory, and live parameter context.",
                "Keep the single canonical GN_Agent_Draft as the source of truth while diagnosing.",
            ]
        elif goal_mode == "focal_correction":
            validation_checks.append("Prefer the smallest complete correction over a broad rewrite.")
        else:
            validation_checks.append("Add the requested capability incrementally without dropping already-working regions.")
        write_requirements = {
            "goal_mode": goal_mode,
            "mode_allows_write": goal_mode != "diagnose_only",
            "resolved_target_tree": bool(tree_name),
            "structural_memory_available": bool(memory),
            "parameter_context_available": params_raw.get("status") == "success",
            "workflow_interpretation_available": False,
            "can_write_safely": not blockers and goal_mode != "diagnose_only",
            "recommended_next_step": recommended_next_step,
            "blockers": blockers,
            "validation_checks": validation_checks,
            "coverage_confirmed_this_turn": bool(coverage.get("coverage_confirmed_this_turn", False)),
            "coverage_refresh_needed": bool(coverage.get("coverage_refresh_needed", False)),
        }

        structural_memory_summary = {
            "tree_name": memory.get("tree_name", ""),
            "node_count": int(memory.get("node_count", 0) or 0),
            "frame_count": int(memory.get("frame_count", 0) or 0),
            "group_count": int(memory.get("group_count", 0) or 0),
            "phase_dominant": str(memory.get("phase_dominant") or ""),
            "organization_assessment": memory.get("organization_assessment", {}),
            "key_outputs": _ta._bounded_list(memory.get("key_outputs", []), limit=8),
            "key_joins": _ta._bounded_list(memory.get("key_joins", []), limit=8),
            "major_regions": _ta._bounded_list(memory.get("major_regions", []), limit=10),
            "parameters": memory.get("parameters", {}),
            "marker": {
                "tree_hash": str((memory.get("marker") if isinstance(memory.get("marker"), dict) else {}).get("tree_hash") or ""),
                "node_names": _ta._bounded_list(
                    (memory.get("marker") if isinstance(memory.get("marker"), dict) else {}).get("node_names", []),
                    limit=260,
                ),
                "links": _ta._bounded_list(
                    (memory.get("marker") if isinstance(memory.get("marker"), dict) else {}).get("links", []),
                    limit=80,
                ),
            },
            "freshness": memory.get("freshness", {}) if isinstance(memory.get("freshness"), dict) else {
                "snapshot_truncated": bool(memory.get("snapshot_truncated", False)),
            },
            "memory_meta": {
                "source": memory_meta.get("source", ""),
                "reused": bool(memory_meta.get("reused", False)),
                "structural_hash": str(memory.get("structural_hash") or ""),
                "built_at": str(memory.get("built_at") or ""),
            },
        } if memory else {}
        live_parameters_summary = {
            "tree": str(parameters.get("tree") or tree_name),
            "object": str(parameters.get("object") or ""),
            "modifier": str(parameters.get("modifier") or ""),
            "parameters": _ta._bounded_list(parameters.get("parameters", []), limit=16),
        } if parameters else {}
        result = {
            "goal_mode": goal_mode,
            "goal_guidance": goal_guidance,
            "tree_name": tree_name,
            "workspace": workspace,
            "structural_memory": structural_memory_summary,
            "live_parameters": live_parameters_summary,
            "phase_classification": phase_summary,
            "clinical_parameter_roles": clinical_summary,
            "orthosis_interpretation": interpretation_summary,
            "coverage": coverage,
            "write_requirements": write_requirements,
            "context_ready": not blockers,
            "warnings": warnings,
        }
        result["prompt_context"] = self._draft_context_summary(
            goal_mode=goal_mode,
            tree_name=tree_name,
            workspace=workspace,
            memory=structural_memory_summary,
            phase=phase_summary,
            clinical_roles=clinical_summary,
            interpretation=interpretation_summary,
            goal_guidance=goal_guidance,
            write_requirements=write_requirements,
            coverage=coverage,
            warnings=warnings,
        )
        return {"status": "success", "result": result}

    def _normalize_draft_goal_mode(self, value: Any) -> str:
        mode = _ta._norm_text(value)
        if mode in self._VALID_DRAFT_GOAL_MODES:
            return mode
        return "functional_expansion"

    def _workspace_candidates(self, scene: dict[str, Any], node_trees: dict[str, Any]) -> list[dict[str, Any]]:
        object_flags: dict[str, dict[str, bool]] = {}
        for obj in scene.get("objects", []):
            if not isinstance(obj, dict):
                continue
            object_flags[str(obj.get("name") or "")] = {
                "active": str(obj.get("name") or "") == str(scene.get("scene", {}).get("active_object") or ""),
                "selected": str(obj.get("name") or "") in set(scene.get("scene", {}).get("selected_objects") or []),
            }

        candidates: list[dict[str, Any]] = []
        for group in node_trees.get("node_groups", []):
            if not isinstance(group, dict):
                continue
            tree_name = _ta._norm_text(group.get("name"))
            if not tree_name:
                continue
            bindings = []
            for raw in group.get("bindings", []) if isinstance(group.get("bindings"), list) else []:
                if not isinstance(raw, dict):
                    continue
                object_name = _ta._norm_text(raw.get("object_name"))
                flags = object_flags.get(object_name, {})
                bindings.append(
                    {
                        "object_name": object_name,
                        "modifier_name": _ta._norm_text(raw.get("modifier_name")),
                        "active_object": bool(flags.get("active", False)),
                        "selected_object": bool(flags.get("selected", False)),
                        "parameter_count": len(raw.get("inputs", [])) if isinstance(raw.get("inputs"), list) else 0,
                    }
                )
            nodes = group.get("nodes", []) if isinstance(group.get("nodes"), list) else []
            candidates.append(
                {
                    "tree_name": tree_name,
                    "node_count": int(group.get("node_count", len(nodes)) or 0),
                    "frame_count": sum(1 for n in nodes if isinstance(n, dict) and n.get("type") == "NodeFrame"),
                    "group_count": sum(
                        1
                        for n in nodes
                        if isinstance(n, dict)
                        and str(n.get("type", "")).lower() in {"geometrynodegroup", "nodegroup"}
                    ),
                    "snapshot_truncated": bool(group.get("snapshot_truncated", False)),
                    "bindings": bindings,
                    "used_by_objects": list(group.get("used_by_objects", []))
                    if isinstance(group.get("used_by_objects"), list)
                    else [],
                }
            )
        return candidates

    def _resolve_gn_workspace(
        self,
        tool_input: dict[str, Any],
        *,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scene = self._capture_scene()
        node_trees = self._capture_node_trees()
        if not scene:
            return _json_error("Failed to capture scene")
        if not node_trees:
            return _json_error("Failed to capture Geometry Nodes trees")

        candidates = self._workspace_candidates(scene, node_trees)
        by_name = {item["tree_name"]: item for item in candidates}
        if not candidates:
            return {
                "status": "success",
                "result": {
                    "candidate_trees": [],
                    "selected_tree": "",
                    "selected_binding": {},
                    "selection_reason": "no_geometry_nodes_tree_found",
                    "confidence": _ta._confidence(0.0),
                    "bindings": [],
                    "explicit_user_target_detected": False,
                    "warnings": ["No Geometry Nodes tree or bound modifier was found in the scene."],
                },
            }

        state = session_state if isinstance(session_state, dict) else {}
        memory = state.get("session_memory") if isinstance(state.get("session_memory"), dict) else {}
        remembered_tree = _ta._norm_text(memory.get("target_tree") or state.get("last_target_tree"))
        message = " ".join(
            [
                _ta._norm_text(tool_input.get("user_message")),
                _ta._norm_text(tool_input.get("tree_name")),
                _ta._norm_text(tool_input.get("object_name")),
                _ta._norm_text(tool_input.get("modifier_name")),
            ]
        )
        explicit_matches = []
        for item in candidates:
            tree_name = item["tree_name"]
            binding_hit = any(
                _ta._contains_name(message, b.get("object_name", ""))
                or _ta._contains_name(message, b.get("modifier_name", ""))
                for b in item.get("bindings", [])
            )
            if _ta._contains_name(message, tree_name) or binding_hit:
                explicit_matches.append(item)
        explicit_detected = bool(explicit_matches)
        warnings: list[str] = []

        selected: dict[str, Any] | None = None
        reason = ""
        score = 0.0
        if remembered_tree and remembered_tree in by_name and (
            not explicit_detected or any(item["tree_name"] == remembered_tree for item in explicit_matches)
        ):
            selected = by_name[remembered_tree]
            reason = "session_memory_target_tree_valid"
            score = 0.88
        elif len(explicit_matches) == 1:
            selected = explicit_matches[0]
            reason = "explicit_user_target"
            score = 0.9
        elif len(explicit_matches) > 1:
            selected = explicit_matches[0]
            reason = "explicit_user_target_ambiguous_first_match"
            score = 0.55
            warnings.append("User target matched multiple GN candidates; selected the first matching tree.")
        else:
            active_or_selected = [
                item
                for item in candidates
                if any(b.get("active_object") or b.get("selected_object") for b in item.get("bindings", []))
            ]
            if len(active_or_selected) == 1:
                selected = active_or_selected[0]
                reason = "active_or_selected_object_binding"
                score = 0.78
            elif len(candidates) == 1:
                selected = candidates[0]
                reason = "single_gn_tree_fallback"
                score = 0.68
            else:
                selected = active_or_selected[0] if active_or_selected else candidates[0]
                reason = "ambiguous_fallback_first_candidate"
                score = 0.38
                warnings.append("Multiple GN trees are available and no unique target was resolved.")

        selected_binding = {}
        for binding in selected.get("bindings", []) if isinstance(selected, dict) else []:
            if binding.get("active_object") or binding.get("selected_object"):
                selected_binding = dict(binding)
                break
        if not selected_binding and isinstance(selected, dict) and selected.get("bindings"):
            selected_binding = dict(selected["bindings"][0])

        return {
            "status": "success",
            "result": {
                "candidate_trees": candidates,
                "selected_tree": selected.get("tree_name", "") if isinstance(selected, dict) else "",
                "selected_binding": selected_binding,
                "selection_reason": reason,
                "confidence": _ta._confidence(score),
                "bindings": selected.get("bindings", []) if isinstance(selected, dict) else [],
                "explicit_user_target_detected": explicit_detected,
                "warnings": warnings,
            },
        }

    def _build_tree_structural_memory(
        self,
        tool_input: dict[str, Any],
        *,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        requested_tree = _ta._norm_text(tool_input.get("tree_name"))
        resolved = self._resolve_gn_workspace(tool_input, session_state=session_state)
        if resolved.get("status") != "success":
            return resolved
        workspace = resolved.get("result", {}) if isinstance(resolved.get("result"), dict) else {}
        tree_name = requested_tree or _ta._norm_text(workspace.get("selected_tree"))
        if not tree_name:
            return _json_error("No Geometry Nodes tree resolved for structural memory build.")

        state = session_state if isinstance(session_state, dict) else {}
        memory_store = state.get("tree_structural_memory") if isinstance(state.get("tree_structural_memory"), dict) else {}
        existing = memory_store.get(tree_name) if isinstance(memory_store.get(tree_name), dict) else {}
        if existing and not bool(existing.get("stale", False)) and not bool(tool_input.get("force_refresh", False)):
            reused = dict(existing)
            freshness = dict(reused.get("freshness", {})) if isinstance(reused.get("freshness"), dict) else {}
            freshness["reused_from_session_state"] = True
            reused["freshness"] = freshness
            return {"status": "success", "result": {"workspace": workspace, "memory": reused}}

        inventory_raw = self._tool_list_tree_nodes({"tree_name": tree_name})
        if inventory_raw.get("status") != "success":
            return inventory_raw
        inventory = inventory_raw.get("result", {}) if isinstance(inventory_raw.get("result"), dict) else {}
        nodes = inventory.get("nodes", []) if isinstance(inventory.get("nodes"), list) else []

        node_trees = self._capture_node_trees()
        tree_snapshot: dict[str, Any] = {}
        for group in node_trees.get("node_groups", []) if isinstance(node_trees.get("node_groups"), list) else []:
            if isinstance(group, dict) and group.get("name") == tree_name:
                tree_snapshot = group
                break
        links = tree_snapshot.get("links", []) if isinstance(tree_snapshot.get("links"), list) else []
        interface = tree_snapshot.get("interface", {}) if isinstance(tree_snapshot.get("interface"), dict) else {}
        bindings = tree_snapshot.get("bindings", []) if isinstance(tree_snapshot.get("bindings"), list) else []
        selected_binding = workspace.get("selected_binding") if isinstance(workspace.get("selected_binding"), dict) else {}
        if not selected_binding and bindings:
            first_binding = bindings[0]
            selected_binding = {
                "object_name": first_binding.get("object_name", ""),
                "modifier_name": first_binding.get("modifier_name", ""),
            }

        frames = [n for n in nodes if _ta._node_type(n) == "NodeFrame"]
        groups = [n for n in nodes if _ta._node_type(n).lower() in {"geometrynodegroup", "nodegroup"}]
        nodes_by_frame: dict[str, list[dict[str, Any]]] = {}
        unframed = []
        for node in nodes:
            parent = _ta._norm_text(node.get("parent_frame"))
            if parent:
                nodes_by_frame.setdefault(parent, []).append(node)
            elif _ta._node_type(node) != "NodeFrame":
                unframed.append(node)

        regions: list[dict[str, Any]] = []
        for frame in frames:
            name = _ta._norm_text(frame.get("name"))
            children = nodes_by_frame.get(name, [])
            phase, phase_conf, _ = _ta._dominant_phase(children or [frame])
            regions.append(
                {
                    "name": name,
                    "label": _ta._norm_text(frame.get("label")),
                    "type": "frame",
                    "probable_function": _ta._region_function(name, children or [frame]),
                    "local_phase": phase,
                    "local_phase_confidence": phase_conf,
                    "key_nodes": [_ta._norm_text(n.get("name")) for n in children if _ta._norm_text(n.get("name"))],
                    "relation_to_other_regions": "groups_child_nodes_by_parent_frame",
                }
            )
        for group_node in groups:
            name = _ta._norm_text(group_node.get("name"))
            phase, phase_conf, _ = _ta._dominant_phase([group_node])
            regions.append(
                {
                    "name": name,
                    "label": _ta._norm_text(group_node.get("label")),
                    "type": "group",
                    "probable_function": _ta._region_function(name, [group_node]),
                    "local_phase": phase,
                    "local_phase_confidence": phase_conf,
                    "key_nodes": [name],
                    "relation_to_other_regions": "encapsulated_node_group_call",
                }
            )

        degree: dict[str, int] = {}
        for link in links:
            if not isinstance(link, dict):
                continue
            for key in ("from_node", "to_node"):
                name = _ta._norm_text(link.get(key))
                if name:
                    degree[name] = degree.get(name, 0) + 1
        high_degree = sorted(degree.items(), key=lambda item: item[1], reverse=True)[:10]
        key_joins = [
            _ta._norm_text(n.get("name"))
            for n in nodes
            if "join" in f"{n.get('name', '')} {n.get('label', '')} {_ta._node_type(n)}".lower()
        ][:12]
        key_outputs = [
            _ta._norm_text(n.get("name"))
            for n in nodes
            if "output" in f"{n.get('name', '')} {n.get('label', '')} {_ta._node_type(n)}".lower()
            or _ta._node_type(n) == "NodeGroupOutput"
        ][:12]
        phase, phase_conf, phase_scores = _ta._dominant_phase(nodes)
        marker_payload = {
            "name": tree_name,
            "nodes": nodes,
            "links": links,
            "interface": interface,
        }
        marker = self.build_tree_marker(marker_payload)
        structural_hash = self._tree_hash(marker_payload)
        params = _ta._parameter_summary(self._get_tree_parameters(tree_name))
        organization = _ta._organization_assessment(
            node_count=int(inventory.get("node_count", len(nodes)) or len(nodes)),
            frame_count=len(frames),
            group_count=len(groups),
            unframed_count=len(unframed),
        )
        hotspots = []
        if high_degree:
            hotspots.append({"type": "high_link_degree_nodes", "nodes": [{"name": n, "degree": d} for n, d in high_degree]})
        if unframed:
            hotspots.append({"type": "unframed_nodes", "count": len(unframed), "sample": [n.get("name") for n in unframed[:12]]})
        unlabeled_regions = [r["name"] for r in regions if not r.get("label")]
        if unlabeled_regions:
            hotspots.append({"type": "unlabeled_frames_or_groups", "count": len(unlabeled_regions), "sample": unlabeled_regions[:12]})

        memory = {
            "schema_version": "tree_structural_memory.v1",
            "tree_name": tree_name,
            "bound_object": selected_binding.get("object_name", ""),
            "bound_modifier": selected_binding.get("modifier_name", ""),
            "bindings": bindings,
            "node_count": int(inventory.get("node_count", len(nodes)) or len(nodes)),
            "frame_count": len(frames),
            "group_count": len(groups),
            "phase_dominant": phase,
            "phase_confidence": phase_conf,
            "phase_scores": phase_scores,
            "organization_assessment": organization,
            "key_joins": [name for name in key_joins if name],
            "key_outputs": [name for name in key_outputs if name],
            "major_regions": regions[:80],
            "structural_hotspots": hotspots,
            "parameters": params,
            "marker": marker,
            "structural_hash": structural_hash,
            "built_at": _ta._utc_now_iso(),
            "source_tools": [
                "resolve_gn_workspace",
                "list_tree_nodes",
                "get_tree_parameters",
                "capture_node_trees_snapshot_internal",
            ],
            "freshness": {
                "stale": False,
                "marker_kind": "node_names_and_link_signatures",
                "snapshot_truncated": bool(tree_snapshot.get("snapshot_truncated", False)),
            },
            "stale": False,
        }
        return {"status": "success", "result": {"workspace": workspace, "memory": memory}}

    def _load_tree_structural_memory(
        self,
        tool_input: dict[str, Any],
        *,
        session_state: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        requested_tree = _ta._norm_text(tool_input.get("tree_name"))
        state = session_state if isinstance(session_state, dict) else {}
        memory_store = state.get("tree_structural_memory") if isinstance(state.get("tree_structural_memory"), dict) else {}
        memory = memory_store.get(requested_tree) if requested_tree and isinstance(memory_store.get(requested_tree), dict) else {}
        if not memory and not requested_tree:
            memory_session = state.get("session_memory") if isinstance(state.get("session_memory"), dict) else {}
            fallback_tree = _ta._norm_text(memory_session.get("target_tree") or state.get("last_target_tree"))
            memory = memory_store.get(fallback_tree) if fallback_tree and isinstance(memory_store.get(fallback_tree), dict) else {}
        if memory and not bool(memory.get("stale", False)) and not bool(tool_input.get("force_refresh", False)):
            return dict(memory), {"source": "tree_structural_memory", "reused": True}, []

        rebuilt = self._build_tree_structural_memory(tool_input, session_state=session_state)
        if rebuilt.get("status") != "success":
            return {}, {"source": "unavailable", "reused": False}, [str(rebuilt.get("error", "Failed to load structural memory"))]
        result = rebuilt.get("result", {}) if isinstance(rebuilt.get("result"), dict) else {}
        memory = result.get("memory", {}) if isinstance(result.get("memory"), dict) else {}
        if memory and isinstance(state, dict):
            store = state.get("tree_structural_memory")
            if not isinstance(store, dict):
                store = {}
            tree_name = _ta._norm_text(memory.get("tree_name"))
            if tree_name:
                store[tree_name] = dict(memory)
                state["tree_structural_memory"] = store
        source = "rebuilt_force_refresh" if bool(tool_input.get("force_refresh", False)) else "rebuilt_missing_or_stale"
        return memory, {"source": source, "reused": False}, []

    def _classify_tree_phases(
        self,
        tool_input: dict[str, Any],
        *,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        memory, memory_meta, warnings = self._load_tree_structural_memory(tool_input, session_state=session_state)
        if not memory:
            return _json_error("Structural memory unavailable for phase classification.", warnings=warnings)

        regions = memory.get("major_regions", []) if isinstance(memory.get("major_regions"), list) else []
        local_map = [_ta._classify_region_phase(r) for r in regions if isinstance(r, dict)]
        phase_signals = _ta._semantic_phase_signals()
        text = _ta._tokenize_semantic_text(
            memory.get("tree_name"),
            " ".join(str(v) for v in memory.get("key_joins", []) if str(v).strip()),
            " ".join(str(v) for v in memory.get("key_outputs", []) if str(v).strip()),
            json.dumps(memory.get("parameters", {}), ensure_ascii=False),
            json.dumps(regions, ensure_ascii=False),
        )
        scores: dict[str, int] = {}
        evidence: list[dict[str, Any]] = []
        for phase, spec in phase_signals.items():
            matches = _ta._match_keywords(text, spec["keywords"])
            local_hits = sum(1 for r in local_map if r.get("phase") == phase)
            score = len(matches) + local_hits
            scores[phase] = score
            if score:
                evidence.append(
                    {
                        "phase": phase,
                        "signal": spec["evidence_label"],
                        "score": score,
                        "keyword_matches": matches[:16],
                        "local_region_hits": local_hits,
                    }
                )
        if not any(scores.values()):
            dominant = str(memory.get("phase_dominant") or "unknown")
            confidence = float(memory.get("phase_confidence") or 0.2)
        else:
            dominant = max(scores, key=scores.get)
            confidence = max(0.25, min(0.92, scores[dominant] / max(sum(scores.values()), 1)))
            if dominant == "phase_3":
                confidence = min(confidence, 0.65)

        transition_regions = []
        previous: dict[str, Any] | None = None
        for item in local_map:
            if previous and previous.get("phase") != item.get("phase") and "unknown" not in {previous.get("phase"), item.get("phase")}:
                transition_regions.append(
                    {
                        "from_region": previous.get("name", ""),
                        "from_phase": previous.get("phase", ""),
                        "to_region": item.get("name", ""),
                        "to_phase": item.get("phase", ""),
                        "confidence": round(min(float(previous.get("confidence", 0)), float(item.get("confidence", 0))), 2),
                    }
                )
            previous = item
        unresolved = [
            {
                "name": item.get("name", ""),
                "type": item.get("type", ""),
                "reason": "low_confidence_or_no_semantic_signal",
                "confidence": item.get("confidence", 0),
            }
            for item in local_map
            if item.get("phase") == "unknown" or float(item.get("confidence", 0)) < 0.35
        ]

        result = {
            "tree_name": memory.get("tree_name", ""),
            "tree_phase": dominant,
            "confidence": _ta._confidence(confidence),
            "phase_scores": scores,
            "phase_evidence": evidence,
            "local_phase_map": local_map,
            "transition_regions": transition_regions,
            "unresolved_regions": unresolved,
            "memory": {
                "source": memory_meta.get("source", ""),
                "reused": bool(memory_meta.get("reused", False)),
                "structural_hash": memory.get("structural_hash", ""),
                "built_at": memory.get("built_at", ""),
            },
            "warnings": warnings,
        }
        return {"status": "success", "result": result}

    def _map_clinical_parameter_roles(
        self,
        tool_input: dict[str, Any],
        *,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        memory, memory_meta, warnings = self._load_tree_structural_memory(tool_input, session_state=session_state)
        if not memory:
            return _json_error("Structural memory unavailable for parameter role mapping.", warnings=warnings)
        params = memory.get("parameters", {}) if isinstance(memory.get("parameters"), dict) else {}
        raw_params: list[dict[str, Any]] = []
        for key in ("measures", "positioning", "other"):
            values = params.get(key, []) if isinstance(params.get(key), list) else []
            raw_params.extend([dict(v) for v in values if isinstance(v, dict)])
        seen: set[str] = set()
        unique_params = []
        for param in raw_params:
            key = str(param.get("identifier") or param.get("name") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            unique_params.append(param)

        roles = [_ta._clinical_parameter_role(param) for param in unique_params]
        regions = memory.get("major_regions", []) if isinstance(memory.get("major_regions"), list) else []
        measurement = [role for role in roles if role.get("group") == "measurement"]
        positioning = [role for role in roles if role.get("group") == "positioning"]
        uncertain = [role for role in roles if role.get("group") == "uncertain"]
        affected: list[dict[str, Any]] = []
        disconnected = []
        for role in roles:
            matches = _ta._likely_regions_for_parameter(role, regions)
            affected.extend(matches)
            if not matches:
                disconnected.append(
                    {
                        "name": role.get("name", ""),
                        "role": role.get("role", ""),
                        "reason": "no_region_name_or_label_match_found",
                        "confidence": role.get("confidence", 0),
                    }
                )
        result = {
            "tree_name": memory.get("tree_name", ""),
            "measurement_parameters": measurement,
            "positioning_parameters": positioning,
            "uncertain_parameters": uncertain,
            "likely_affected_regions": affected,
            "disconnected_or_unused_parameters": disconnected,
            "summary": {
                "parameter_count": len(roles),
                "measurement_count": len(measurement),
                "positioning_count": len(positioning),
                "uncertain_count": len(uncertain),
                "note": "Unused/disconnected is heuristic: no region name/label match, not a proof of graph disconnection.",
            },
            "memory": {
                "source": memory_meta.get("source", ""),
                "reused": bool(memory_meta.get("reused", False)),
                "structural_hash": memory.get("structural_hash", ""),
                "built_at": memory.get("built_at", ""),
            },
            "warnings": warnings,
        }
        return {"status": "success", "result": result}

    def build_tree_marker(self, tree_payload: dict[str, Any]) -> dict[str, Any]:
        nodes = tree_payload.get("nodes", []) if isinstance(tree_payload, dict) else []
        links = tree_payload.get("links", []) if isinstance(tree_payload, dict) else []
        node_names = [str(node.get("name", "")).strip() for node in nodes if isinstance(node, dict)]
        node_names = sorted([name for name in node_names if name])
        link_signatures: list[str] = []
        for link in links:
            if not isinstance(link, dict):
                continue
            from_node = str(link.get("from_node", "")).strip()
            from_socket = str(link.get("from_socket", "")).strip()
            to_node = str(link.get("to_node", "")).strip()
            to_socket = str(link.get("to_socket", "")).strip()
            if from_node and to_node:
                link_signatures.append(f"{from_node}:{from_socket}->{to_node}:{to_socket}")
        link_signatures = sorted(link_signatures)
        return {
            "tree_hash": self._tree_hash(tree_payload),
            "node_names": node_names,
            "links": link_signatures,
        }

    def _get_changes_since_last_turn(
        self,
        tool_input: dict[str, Any],
        *,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = session_state if isinstance(session_state, dict) else {}
        tree_name = str(tool_input.get("tree_name", "")).strip()
        if not tree_name:
            memory = state.get("session_memory", {}) if isinstance(state.get("session_memory"), dict) else {}
            tree_name = str(memory.get("target_tree", "")).strip() or str(state.get("last_target_tree", "")).strip()
        if not tree_name:
            return _json_error("Missing tree_name and no target tree available from session memory.")

        structure = self._get_tree_structure(tree_name)
        if structure.get("status") != "success":
            return structure
        tree_payload = structure.get("result", {})
        current_marker = self.build_tree_marker(tree_payload)
        markers = state.get("tree_change_markers", {}) if isinstance(state.get("tree_change_markers"), dict) else {}
        previous_marker = markers.get(tree_name, {}) if isinstance(markers.get(tree_name), dict) else {}

        prev_nodes = set(str(v) for v in previous_marker.get("node_names", []) if str(v).strip())
        cur_nodes = set(current_marker.get("node_names", []))
        prev_links = set(str(v) for v in previous_marker.get("links", []) if str(v).strip())
        cur_links = set(current_marker.get("links", []))

        added_nodes = sorted(cur_nodes - prev_nodes)
        removed_nodes = sorted(prev_nodes - cur_nodes)
        added_links = sorted(cur_links - prev_links)
        removed_links = sorted(prev_links - cur_links)
        changed = bool(added_nodes or removed_nodes or added_links or removed_links)

        limit = max(1, min(int(tool_input.get("limit", 25) or 25), 200))

        # W1-T3: verificar se snapshot está truncado (atual ou anterior)
        # e emitir warning para que o agente saiba usar list_tree_nodes.
        snap = self._capture_node_trees()
        current_truncated = False
        for ng in snap.get("node_groups", []):
            if ng.get("name") == tree_name:
                current_truncated = bool(ng.get("snapshot_truncated", False))
                break
        prev_truncated = bool(previous_marker.get("snapshot_truncated", False))

        result: dict[str, Any] = {
            "tree_name": tree_name,
            "changed": changed,
            "added_nodes": added_nodes[:limit],
            "removed_nodes": removed_nodes[:limit],
            "added_links": added_links[:limit],
            "removed_links": removed_links[:limit],
            "changes_count": len(added_nodes) + len(removed_nodes) + len(added_links) + len(removed_links),
            "current_marker": current_marker,
            "previous_marker": previous_marker,
            "marker_available": bool(previous_marker),
        }
        if current_truncated or prev_truncated:
            result["warning"] = (
                "Change detection may miss nodes beyond snapshot cap. "
                "Run list_tree_nodes for full inventory."
            )
        return {"status": "success", "result": result}

    def _analyze_scene(self, tool_input: dict[str, Any], *, output_mode: str) -> dict[str, Any]:
        full = self._capture_full()
        scene_snapshot = full.get("scene_snapshot")
        if not scene_snapshot:
            return _json_error("Failed to capture scene snapshot for analyze_scene")
        try:
            report = self.skill_router.analyze_scene(
                scene_snapshot=scene_snapshot,
                node_trees_snapshot=full.get("node_trees_snapshot"),
                current_goal=tool_input.get("current_goal"),
                query=tool_input.get("query"),
                output_mode=tool_input.get("output_mode") or output_mode,
            )
            return {"status": "success", "result": report}
        except Exception as exc:
            return _json_error("analyze_scene failed", details=str(exc))

    def _capture_screenshot(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        max_size = int(tool_input.get("max_size", 900) or 900)
        screenshot_path = os.path.join(tempfile.gettempdir(), "blender_runtime_screenshot.png")
        code = (
            "import bpy, os, base64\n"
            f"path = r'{screenshot_path}'\n"
            f"max_size = {max_size}\n"
            "bpy.context.scene.render.filepath = path\n"
            "for area in bpy.context.screen.areas:\n"
            "    if area.type == 'VIEW_3D':\n"
            "        with bpy.context.temp_override(area=area):\n"
            "            bpy.ops.render.opengl(write_still=True)\n"
            "        break\n"
            "if os.path.exists(path):\n"
            "    with open(path, 'rb') as f:\n"
            "        data = base64.b64encode(f.read()).decode('ascii')\n"
            "    print('SCREENSHOT_BASE64:' + data)\n"
            "    os.remove(path)\n"
            "else:\n"
            "    print('ERROR: Screenshot failed')\n"
        )
        result = execution.handle_execute_code({"code": code})
        if result.get("status") != "success":
            return result
        stdout = result.get("stdout", "")
        marker = "SCREENSHOT_BASE64:"
        if marker not in stdout:
            return _json_error("Screenshot capture failed", stdout=stdout[-300:])
        image_base64 = stdout.split(marker, 1)[1].strip()
        return {"status": "success", "result": {"image_base64": image_base64}}

