"""Compact system-prompt builder for Phase 3 of REFATOR_PLAN.md.

Replaces the 4×1400 + 4×1200 token knowledge dump in
``context_prompt.build_system_prompt`` (item 18 of the "Do Not Preserve"
list) with a focused, budgeted prompt that is assembled from the session
state and a small retrieved knowledge bundle.

Token budget (§9.4 of REFATOR_PLAN.md):
    Base role block:           ~250 tokens
    Focus + baseline block:    ~200 tokens
    Knowledge bundle:          ≤1000 tokens (caller supplies)
    Turn-class guidance:       ~100 tokens
    Total target:              ≤1550 tokens

The builder never loads knowledge itself — the caller passes a pre-selected
``knowledge`` list (each item is a dict with ``title`` and ``content`` keys).
Knowledge retrieval lives in Phase 6 (``knowledge/retriever.py``).  For
Phase 3, callers either pass an empty list (simplest) or reuse the existing
``context_knowledge`` helpers while those are still present.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_renderer import render_compact_tree


# ---------------------------------------------------------------------------
# Base role block (invariant across turn classes)
# ---------------------------------------------------------------------------

_BASE_ROLE = """\
You are a Blender Geometry Nodes copilot.
Your job is to help the user understand, diagnose, and modify a Geometry Nodes
modifier tree inside Blender.

Core rules:
- Prefer the minimum change needed.
- Generated Python belongs in Blender's Text Editor draft, not in chat.
- The user manually runs drafts; never autoexecute draft code.
- Explain draft changes in concise status language.
- You always have a live connection to Blender via the available tools.
  If you have no tree in focus, call ``get_scene_summary`` or ``get_gn_hosts``
  to discover the current state before answering — never assume disconnection.\
"""

# Turn-class-specific guidance blocks for the live draft-first product.
_TURN_GUIDANCE: dict[str, str] = {
    "trivial_chat": "Respond briefly and conversationally. No tool calls needed.",
    "context_inquiry": (
        "Answer using concise prose. Use structured read/context tools only when needed. "
        "Do not call make_plan, execute_code, or write_script_draft."
    ),
    "draft_workspace": (
        "Unified draft workspace. Read the current Text Editor draft first when changing or diagnosing code, "
        "then save complete revised Python with write_script_draft. Do not call make_plan or execute_code. "
        "Do not put full code in chat."
    ),
    "execution_feedback": (
        "Record the user's manual execution outcome. Do not call make_plan or execute_code. "
        "If the result was wrong, had no visible effect, or was reverted, diagnose and propose options first; "
        "do not write a revised draft until the user explicitly approves a path."
    ),
    "state_control": "Handle draft workflow control concisely. Do not execute or plan anything.",
}

POST_FAILURE_DIAGNOSIS_CONTRACT = """\
[Repair conversation guidance]
Respond in natural, conversational Brazilian Portuguese — no sections, no headers, no bullet lists.
Do not call tools, do not rewrite code, and do not include code fences.
Use the user's symptom and the Failed draft static evidence (if present) to state the most likely cause briefly, in prose.
If concrete node or socket names are available in the evidence, mention them naturally.
Do not ask the user to confirm anything about the tree — you can read the tree yourself with tools when you write the next revision.
End with one short sentence asking whether you should proceed with the fix.
If screenshots are attached, look at them first.
"""

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_system_prompt(
    session: Any,
    turn_class: str,
    knowledge: list[dict[str, Any]] | None = None,
) -> str:
    """Return a compact system prompt for the given turn.

    Args:
        session:    v1 Session.
        turn_class: One of the live draft-first TurnClass string values.
        knowledge:  Pre-selected knowledge items
                    (``[{"title": str, "content": str}, ...]``).
                    Pass ``[]`` or ``None`` to skip.
    """
    sections: list[str] = [_BASE_ROLE]

    # --- focus + baseline block ---
    focus_block = _build_focus_block(session)
    if focus_block:
        sections.append(focus_block)

    # --- history hint (recent failure / pending state) ---
    hint = _build_state_hint(session)
    if hint:
        sections.append(hint)

    # --- turn-class guidance ---
    guidance = _TURN_GUIDANCE.get(turn_class, "")
    if guidance:
        sections.append(f"This turn: {guidance}")

    # --- knowledge bundle ---
    if knowledge:
        bundle = _render_knowledge(knowledge)
        if bundle:
            sections.append(bundle)

    return "\n\n".join(sections)


def build_post_failure_diagnosis_contract() -> str:
    """Return repair conversation guidance for post-failure diagnosis turns."""
    return POST_FAILURE_DIAGNOSIS_CONTRACT


def _build_focus_block(session: Any) -> str:
    """Return a short description of the current focus and baseline state."""
    focus = getattr(session, "focus", None)
    baseline = getattr(session, "baseline_workspace", None)

    parts: list[str] = []

    tree_name = getattr(focus, "tree_name", "") if focus else ""
    if tree_name:
        parts.append(f"Focused GN modifier: {tree_name}")

    blend_path = ""
    if focus:
        blend_path = getattr(focus, "blend_path", "") or ""
    if not blend_path:
        identity = getattr(session, "identity", None)
        if identity:
            blend_path = getattr(identity, "blend_path", "") or ""
    if blend_path and not blend_path.startswith("__untitled__"):
        # Only show the filename, not the full path.
        parts.append(f"File: {Path(blend_path).name}")
    elif blend_path.startswith("__untitled__"):
        parts.append("File: (arquivo não salvo)")

    if baseline:
        stale = getattr(baseline, "stale", False)
        summary = getattr(baseline, "structural_summary", "") or ""
        if stale:
            parts.append("Baseline: stale (refresh recommended).")
        elif summary:
            # Compact 1-line summary — structural_summary may be a dict or a string.
            if isinstance(summary, dict):
                rendered = render_compact_tree(summary, max_chars=3000)
                if rendered:
                    parts.append(rendered)
                    return "\n".join(parts) if parts else ""
                import json
                summary_str = json.dumps(summary, ensure_ascii=False)
            else:
                summary_str = str(summary)
            first_line = summary_str.split("\n")[0].strip()
            if first_line:
                parts.append(f"Baseline summary: {first_line[:200]}")

    return "\n".join(parts) if parts else ""


def _build_state_hint(session: Any) -> str:
    """Return a one-line hint about the current execution state."""
    es = getattr(session, "execution_state", None)
    if es is None:
        return ""
    phase = getattr(es, "phase", "idle")
    draft = getattr(es, "current_draft", None)
    draft_revision = int(getattr(es, "draft_revision", 0) or getattr(draft, "version", 0) or 0)
    if draft_revision:
        block_name = str(getattr(es, "draft_block_name", "") or getattr(draft, "block_name", "") or "GN_Agent_Draft")
        outcome = str(getattr(es, "last_execution_outcome", "") or "")
        retry = bool(getattr(es, "retry_requires_draft_change", False))
        reverted = bool(getattr(es, "scene_reverted_by_user", False))
        parts = [f"Draft: {block_name} rev {draft_revision}"]
        if outcome:
            parts.append(f"last outcome: {outcome}")
        if retry:
            parts.append("retry requires draft modification")
        if reverted:
            parts.append("scene may have been reverted by user")
        return "State: " + "; ".join(parts) + "."
    return ""


def _render_knowledge(items: list[dict[str, Any]]) -> str:
    """Render a list of knowledge items into a compact section."""
    if not items:
        return ""
    lines = ["Relevant knowledge:"]
    for item in items:
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        if title:
            lines.append(f"### {title}")
        lines.append(content[:600])  # hard cap per item
    return "\n".join(lines) if len(lines) > 1 else ""


