"""Post-execution feedback handling for script drafts."""

from __future__ import annotations

from typing import Any

from . import HandlerResult, TurnContext
from .draft_context import _compact_structural_memory, _prepare_structural_memory
from .draft_runtime import _replace_last_assistant_message
from .draft_response import _brief_chat_summary
from .draft_state import _sync_draft_metadata_from_read, _target_tree_for_draft
from .feedback_evidence import (
    _extract_failed_draft_static_evidence,
    _fallback_post_failure_diagnosis,
    _minimum_useful_analysis_response,
    _post_failure_quality_status,
    _read_draft_info,
    _read_failed_draft_info,
    _render_failed_draft_evidence_pack,
)
from .feedback_classifier import _EXECUTION_DIAGNOSIS_RE, _classify_execution_feedback
from .prompt import build_post_failure_diagnosis_contract
from ..runtime.pending_decision import set_pending_decision

__all__ = [
    "handle",
    "handle_execution_feedback",
    "_classify_execution_feedback",
    "_extract_failed_draft_static_evidence",
    "_fallback_post_failure_diagnosis",
    "_minimum_useful_analysis_response",
]


def handle(ctx: TurnContext) -> HandlerResult:
    """Record manual draft execution feedback without executing or writing.

    This is the deliberate collaboration checkpoint after a failed draft: capture
    the user's feedback, diagnose the failed revision, and set a pending decision
    before any new draft can be written.
    """
    session = ctx.session
    es = session.execution_state
    draft = getattr(es, "current_draft", None)
    block_name = str(
        getattr(draft, "block_name", "")
        or getattr(es, "draft_block_name", "")
        or "GN_Agent_Draft"
    )
    tree_name_hint = _target_tree_for_draft(ctx, draft)
    _system, structural_memory = _prepare_structural_memory(ctx, tree_name_hint)
    current_revision = int(
        getattr(draft, "version", 0)
        or getattr(es, "draft_revision", 0)
        or getattr(es, "current_revision", 0)
        or 0
    )
    if current_revision <= 0:
        info = _read_draft_info(ctx, block_name)
        current_revision = int(info.get("version") or 0)
        if info:
            draft = _sync_draft_metadata_from_read(ctx, block_name, info)
            if draft:
                current_revision = draft.version

    outcome, reverted = _classify_execution_feedback(ctx.message)
    bad_outcomes = {"executed_no_effect", "executed_failed", "executed_partial_failure", "reverted_by_user"}

    es.last_executed_revision = current_revision
    es.last_execution_outcome = outcome
    es.last_execution_notes = str(ctx.message or "")[:500]
    es.scene_reverted_by_user = bool(reverted)
    es.retry_requires_draft_change = outcome in bad_outcomes
    es.draft_block_name = block_name
    if outcome in bad_outcomes:
        es.last_failed_revision = current_revision
    if draft is not None:
        es.draft_revision = int(getattr(draft, "version", current_revision) or current_revision)
        es.draft_target_tree = str(getattr(draft, "tree_name", "") or getattr(es, "draft_target_tree", ""))
        es.last_saved_char_count = int(getattr(draft, "last_written_chars", 0) or getattr(es, "last_saved_char_count", 0))

    baseline = getattr(session, "baseline_workspace", None)
    if baseline is not None and outcome == "executed":
        baseline.stale = True

    try:
        if session.execution_state.phase != "drafting":
            session.execution_state.set_phase("drafting")
    except Exception:
        pass

    ctx.log_event(
        "script_draft_execution_feedback",
        {
            "block_name": block_name,
            "draft_revision": current_revision,
            "outcome": outcome,
            "scene_reverted_by_user": bool(reverted),
            "retry_requires_draft_change": bool(es.retry_requires_draft_change),
        },
    )

    diagnosis = ""
    failed_draft_source = ""
    failed_draft_archive_path = ""
    diagnosis_contract_satisfied = False
    diagnosis_used_fallback = False
    diagnosis_missing_sections: list[str] = []
    diagnosis_strategy_count = 0
    failed_draft_evidence: dict[str, Any] = {}
    failed_draft_evidence_pack = ""
    wants_diagnosis = (
        outcome in bad_outcomes
        or bool(_EXECUTION_DIAGNOSIS_RE.search(ctx.message or ""))
        or "?" in str(ctx.message or "")
    )
    if wants_diagnosis:
        info = _read_failed_draft_info(ctx, block_name=block_name, revision=current_revision)
        content = str(info.get("content") or "")
        if content.strip():
            failed_draft_source = str(info.get("source") or "")
            failed_draft_archive_path = str(info.get("draft_archive_path") or "")
            current_revision = int(info.get("version") or current_revision or 0)
            es.last_executed_revision = current_revision
            if outcome in bad_outcomes:
                es.last_failed_revision = current_revision
            if failed_draft_source != "draft_history":
                _sync_draft_metadata_from_read(ctx, block_name, info)
            failed_draft_evidence = _extract_failed_draft_static_evidence(content, structural_memory)
            failed_draft_evidence_pack = _render_failed_draft_evidence_pack(failed_draft_evidence)
            prompt = (
                f"User feedback: {ctx.message}\n"
                f"Recorded outcome: {outcome}\n"
                f"Draft revision: {current_revision}\n"
                f"Draft source used for diagnosis: {failed_draft_source or 'unknown'}\n"
                f"Scene reverted/restored: {bool(reverted)}\n"
                f"Attached screenshots: {len(ctx.image_blocks)}\n"
                f"Attached text/file context blocks: {len(ctx.attachment_text_blocks)}\n"
                f"Structural memory:\n{_compact_structural_memory(structural_memory, max_chars=1200)}\n\n"
                f"{failed_draft_evidence_pack}\n\n"
                f"Failed draft content:\n```python\n{content[:9000]}\n```\n\n"
                f"{build_post_failure_diagnosis_contract()}\n"
                "Use at least one concrete item from 'Failed draft static evidence' when available."
            )
            diagnosis_content: list[Any] = []
            if ctx.attachment_text_blocks:
                diagnosis_content.extend(ctx.attachment_text_blocks)
            if ctx.image_blocks:
                diagnosis_content.extend(ctx.image_blocks)
            diagnosis_content.append({"type": "text", "text": prompt})
            try:
                diagnosis = ctx.request_text(
                    system=(
                        "You diagnose Blender Python draft failures using the current draft, "
                        "last execution feedback, and structural memory. Preserve the user's biomechanical goal, "
                        "especially palm/metacarpal/phalange relationships, and separate evidence from hypothesis. "
                        "When screenshots are present, explicitly use visible error text before forming hypotheses. "
                        "Never call tools and never write a revised draft in this turn. "
                        "Be concise and do not include code fences or raw code snippets in chat."
                    ),
                    messages=[
                        {
                            "role": "user",
                            "content": diagnosis_content if len(diagnosis_content) > 1 else prompt,
                        }
                    ],
                    max_tokens=2200,
                ).strip()
            except Exception:
                diagnosis = ""
            diagnosis_contract_satisfied, diagnosis_missing_sections, diagnosis_strategy_count = _post_failure_quality_status(diagnosis, failed_draft_evidence)
            if not diagnosis_contract_satisfied:
                diagnosis_used_fallback = True
                diagnosis = _fallback_post_failure_diagnosis(
                    block_name=block_name,
                    revision=current_revision,
                    content=content,
                    outcome=outcome,
                    notes=str(ctx.message or ""),
                    structural_memory=structural_memory,
                    failed_draft_source=failed_draft_source,
                    reverted=bool(reverted),
                    evidence_pack_text=failed_draft_evidence_pack,
                    evidence=failed_draft_evidence,
                )
                diagnosis_contract_satisfied, diagnosis_missing_sections, diagnosis_strategy_count = _post_failure_quality_status(diagnosis, failed_draft_evidence)
            if diagnosis_contract_satisfied:
                es.post_failure_state = "STRATEGY_PROPOSED"
                es.session_state = "STRATEGY_PROPOSED"
                es.proposed_strategy_count = int(diagnosis_strategy_count)
                es.proposed_strategy_revision = int(current_revision or 0)
                es.approved_strategy_label = ""
                es.approved_strategy_prompt = ""
                use_ab = diagnosis_strategy_count >= 2
                if use_ab:
                    decision_options = ["A", "B"]
                    decision_kind = "strategy_choice"
                    decision_summary = "Qual caminho voce aprova para a proxima revisao, A ou B?"
                else:
                    # No A/B split (count 0 or 1). A bare ["sim", "não"] is redundant —
                    # upstream `_is_clear_denial` already cancels on "não". Use a single
                    # positive option so `_match_option`'s single-positive path accepts
                    # any affirmative ("ok", "pode", "segue") or strategy phrase
                    # ("seguir", "essa direção") without forcing the user to guess
                    # between "sim" and "não".
                    decision_options = ["sim"]
                    decision_kind = "repair_direction"
                    decision_summary = "Confirmar direção de reparo antes da próxima revisão."
                set_pending_decision(
                    ctx,
                    kind=decision_kind,
                    options=decision_options,
                    prompt_summary=decision_summary,
                    source_revision=int(current_revision or 0),
                    related_failure=outcome,
                )
            else:
                es.post_failure_state = "DIAGNOSING"
        ctx.log_event(
            "script_draft_execution_diagnosis",
            {
                "block_name": block_name,
                "draft_revision": current_revision,
                "diagnosis_requested": True,
                "diagnosis_generated": bool(diagnosis),
                "used_structural_memory": bool(structural_memory),
                "failed_draft_source": failed_draft_source,
                "failed_draft_archive_path": failed_draft_archive_path,
                "image_blocks_count": len(ctx.image_blocks),
                "attachment_text_blocks_count": len(ctx.attachment_text_blocks),
                "used_image_context": bool(ctx.image_blocks),
                "diagnosis_contract_satisfied": bool(diagnosis_contract_satisfied),
                "diagnosis_used_fallback": bool(diagnosis_used_fallback),
                "diagnosis_missing_sections": diagnosis_missing_sections,
                "diagnosis_strategy_count": diagnosis_strategy_count,
                "post_failure_state": str(getattr(es, "post_failure_state", "") or ""),
                "proposed_strategy_revision": int(getattr(es, "proposed_strategy_revision", 0) or 0),
                "static_evidence_available": bool(failed_draft_evidence_pack),
                "static_evidence_touched_nodes": failed_draft_evidence.get("touched_nodes", []) if isinstance(failed_draft_evidence, dict) else [],
                "static_evidence_mismatches": failed_draft_evidence.get("semantic_mismatches", []) if isinstance(failed_draft_evidence, dict) else [],
            },
        )

    if outcome == "executed":
        response = (
            f"Script v{current_revision} executado com sucesso. "
            "Se algo ficou fora do esperado me diga; caso contrário podemos seguir para a próxima funcionalidade."
        )
    else:
        response = f"Registrei o resultado: falha da revisão {current_revision} de **{block_name}**."
        if reverted:
            response += " Cena revertida."

    if diagnosis:
        response += "\n\nDiagnóstico:\n" + _brief_chat_summary(diagnosis, max_chars=2600)

    if outcome in bad_outcomes:
        es.draft_edit_mode = "preserve_and_refine"
        if not diagnosis:
            response += (
                "\n\nMe conta mais sobre o que aconteceu ou o que deveria ter funcionado; "
                "assim chegamos juntos ao melhor caminho antes de reescrever."
            )
        else:
            response += (
                "\n\nMe confirma a direção ou me dá um ajuste explícito; "
                "só vou escrever uma nova revisão depois dessa confirmação."
            )

    _replace_last_assistant_message(ctx._runtime, response)
    return HandlerResult(
        response_text=response,
        phase_transition="drafting",
        session_mutations=[{"type": "script_draft_execution_feedback", "outcome": outcome}],
    )


handle_execution_feedback = handle
