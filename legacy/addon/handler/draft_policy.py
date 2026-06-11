"""Draft workspace tool policy and semantic coverage helpers."""

from __future__ import annotations

import re
from typing import Any

_VALID_DRAFT_GOAL_MODES = {"diagnose_only", "focal_correction", "functional_expansion", "feedback_fix"}


def _normalize_draft_goal_mode(value: Any) -> str:
    mode = str(value or "").strip()
    if mode in _VALID_DRAFT_GOAL_MODES:
        return mode
    return "functional_expansion"


def _semantic_identity(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]+", "", text)


def _dedupe_semantic_terms(values: list[Any], *, limit: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        key = _semantic_identity(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _collect_named_terms(items: Any, *, keys: tuple[str, ...], limit: int = 8) -> list[str]:
    if not isinstance(items, list):
        return []
    collected: list[str] = []
    for item in items:
        if isinstance(item, dict):
            for key in keys:
                value = str(item.get(key) or "").strip()
                if value:
                    collected.append(value)
        else:
            value = str(item or "").strip()
            if value:
                collected.append(value)
    return _dedupe_semantic_terms(collected, limit=limit)


def _prepared_context_semantic_expectations(prepared_context: dict[str, Any]) -> tuple[list[str], list[str]]:
    prepared = prepared_context if isinstance(prepared_context, dict) else {}
    live_parameters = prepared.get("live_parameters", {}) if isinstance(prepared.get("live_parameters"), dict) else {}
    clinical = prepared.get("clinical_parameter_roles", {}) if isinstance(prepared.get("clinical_parameter_roles"), dict) else {}
    interpretation = prepared.get("orthosis_interpretation", {}) if isinstance(prepared.get("orthosis_interpretation"), dict) else {}
    structural = prepared.get("structural_memory", {}) if isinstance(prepared.get("structural_memory"), dict) else {}
    phase = prepared.get("phase_classification", {}) if isinstance(prepared.get("phase_classification"), dict) else {}

    parameter_terms = _dedupe_semantic_terms(
        _collect_named_terms(live_parameters.get("parameters", []), keys=("name", "identifier"), limit=12)
        + _collect_named_terms(clinical.get("measurement_parameters", []), keys=("name", "identifier", "role"), limit=12)
        + _collect_named_terms(clinical.get("positioning_parameters", []), keys=("name", "identifier", "role"), limit=12),
        limit=10,
    )
    region_terms = _dedupe_semantic_terms(
        _collect_named_terms(interpretation.get("suggested_focus_regions", []), keys=("region", "name", "label"), limit=12)
        + _collect_named_terms(clinical.get("likely_affected_regions", []), keys=("region", "name", "label"), limit=12)
        + _collect_named_terms(structural.get("major_regions", []), keys=("name", "label", "probable_function"), limit=12)
        + _collect_named_terms(phase.get("transition_regions", []), keys=("region", "name", "label"), limit=12),
        limit=10,
    )
    return parameter_terms, _filter_actionable_focus_regions(region_terms)


def _filter_actionable_focus_regions(regions: list[str]) -> list[str]:
    actionable: list[str] = []
    for item in regions or []:
        text = str(item or "").strip()
        lowered = text.lower()
        if not text:
            continue
        if lowered == "frame" or re.fullmatch(r"frame(?:\.\d+)?", lowered):
            continue
        if lowered in {"unknown_structural_region", "geometry_join_or_assembly_region"}:
            continue
        actionable.append(text)
    return _dedupe_semantic_terms(actionable, limit=10)


def _draft_coverage_refresh_status(
    *,
    prepared_context: dict[str, Any] | None,
    structural_memory: dict[str, Any] | None,
    stored_expected_parameter_refs: list[str] | None = None,
    stored_expected_focus_regions: list[str] | None = None,
    stored_live_node_refs: list[str] | None = None,
) -> dict[str, Any]:
    confirmed_parameter_refs, confirmed_focus_regions = _prepared_context_semantic_expectations(
        prepared_context if isinstance(prepared_context, dict) else {}
    )
    persisted_parameter_refs = [
        str(item).strip()
        for item in (stored_expected_parameter_refs or [])
        if str(item).strip()
    ][:10]
    persisted_focus_regions = _filter_actionable_focus_regions([
        str(item).strip()
        for item in (stored_expected_focus_regions or [])
        if str(item).strip()
    ])[:10]
    persisted_live_refs = [
        str(item).strip()
        for item in (stored_live_node_refs or [])
        if str(item).strip()
    ][:8]
    has_persisted_semantic_memory = bool(
        persisted_parameter_refs or persisted_focus_regions or persisted_live_refs
    )
    has_confirmed_semantic_memory = bool(
        confirmed_parameter_refs or confirmed_focus_regions
    )
    coverage_refresh_needed = bool(
        has_persisted_semantic_memory
        and not has_confirmed_semantic_memory
        and not bool(structural_memory)
    )
    return {
        "confirmed_parameter_refs": confirmed_parameter_refs,
        "confirmed_focus_regions": confirmed_focus_regions,
        "persisted_parameter_refs": persisted_parameter_refs,
        "persisted_focus_regions": persisted_focus_regions,
        "persisted_live_refs": persisted_live_refs,
        "has_persisted_semantic_memory": has_persisted_semantic_memory,
        "has_confirmed_semantic_memory": has_confirmed_semantic_memory,
        "coverage_refresh_needed": coverage_refresh_needed,
    }


def _fallback_goal_guidance(goal_mode: str) -> dict[str, Any]:
    mode = _normalize_draft_goal_mode(goal_mode)
    if mode == "diagnose_only":
        return {
            "summary": "Diagnose the current living draft before proposing a rewrite.",
            "suggested_output": "analysis_with_likely_failure_and_smallest_next_fix",
            "focus_priorities": [],
        }
    if mode == "focal_correction":
        return {
            "summary": "Apply the smallest safe correction to the current living draft.",
            "suggested_output": "single_targeted_revision",
            "focus_priorities": [],
        }
    if mode == "feedback_fix":
        return {
            "summary": "Fix the current living draft using the latest execution feedback.",
            "suggested_output": "single_feedback_driven_revision",
            "focus_priorities": [],
        }
    return {
        "summary": "Extend the same living draft incrementally without regressing existing capabilities.",
        "suggested_output": "incremental_feature_expansion",
        "focus_priorities": [],
    }


def _draft_workspace_tool_policy(
    *,
    tree_name_hint: str,
    structural_memory: dict,
    relevant_nodes: list[Any],
    economy_retry: bool,
    has_existing_draft_content: bool,
    prepared_context: dict[str, Any] | None = None,
    edit_mode: str = "preserve_and_refine",
    goal_mode: str = "functional_expansion",
    stored_goal_guidance: dict[str, Any] | None = None,
    stored_expected_parameter_refs: list[str] | None = None,
    stored_expected_focus_regions: list[str] | None = None,
    stored_live_node_refs: list[str] | None = None,
) -> dict[str, Any]:
    prepared = prepared_context if isinstance(prepared_context, dict) else {}
    write_requirements = prepared.get("write_requirements", {}) if isinstance(prepared.get("write_requirements"), dict) else {}
    coverage_status = _draft_coverage_refresh_status(
        prepared_context=prepared,
        structural_memory=structural_memory,
        stored_expected_parameter_refs=stored_expected_parameter_refs,
        stored_expected_focus_regions=stored_expected_focus_regions,
        stored_live_node_refs=stored_live_node_refs,
    )
    expected_parameter_refs = list(coverage_status.get("confirmed_parameter_refs", []))
    expected_focus_regions = list(coverage_status.get("confirmed_focus_regions", []))
    if not expected_parameter_refs:
        expected_parameter_refs = list(coverage_status.get("persisted_parameter_refs", []))
    if not expected_focus_regions:
        expected_focus_regions = list(coverage_status.get("persisted_focus_regions", []))
    goal_guidance = prepared.get("goal_guidance", {}) if isinstance(prepared.get("goal_guidance"), dict) else {}
    if not goal_guidance:
        if isinstance(stored_goal_guidance, dict) and stored_goal_guidance:
            goal_guidance = dict(stored_goal_guidance)
        else:
            goal_guidance = _fallback_goal_guidance(goal_mode)
    prepared_blockers = write_requirements.get("blockers", []) if isinstance(write_requirements.get("blockers"), list) else []
    persisted_live_refs = list(coverage_status.get("persisted_live_refs", []))
    coverage_has_semantic_memory = bool(expected_parameter_refs or expected_focus_regions or persisted_live_refs)
    economy_retry_focal_budget = 3 if bool(economy_retry) else 0
    enforced_prepared_blockers = [
        str(item).strip()
        for item in prepared_blockers
        if str(item).strip() in {
            "target_tree_unresolved",
            "structural_memory_unavailable",
            "tree_parameters_unavailable",
        }
    ]
    mode = _normalize_draft_goal_mode(goal_mode)
    return {
        "turn_class": "draft_workspace",
        "write_allowed": mode != "diagnose_only",
        "tree_name": tree_name_hint,
        "fresh_structural_memory": bool(structural_memory),
        "workspace_resolution_budget": 1 if not tree_name_hint else 0,
        "workspace_resolution_used": 0,
        "recovery_structural_budget": 1,
        "recovery_structural_used": 0,
        "focal_budget": economy_retry_focal_budget if economy_retry else (4 if not tree_name_hint and not relevant_nodes else 3),
        "focal_used": 0,
        "economy_retry": bool(economy_retry),
        "coverage_has_semantic_memory": coverage_has_semantic_memory,
        "coverage_confirmed_this_turn": bool(coverage_status.get("has_confirmed_semantic_memory")),
        "coverage_refresh_needed": bool(coverage_status.get("coverage_refresh_needed")),
        "economy_retry_focal_budget": economy_retry_focal_budget,
        "existing_draft_loaded": bool(has_existing_draft_content),
        "edit_mode": str(edit_mode or "preserve_and_refine"),
        "goal_mode": mode,
        "goal_guidance": goal_guidance,
        "require_read_before_write": mode != "functional_expansion",
        "allow_write_when_source_missing": (
            (not has_existing_draft_content and not economy_retry)
            or mode == "functional_expansion"
        ),
        "require_target_tree_for_write": (
            not has_existing_draft_content
            and mode != "functional_expansion"
        ),
        "require_structural_memory_for_write": mode != "diagnose_only",
        "require_context_evidence_for_write": bool(
            not has_existing_draft_content
            and not bool(write_requirements.get("can_write_safely", False))
            and mode != "functional_expansion"
        ),
        "require_prepared_context_for_write": bool(prepared) and not economy_retry and mode != "functional_expansion",
        "prepared_context_pre_read": bool(prepared) and not economy_retry,
        "block_when_prepared_context_has_blockers": (
            bool(enforced_prepared_blockers)
            and not economy_retry
            and mode != "functional_expansion"
        ),
        "prepared_context_blockers": enforced_prepared_blockers,
        "expected_parameter_refs": expected_parameter_refs,
        "expected_focus_regions": expected_focus_regions,
    }
