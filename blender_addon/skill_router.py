"""Runtime entrypoint for analytical skills used by dispatch."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from .project_paths import canonical_project_root


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

    def analyze_gn_state(
        self,
        *,
        scene_snapshot: dict,
        node_trees_snapshot: dict | None = None,
        tree_name: str | None = None,
        current_goal: str | None = None,
        query: str | None = None,
        output_mode: str | None = "compact",
    ) -> dict[str, Any]:
        build_gn_report, _ = _import_skill_functions()
        mode = self._normalize_output_mode(output_mode)
        report = build_gn_report(
            scene_snapshot=scene_snapshot,
            node_trees_snapshot=node_trees_snapshot,
            current_goal=current_goal,
            query=query or "inspect_deep_structure",
        )

        if tree_name:
            tree_names = {tree_name}
            report["node_trees"] = [t for t in report.get("node_trees", []) if t.get("group_name") in tree_names]
            report["node_inventory"] = [n for n in report.get("node_inventory", []) if n.get("group_name") in tree_names]
            report["link_inventory"] = [l for l in report.get("link_inventory", []) if l.get("group_name") in tree_names]
            report["group_interfaces"] = [g for g in report.get("group_interfaces", []) if g.get("group_name") in tree_names]

        if mode == "verbose":
            return report
        compact = self._compact_gn_report(report)
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

    def _compact_gn_report(self, report: dict[str, Any]) -> dict[str, Any]:
        structural_flags = report.get("structural_flags", [])
        return {
            "schema_version": report.get("schema_version"),
            "context_id": report.get("context_id"),
            "query_used": report.get("query_used"),
            "gn_host_count": len(report.get("gn_hosts", [])),
            "domain_hypotheses": report.get("domain_hypotheses", [])[:8],
            "tree_summaries": [
                {
                    "group_name": t.get("group_name"),
                    "node_count": t.get("node_count", 0),
                    "link_count": t.get("link_count", 0),
                    "structural_warnings": t.get("structural_warnings", [])[:4],
                }
                for t in report.get("node_trees", [])[:8]
            ],
            "structural_flags": structural_flags[:12],
            "high_severity_flag_count": len([f for f in structural_flags if f.get("severity") == "high"]),
            "visual_capture_recommendations": report.get("visual_capture_recommendations", [])[:3],
            "follow_up_inspection_suggestions": report.get("follow_up_inspection_suggestions", [])[:5],
        }
