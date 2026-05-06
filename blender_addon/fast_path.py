"""Fast paths for deterministic resolution without LLM.

Intercepts specific message patterns BEFORE the TurnRouter and returns a
response string without any API call (or with exactly one direct tool call).

Entry point
-----------
    try_fast_path(message, *, session, runtime) -> tuple[str, dict] | None

Returns ``(response_text, metadata)`` when handled, ``None`` to fall through.
The metadata dict always contains at least ``fp_type`` (one of
``"greeting"``, ``"help"``, ``"read"``, ``"draft_confirmation"``).
Read hits also carry ``"node"``.

Contract
--------
- Returns None to fall through to normal flow on any doubt.
- Reads fall through on error (never return an error string).
- Any uncaught exception falls through silently (call site wraps in try/except).

Fast paths
----------
1. Greetings / small talk  — canned replies, zero cost.
2. Help                    — static capability text, zero cost.
3. Simple reads            — one get_node_context call, no LLM.
4. Draft confirmation      — present pending draft for manual execution, zero LLM, zero tools.
"""

from __future__ import annotations

import json
import re
from typing import Any


# ---------------------------------------------------------------------------
# Fast path 1: Greetings / small talk
# ---------------------------------------------------------------------------

_GREETING_REPLIES: dict[str, str] = {
    "oi":          "Oi! Como posso ajudar?",
    "olá":         "Olá! Como posso ajudar com seu projeto de nós de geometria?",
    "ola":         "Olá! Como posso ajudar?",
    "hi":          "Hi! How can I help with your Geometry Nodes project?",
    "hey":         "Hey! Ready to work on some nodes.",
    "hello":       "Hello! How can I help with your Geometry Nodes project?",
    "obrigado":    "De nada! Se precisar de mais alguma coisa é só falar.",
    "obrigada":    "De nada! Se precisar de mais alguma coisa é só falar.",
    "thanks":      "You're welcome! Let me know if you need anything else.",
    "thank you":   "You're welcome! Let me know if you need anything else.",
    "valeu":       "Por nada! Pode perguntar o que quiser.",
    "bom dia":     "Bom dia! Como posso ajudar?",
    "boa tarde":   "Boa tarde! Como posso ajudar?",
    "boa noite":   "Boa noite! Como posso ajudar?",
    "tudo bem":    "Tudo bem! Como posso ajudar?",
    "tudo bom":    "Tudo bem! Como posso ajudar?",
    "ok":          "Entendido! Se precisar de mais alguma coisa é só falar.",
    "certo":       "Certo! Pode perguntar o que quiser.",
    "perfeito":    "Perfeito! Pode continuar.",
    "entendido":   "Ótimo! Como posso ajudar?",
}

_AMBIGUOUS_GREETING_TOKENS = {"ok", "certo", "perfeito", "entendido"}
_WORK_CONTEXT_RE = re.compile(
    r"\b("
    r"script|c[oó]digo|python|bpy|execute_code|socket|painel|panel|interface|"
    r"geometry\s+nodes|node|blender|erro|falhou|truncad|executar|rodar|"
    r"adicion|criar|alterar|modificar|input|output"
    r")\b",
    re.IGNORECASE,
)

# Fullmatch patterns on the cleaned (lowered, rstripped) message.
# Only covers multi-word combos not reachable via the dict above.
_GREETING_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"oi\s*,?\s*tudo\s*(bem|bom)\??"),
     "Oi! Tudo bem! Como posso ajudar?"),
    (re.compile(r"ol[aá]\s*,?\s*tudo\s*(bem|bom)\??"),
     "Olá! Tudo bem! Como posso ajudar?"),
]


def _recent_history_texts(session: Any, limit: int = 6) -> list[str]:
    history = getattr(getattr(session, "history", None), "messages", []) or []
    texts: list[str] = []
    for item in history[-limit:]:
        content = str(getattr(item, "content", "") or "").strip()
        if content:
            texts.append(content)
    return texts


def _has_recent_work_context(session: Any) -> bool:
    joined = "\n".join(_recent_history_texts(session))
    return bool(joined and _WORK_CONTEXT_RE.search(joined))


def _try_greeting(msg_lower: str, session: Any) -> tuple[str, dict] | None:
    """Return a canned reply for simple greetings, or None."""
    clean = msg_lower.rstrip(" !.,?").strip()

    if clean in _AMBIGUOUS_GREETING_TOKENS and _has_recent_work_context(session):
        return None

    reply = _GREETING_REPLIES.get(clean)
    if reply:
        return reply, {"fp_type": "greeting"}

    for pat, resp in _GREETING_PATTERNS:
        if pat.fullmatch(clean):
            return resp, {"fp_type": "greeting"}

    return None


# ---------------------------------------------------------------------------
# Fast path 2: Help / capability query
# ---------------------------------------------------------------------------

_HELP_TEXT = (
    "Posso ajudar com:\n"
    "Contexto    - \"mostra contexto do no X\" ou \"analisa a cena\"\n"
    "Draft       - \"cria um draft para ajustar X\" ou \"continua o draft\"\n"
    "Feedback    - \"rodei e nada aconteceu\" ou \"desfiz\"\n"
    "Captura     - \"tire um screenshot\"\n\n"
    "Exemplos rapidos:\n"
    "  cria um draft para mudar VM_G1_Scale para 1.0\n"
    "  mostra contexto de VM_G1_Scale\n"
    "  qual o estado da cena?"
)

_HELP_RE = re.compile(
    r"^(?:"
    r"ajuda|help|socorro|"
    r"o\s+que\s+(?:você|voce)\s+(?:pode\s+)?(?:fazer|me\s+ajudar)|"
    r"quais?\s+(?:são\s+)?(?:as\s+)?(?:ferramentas|comandos|funções|funcoes|opções|opcoes)|"
    r"como\s+(?:você|voce)\s+funciona|"
    r"o\s+que\s+[eéê]\s+isso|"
    r"what\s+(?:can\s+you\s+do|are\s+your\s+tools)|"
    r"list\s+tools?"
    r")$",
    re.IGNORECASE,
)


def _try_help(msg_lower: str) -> tuple[str, dict] | None:
    clean = msg_lower.rstrip(" !.,?").strip()
    if _HELP_RE.match(clean):
        return _HELP_TEXT, {"fp_type": "help"}
    return None


def _try_blender_console_help(msg_lower: str) -> tuple[str, dict] | None:
    clean = msg_lower.rstrip(" !.,?").strip()
    words = set(clean.replace("?", " ").split())
    asks_where = bool(words & {"onde", "cadê", "cade"})
    asks_prints = bool(words & {"print", "prints", "imprimiu", "impressao", "impressão", "console"})
    if not (asks_where and asks_prints):
        return None
    return (
        "No Blender, o `print()` de um script aparece no console do sistema, não no painel do chat.\n\n"
        "Caminho rápido no Windows: menu **Window > Toggle System Console**. "
        "Depois rode o script de novo no Text Editor; as linhas `print(...)` aparecem nessa janela preta.\n\n"
        "Se você abriu o Blender pelo terminal/PowerShell, os prints também podem aparecer no terminal que iniciou o Blender.",
        {"fp_type": "blender_console_help"},
    )


# ---------------------------------------------------------------------------
# Fast path 3: Simple reads (get_node_context without LLM)
# ---------------------------------------------------------------------------

# Verb-first: "mostra [o] [contexto [do]] [nó] NAME"
_READ_VERB_RE = re.compile(
    r"^(?:mostr[ae]|show|ver|veja?|exib[ae])\s+"
    r"(?:o\s+)?(?:contexto\s+)?(?:d[oae]\s+)?(?:n[oó]\s+)?"
    r"(?P<node>\S+)\s*$",
    re.IGNORECASE,
)
# Noun-first: "contexto [do] [nó] NAME"
_READ_CONTEXT_RE = re.compile(
    r"^contexto\s+(?:d[oae]\s+)?(?:n[oó]\s+)?(?P<node>\S+)\s*$",
    re.IGNORECASE,
)
# Question: "o que é [o] [nó] NAME"
_READ_WHAT_RE = re.compile(
    r"^o\s+que\s+[eéê]\s+(?:o\s+)?(?:n[oó]\s+)?(?P<node>\S+)\s*$",
    re.IGNORECASE,
)


def _try_simple_read(msg: str, runtime: Any) -> tuple[str, dict] | None:
    """Call get_node_context directly and return its output.  Falls through on error."""
    clean = msg.strip().rstrip("?.,!")
    m = (
        _READ_VERB_RE.match(clean)
        or _READ_CONTEXT_RE.match(clean)
        or _READ_WHAT_RE.match(clean)
    )
    if not m:
        return None

    node_name = m.group("node").strip().rstrip("?.,!")
    # Require ≥3 chars, no spaces, and at least one structural hint:
    # underscore (GN parameter naming) or initial uppercase (proper node name).
    # This rejects generic lowercase words like "resultado", "tudo", "isso".
    if len(node_name) < 3 or " " in node_name:
        return None
    if "_" not in node_name and not node_name[0].isupper():
        return None

    try:
        result = runtime._execute_tool("get_node_context", {"node_name": node_name}, 0)
    except Exception:
        return None

    if _is_fast_path_read_failure(result):
        return None

    return result, {"fp_type": "read", "node": node_name}


def _is_fast_path_read_failure(result: Any) -> bool:
    text = str(result or "").strip()
    if not text:
        return True

    upper = text.upper()
    if upper.startswith("ERROR:") or upper.startswith("BLOCKED:"):
        return True

    try:
        payload = json.loads(text)
    except Exception:
        return False

    if not isinstance(payload, dict):
        return False

    status = str(payload.get("status", "") or "").strip().lower()
    return status in {"error", "blocked"}


# ---------------------------------------------------------------------------
# Fast path 4: Draft confirmation short-circuit
# ---------------------------------------------------------------------------

# Same core pattern as _SHORT_CONFIRMATION_RE in drafting.py — kept local to
# avoid a cross-package import.
_DRAFT_CONFIRM_RE = re.compile(
    r"^\s*(pode|sim|ok|claro|manda|vai|bora|yes|sure|go\s+ahead|do\s+it)\s*[!.]?\s*$",
    re.IGNORECASE,
)

# Any of these tokens in the message indicate the user is doing more than
# confirming — new instruction, error report, scene-read request, etc.
# When present, fall through to the full handler.
_FP4_DISQUALIFY_RE = re.compile(
    r"\b("
    r"mas\b|s[oó]\s+que|depois\s+de|exceto|a\s+n[aã]o\s+ser|"  # new constraint qualifiers
    r"ajust|muda|troca|corrig|conserta|refina|reescrev|"         # correction verbs
    r"adicion|inclu|expand|cria|gera|implement|"                 # expansion verbs
    r"erro|falh|deu\s+errado|n[aã]o\s+deu|nada\s+aconteceu|"   # error reports
    r"por\s+que|porque|why|o\s+que\s+est|"                      # diagnosis questions
    r"cena|scene|arvore|[aá]rvore|modifier|objeto"              # scene-read scope
    r")\b",
    re.IGNORECASE,
)


def _try_draft_confirmation(msg: str, session: Any) -> tuple[str, dict] | None:
    """FP4: present a pending draft for manual Blender execution.

    Fires only when ALL of the following hold:
    - ``execution_state.pending_draft_action == "write_confirmed_draft_revision"``
    - ``execution_state.phase == "drafting"``
    - The message is a bare short confirmation (no new instructions, no errors)
    - There is draft evidence in the session (current_draft set OR draft_revision > 0)

    Side effect: clears ``pending_draft_action`` / ``pending_draft_prompt`` so the
    next turn starts clean. The session is persisted by the call site in run_turn().
    """
    es = getattr(session, "execution_state", None)
    if es is None:
        return None

    # Must have a pending confirmed-write action
    pending = str(getattr(es, "pending_draft_action", "") or "").strip()
    if pending != "write_confirmed_draft_revision":
        return None

    # Only fire in drafting phase — failed/halted/idle need the full handler
    phase = str(getattr(es, "phase", "") or "")
    if phase != "drafting":
        return None

    # Message must be a bare short confirmation
    clean = msg.strip()
    if not _DRAFT_CONFIRM_RE.match(clean):
        return None

    # No disqualifying content (new instructions, errors, scene-read scope)
    if _FP4_DISQUALIFY_RE.search(clean):
        return None

    # Draft evidence must exist — otherwise the agent still needs to write it
    draft = getattr(es, "current_draft", None)
    draft_revision = int(getattr(es, "draft_revision", 0) or 0)
    if draft is None and draft_revision <= 0:
        return None

    block_name = str(
        getattr(draft, "block_name", "") or getattr(es, "draft_block_name", "") or "GN_Agent_Draft"
    )
    version = int(getattr(draft, "version", 0) or draft_revision or 0)
    chars = int(
        getattr(draft, "last_written_chars", 0) or getattr(es, "last_saved_char_count", 0) or 0
    )

    # Clear pending action before returning — session is saved by the call site
    es.pending_draft_action = ""
    es.pending_draft_prompt = ""

    rev_label = f"revisão {version}" if version > 0 else "draft"
    char_label = f", {chars} chars" if chars > 0 else ""

    response = (
        f"Script pronto em `{block_name}` ({rev_label}{char_label}).\n\n"
        "Para executar manualmente no Blender:\n"
        "1. Abra o **Text Editor** → selecione `GN_Agent_Draft`\n"
        "2. Clique em **Run Script** (ou `Alt+P`)\n"
        "3. Observe o resultado no Viewport\n\n"
        "Depois, relate o que aconteceu para eu diagnosticar ou dar continuidade."
    )

    return response, {
        "fp_type": "draft_confirmation",
        "block_name": block_name,
        "version": version,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def try_fast_path(
    message: str,
    *,
    session: Any,
    runtime: Any,
) -> tuple[str, dict] | None:
    """Try to resolve *message* without an LLM call.

    Returns ``(response_text, metadata)`` when handled; ``None`` to fall
    through to the normal TurnRouter → handler → agent_loop flow.

    The ``metadata`` dict always has ``fp_type`` set to one of:
    ``"greeting"``, ``"help"``, ``"read"``.
    Read hits also carry ``"node"``.

    Safety invariants
    -----------------
    - Reads fall through on any tool error (never return an error string).
    - The entire call is wrapped in try/except at the call site in
      ``run_turn()``; any uncaught exception here silently falls through.
    """
    if not message or not message.strip():
        return None


    msg = message.strip()
    msg_lower = msg.lower()

    hit = _try_draft_confirmation(msg, session)
    if hit is not None:
        return hit

    hit = _try_greeting(msg_lower, session)
    if hit is not None:
        return hit

    hit = _try_help(msg_lower)
    if hit is not None:
        return hit

    hit = _try_blender_console_help(msg_lower)
    if hit is not None:
        return hit

    hit = _try_simple_read(msg, runtime)
    if hit is not None:
        return hit

    return None
