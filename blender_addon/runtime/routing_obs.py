"""Routing observability helpers — read-only, no effect on dispatch.

Computes two purely observational labels for every non-fast-path turn:

  session_state: str
      Inferred work state of the session, derived from ExecutionState fields
      already present in the schema.  Does NOT change any session field.

      IDLE                  — no draft, no recent failure, nothing pending
      EXPLORING             — phase=reading; agent scanning scene/GN
      DRAFTING              — phase=drafting or first draft iteration
      PENDING_USER_EXECUTION — draft written, not yet executed by user
      REPAIRING             — last execution failed; draft needs a fix
      STRATEGY_PROPOSED     — post-failure diagnosis proposed repair options
      STRATEGY_APPROVED     — user approved a proposed repair option
      RESOLVED              — last execution succeeded for current revision

  turn_intent: str
      Inferred work intent of the incoming user message, using the signal
      list already produced by TurnRouter plus a small set of soft-match
      words.  Does NOT re-run any regex from the router.

      trivial_chat          — greeting/small-talk
      pure_inquiry          — read-only analysis or question
      inquiry_then_write    — MISMATCH DETECTOR: context_inquiry chosen, but
                              message shows write intent + active draft
      draft_write           — explicit intent to create/generate a draft
      draft_refinement      — active draft + write/refinement signal
      continuation          — resume truncated response, no draft context
      feedback_fix          — execution feedback + fix intent in same message
      execution_feedback    — execution result, no fix intent yet
      state_control         — confirmation or denial of draft workflow

These labels are attached to ClassifierMeta and logged to the journal via
a ``routing_observation`` runtime event.  They do not influence routing.

``shadow_handler``:
      What handler capability-routing would choose for this turn, given
      session_state and turn_intent.  When it differs from the chosen
      turn_class, the divergence is recorded so frequency can be measured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Session state labels
# ---------------------------------------------------------------------------

SESSION_STATES = frozenset({
    "IDLE",
    "EXPLORING",
    "DRAFTING",
    "PENDING_USER_EXECUTION",
    "REPAIRING",
    "STRATEGY_PROPOSED",
    "STRATEGY_APPROVED",
    "RESOLVED",
})


def infer_session_state(session: Any) -> str:
    """Return the session work state.

    Onda 3: prefer the persisted value on ``execution_state.session_state``
    (written by the runtime at the end of the previous turn). Fall back to
    field-derived inference for sessions loaded before the field existed.
    Pure function — reads only, never writes to session.
    """
    es = getattr(session, "execution_state", None)
    if es is None:
        return "IDLE"

    persisted = str(getattr(es, "session_state", "") or "")
    if persisted in SESSION_STATES:
        return persisted

    phase = str(getattr(es, "phase", "") or "")
    current_draft = getattr(es, "current_draft", None)
    draft_revision = int(getattr(es, "draft_revision", 0) or 0)
    last_executed_revision = int(getattr(es, "last_executed_revision", 0) or 0)
    last_execution_outcome = str(getattr(es, "last_execution_outcome", "") or "")
    last_failure = getattr(es, "last_failure", None)
    retry_requires_draft_change = bool(getattr(es, "retry_requires_draft_change", False))

    active_draft = (
        current_draft is not None
        or draft_revision > 0
        or (bool(getattr(es, "drafting_mode", False)) and bool(getattr(es, "draft_block_name", "")))
    )

    # REPAIRING: execution failed and requires a draft change before retry
    if retry_requires_draft_change:
        return "REPAIRING"
    if last_execution_outcome in ("error", "failed", "failure"):
        return "REPAIRING"
    if phase == "failed":
        return "REPAIRING"
    # last_failure with a non-empty error message → still in repair state
    if last_failure is not None and str(getattr(last_failure, "error", "") or "").strip():
        return "REPAIRING"

    # RESOLVED: last execution covered the current draft revision successfully
    if (
        last_executed_revision > 0
        and last_executed_revision == draft_revision
        and last_execution_outcome in ("success", "partial", "partial_success")
    ):
        return "RESOLVED"

    # PENDING_USER_EXECUTION: draft is newer than what was last executed
    if active_draft and draft_revision > last_executed_revision:
        return "PENDING_USER_EXECUTION"

    # DRAFTING: active drafting phase (draft was not yet executed at all)
    if phase == "drafting" or (active_draft and last_executed_revision == 0):
        return "DRAFTING"

    # EXPLORING: reading phase
    if phase == "reading":
        return "EXPLORING"

    return "IDLE"


# ---------------------------------------------------------------------------
# Turn intent labels
# ---------------------------------------------------------------------------

TURN_INTENTS = frozenset({
    "trivial_chat",
    "pure_inquiry",
    "inquiry_then_write",
    "draft_write",
    "draft_refinement",
    "continuation",
    "feedback_fix",
    "execution_feedback",
    "state_control",
    "strategy_approval",
})

# Words that, together with an active draft, suggest write intent even when
# the router chose context_inquiry.  Kept minimal to avoid false positives.
_SOFT_WRITE_WORDS: tuple[str, ...] = (
    "tenta agora",
    "tenta de novo",
    "tenta denovo",
    "try again",
    "de novo agora",
    "pode tentar",
    "pode fazer",
    "agora que",
    "vê se funciona",
    "funciona agora",
    "criei o draft",
    "criou o draft",
    "já tem o draft",
    "já criei",
    "já criou",
    # --- expanded 2026-04-28: write intents without explicit keyword ---
    "reescreve", "reescrever", "reescreva",
    "fazer o script", "faz o script", "faça o script", "faca o script",
    "fazer um script", "faz um script", "faça um script",
    "pode fazer o script", "consegue fazer o script",
    "quero o draft", "quero um draft",
    "draft novo", "draft de novo", "draft denovo", "novo draft",
    "começar a escrever", "comecar a escrever",
    "começar o draft", "comecar o draft",
    "começa a escrever", "comeca a escrever",
    "consegue começar", "consegue comecar",
    "tenta consertar", "tentar consertar",
    "consertar denovo", "consertar de novo",
    "tenta arrumar", "tenta corrigir",
    "manda o script", "manda o draft",
)

# Words that together with feedback signals imply "feedback + fix intent".
_FIX_WORDS: tuple[str, ...] = (
    "corrige", "corrija", "corriger",
    "arruma", "arrume",
    "conserta", "conserte", "consertar",
    "muda", "mude",
    "altera", "altere",
    "tenta", "tente",
    "reescreve", "reescrever",
    "fix", "change", "correct", "repair", "update", "adjust",
)

# Informal markers of execution result (positive or negative). When any of
# these appears we treat the turn as execution feedback even if the router
# did not produce a feedback signal. Kept conservative — phrases must be
# unambiguous about referring to a prior execution.
_FEEDBACK_MARKERS: tuple[str, ...] = (
    # negative
    "não deu certo", "nao deu certo",
    "não deu", "nao deu",
    "não funcionou", "nao funcionou",
    "não funciona", "nao funciona",
    "não está funcionando", "nao esta funcionando",
    "deu erro", "deu pau", "deu ruim",
    "ctrl z", "ctrl+z", "dei um ctrl",
    "piorou", "regrediu", "regredimos",
    "zoou", "zuou", "bagunçou", "bagunçou tudo",
    "estamos com esse problema", "esse problema ao executar",
    "ao executar o script", "ao rodar o script",
    "script deu", "script zuou", "script zoou",
    # positive
    "agora sim", "deu certo", "funcionou agora",
    "funcionou direitinho", "perfeito agora",
    "agora foi", "deu bom",
)

# Short affirmative continuations that, when state shows active drafting work
# but the router did not emit continuation_pattern, still mean "keep going".
_SHORT_CONTINUE_PHRASES: tuple[str, ...] = (
    "continua", "continue", "continuar",
    "pode continuar",
    "segue", "siga", "segue ai", "segue aí",
    "vai", "vamo", "vamos",
    "manda ver",
    "prossegue", "prossiga",
)

# Session states where the user is reasonably expected to be working on
# the active draft (used as a discriminator for state-based fallbacks).
_ACTIVE_DRAFT_STATES: frozenset[str] = frozenset({
    "DRAFTING",
    "PENDING_USER_EXECUTION",
    "REPAIRING",
    "STRATEGY_PROPOSED",
    "STRATEGY_APPROVED",
})

# Strong, unambiguous write phrases. Even without an active draft these are
# explicit requests to produce code. Subset of _SOFT_WRITE_WORDS.
_STRONG_WRITE_PHRASES: tuple[str, ...] = (
    "reescreve", "reescrever", "reescreva",
    "fazer o script", "faz o script", "faça o script", "faca o script",
    "fazer um script", "faz um script", "faça um script",
    "pode fazer o script", "consegue fazer o script",
    "quero o draft", "quero um draft",
    "draft novo", "draft de novo", "draft denovo", "novo draft",
    "começar a escrever", "comecar a escrever",
    "começar o draft", "comecar o draft",
    "começa a escrever", "comeca a escrever",
    "consegue começar", "consegue comecar",
    "manda o script", "manda o draft",
)


def _has_active_draft_obs(session: Any) -> bool:
    """Return True if the session has an active draft (read-only helper)."""
    es = getattr(session, "execution_state", None)
    if es is None:
        return False
    if getattr(es, "current_draft", None) is not None:
        return True
    if int(getattr(es, "draft_revision", 0) or 0) > 0:
        return True
    return bool(getattr(es, "drafting_mode", False)) and bool(getattr(es, "draft_block_name", ""))


def infer_turn_intent(
    session: Any,
    message: str,
    signals: list[str],
    chosen_class: str,
) -> str:
    """Infer the work intent of the turn from router signals + session state.

    Pure function — reads only, never writes anything.
    ``chosen_class`` is the string value of the TurnClass the router selected.
    """
    msg_lower = (message or "").lower()
    active_draft = _has_active_draft_obs(session)
    session_state = infer_session_state(session)
    es = getattr(session, "execution_state", None)
    pending = getattr(es, "pending_user_decision", None) if es is not None else None
    if (
        pending is not None
        and str(getattr(pending, "status", "") or "") == "answered"
        and str(getattr(pending, "kind", "") or "") in {"strategy_choice", "repair_direction", "write_confirmation"}
    ):
        return "strategy_approval"

    # --- Trivial / state control ---
    if "greeting_pattern" in signals:
        return "trivial_chat"

    if chosen_class == "state_control" or "draft_state_control_pattern" in signals:
        return "state_control"

    # --- Execution feedback (signal-based path, original) ---
    is_feedback_signal = (
        "draft_execution_feedback_pattern" in signals
        or "draft_execution_feedback_recovery" in signals
    )

    # --- Execution feedback (informal keyword path, new 2026-04-28) ---
    # Catches messages like "não deu certo", "ctrl z", "piorou", "AGORA SIM"
    # that the router's regex set does not surface as feedback signals.
    has_feedback_marker = any(p in msg_lower for p in _FEEDBACK_MARKERS)
    is_feedback = is_feedback_signal or (
        has_feedback_marker and (active_draft or session_state in _ACTIVE_DRAFT_STATES)
    )
    # Loosened guard: even with no active draft we accept feedback markers
    # when the user explicitly references the script/execution.
    if not is_feedback and has_feedback_marker:
        if any(token in msg_lower for token in ("script", "executar", "executei", "rodar", "rodei")):
            is_feedback = True

    if is_feedback:
        has_fix_word = any(w in msg_lower for w in _FIX_WORDS)
        has_write_signal = any(s in signals for s in (
            "mutation_pattern",
            "draft_write_request_pattern",
            "draft_workspace_recovery",
            "draft_refinement_write_pattern",
        ))
        has_soft_write = any(w in msg_lower for w in _SOFT_WRITE_WORDS)
        if has_fix_word or has_write_signal or has_soft_write:
            return "feedback_fix"
        return "execution_feedback"

    # --- Explicit draft write request (signal-based) ---
    if "draft_write_request_pattern" in signals or "draft_refinement_write_pattern" in signals:
        return "draft_write"

    # --- Mutation or structured follow-up → draft_write intent ---
    if "mutation_pattern" in signals or "structured_operational_followup" in signals:
        return "draft_write"

    # --- Soft write phrases (new 2026-04-28) — write intent w/o router keyword ---
    # If the user says "reescreve", "fazer o script", "quero o draft novo", etc.
    # When the router picked context_inquiry but there is an active draft,
    # this is a routing mismatch — preserve the legacy `inquiry_then_write`
    # label so divergence accounting keeps working. Otherwise classify by state.
    has_soft_write = any(w in msg_lower for w in _SOFT_WRITE_WORDS)
    if has_soft_write:
        if chosen_class == "context_inquiry" and active_draft:
            return "inquiry_then_write"
        if active_draft or session_state in _ACTIVE_DRAFT_STATES:
            if session_state in {"REPAIRING", "STRATEGY_PROPOSED", "STRATEGY_APPROVED"}:
                return "feedback_fix"
            return "draft_refinement"
        # No active draft and no active state: treat strong write phrases
        # ("reescrever", "fazer o script", "quero o draft") as draft_write,
        # but leave the legacy ambiguous "tenta agora"/"pode tentar" set as
        # pure_inquiry to preserve the historical guard.
        if any(w in msg_lower for w in _STRONG_WRITE_PHRASES):
            return "draft_write"

    # --- Active draft + write/refinement signal → draft_refinement ---
    if "draft_workspace_recovery" in signals:
        return "draft_refinement"

    if "natural_continuation" in signals and active_draft:
        return "draft_refinement"

    if "continuation_pattern" in signals:
        return "draft_refinement" if active_draft else "continuation"

    # --- State-based short-affirmative fallback (new 2026-04-28) ---
    # "continua", "pode continuar", "segue" with no router signal but the
    # session is in an active drafting/repair state → draft_refinement.
    stripped = msg_lower.strip().rstrip("?!.")
    if session_state in _ACTIVE_DRAFT_STATES:
        if stripped in _SHORT_CONTINUE_PHRASES:
            return "draft_refinement"
        # Also catches "pode continuar", "continua ai" — short prefix match
        if any(stripped.startswith(p) for p in _SHORT_CONTINUE_PHRASES):
            if len(stripped) <= 24:
                return "draft_refinement"

    # --- MISMATCH DETECTOR: context_inquiry + active draft + soft write words ---
    # Already largely subsumed by the soft-write block above, kept as a
    # narrow safety net for the exact "active_draft + context_inquiry" case
    # without state coverage.
    if chosen_class == "context_inquiry" and active_draft:
        if any(w in msg_lower for w in _SOFT_WRITE_WORDS):
            return "inquiry_then_write"

    # --- Default: pure_inquiry ---
    return "pure_inquiry"


# ---------------------------------------------------------------------------
# Shadow handler
# ---------------------------------------------------------------------------

def compute_shadow_handler(
    turn_intent: str,
    session_state: str,
    chosen_class: str,
) -> str:
    """What handler would capability-routing choose, given intent + state?

    Returns the same value as ``chosen_class`` when there is no divergence,
    so callers can check ``shadow != chosen`` to detect mismatches.
    """
    # These intents require write_script_draft — context_inquiry cannot serve them
    write_intents = {"inquiry_then_write", "draft_write", "draft_refinement", "feedback_fix", "strategy_approval"}

    if turn_intent in write_intents and chosen_class == "context_inquiry":
        return "draft_workspace"

    # execution_feedback intent stuck on context_inquiry while a draft is
    # actually pending or under repair — the dedicated execution_feedback
    # handler is the correct destination.
    if (
        turn_intent == "execution_feedback"
        and chosen_class == "context_inquiry"
        and session_state in {"PENDING_USER_EXECUTION", "REPAIRING", "STRATEGY_PROPOSED", "STRATEGY_APPROVED"}
    ):
        return "execution_feedback"

    # Intra-handler intent miss (new 2026-04-28): chosen=draft_workspace but
    # the inferred intent is read-only / passive in a state where the user
    # clearly expects more drafting work. Surfaced via a distinct shadow
    # token so the journal's `diverges` flag captures it.
    if chosen_class == "draft_workspace" and turn_intent in {
        "pure_inquiry",
        "execution_feedback",
        "continuation",
    }:
        if session_state in {"PENDING_USER_EXECUTION", "REPAIRING", "STRATEGY_PROPOSED", "STRATEGY_APPROVED", "DRAFTING"}:
            return "draft_workspace+intent_mismatch"

    # pure_inquiry routed to draft_workspace in IDLE: may be unnecessary
    # cost but not wrong — diagnose_only goal_mode still works.

    return chosen_class


# ---------------------------------------------------------------------------
# ClassifierMeta enrichment
# ---------------------------------------------------------------------------

def enrich_meta_observability(meta: Any, session: Any, message: str) -> None:
    """Attach session_state and turn_intent to *meta* in-place.

    Called once per non-fast-path turn, inside a try/except in classify() so
    that any exception here never breaks routing.  Sets both fields; if
    derivation fails the fields remain as their default empty strings.
    """
    try:
        meta.session_state = infer_session_state(session)
    except Exception:
        meta.session_state = "IDLE"

    try:
        signals = list(getattr(meta, "signals", []) or [])
        chosen = str(getattr(getattr(meta, "turn_class", None), "value", "") or "")
        meta.turn_intent = infer_turn_intent(session, message, signals, chosen)
    except Exception:
        meta.turn_intent = "pure_inquiry"
