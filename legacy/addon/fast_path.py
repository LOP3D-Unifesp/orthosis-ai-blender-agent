"""Fast paths for deterministic resolution without LLM.

Intercepts specific message patterns before the slim runtime classifier
(``runtime/router.infer_turn_intent``) and returns a response string without
any API call (or with exactly one direct tool call).

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
from typing import Any

from .text_utils import _clean_text, _has_phrase, _has_prefix, _message_words


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
def _recent_history_texts(session: Any, limit: int = 6) -> list[str]:
    history = getattr(getattr(session, "history", None), "messages", []) or []
    texts: list[str] = []
    for item in history[-limit:]:
        content = str(getattr(item, "content", "") or "").strip()
        if content:
            texts.append(content)
    return texts


def _has_recent_work_context(session: Any) -> bool:
    words = _message_words("\n".join(_recent_history_texts(session)))
    word_set = set(words)
    return (
        bool({
            "script", "codigo", "python", "bpy", "execute_code", "socket",
            "painel", "panel", "interface", "node", "blender", "erro",
            "falhou", "input", "output",
        } & word_set)
        or _has_phrase(words, "geometry", "nodes")
        or _has_prefix(words, "truncad", "executar", "rodar", "adicion", "criar", "alterar", "modificar")
    )


def _try_greeting(msg_lower: str, session: Any) -> tuple[str, dict] | None:
    """Return a canned reply for simple greetings, or None."""
    clean = _clean_text(msg_lower)

    if clean in _AMBIGUOUS_GREETING_TOKENS and _has_recent_work_context(session):
        return None

    reply = _GREETING_REPLIES.get(clean)
    if reply:
        return reply, {"fp_type": "greeting"}

    words = clean.split()
    if words in (["oi", "tudo", "bem"], ["oi", "tudo", "bom"]):
        return "Oi! Tudo bem! Como posso ajudar?", {"fp_type": "greeting"}
    if words in (["ola", "tudo", "bem"], ["ola", "tudo", "bom"]):
        return "Olá! Tudo bem! Como posso ajudar?", {"fp_type": "greeting"}

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

def _try_help(msg_lower: str) -> tuple[str, dict] | None:
    words = _message_words(msg_lower)
    word_set = set(words)
    if (
        words in (["ajuda"], ["help"], ["socorro"])
        or _has_phrase(words, "o", "que", "voce", "fazer")
        or _has_phrase(words, "o", "que", "voce", "pode", "fazer")
        or _has_phrase(words, "o", "que", "voce", "me", "ajudar")
        or ("quais" in word_set and bool({"ferramentas", "comandos", "funcoes", "opcoes"} & word_set))
        or ("qual" in word_set and bool({"ferramentas", "comandos", "funcoes", "opcoes"} & word_set))
        or ("como" in word_set and "voce" in word_set and "funciona" in word_set)
        or _has_phrase(words, "o", "que", "e", "isso")
        or _has_phrase(words, "what", "can", "you", "do")
        or _has_phrase(words, "what", "are", "your", "tools")
        or _has_phrase(words, "list", "tools")
        or words == ["list", "tool"]
    ):
        return _HELP_TEXT, {"fp_type": "help"}
    return None


def _try_blender_console_help(msg_lower: str) -> tuple[str, dict] | None:
    words = set(_message_words(msg_lower))
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

def _try_simple_read(msg: str, runtime: Any) -> tuple[str, dict] | None:
    """Call get_node_context directly and return its output.  Falls through on error."""
    clean = msg.strip().rstrip("?.,!")
    raw_parts = clean.split()
    words = _message_words(clean)
    node_index = _simple_read_node_index(words)
    if node_index is None or node_index >= len(raw_parts):
        return None

    node_name = raw_parts[node_index].strip().rstrip("?.,!")
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


def _simple_read_node_index(words: list[str]) -> int | None:
    if not words:
        return None
    if words[0] in {"mostra", "mostre", "show", "ver", "ve", "veja", "exiba", "exibe"}:
        index = 1
        while index < len(words) and words[index] in {"o", "a", "contexto", "do", "da", "de", "no", "na", "node"}:
            index += 1
        return index if index == len(words) - 1 else None
    if words[0] == "contexto":
        index = 1
        while index < len(words) and words[index] in {"do", "da", "de", "no", "na", "node"}:
            index += 1
        return index if index == len(words) - 1 else None
    if len(words) >= 4 and words[:3] == ["o", "que", "e"]:
        index = 3
        while index < len(words) and words[index] in {"o", "a", "no", "na", "node"}:
            index += 1
        return index if index == len(words) - 1 else None
    return None


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
    if not _is_bare_confirmation(clean):
        return None

    # No disqualifying content (new instructions, errors, scene-read scope)
    if _has_fp4_disqualifier(clean):
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


def _is_bare_confirmation(message: str) -> bool:
    words = _message_words(message)
    return words in (
        ["pode"], ["sim"], ["ok"], ["claro"], ["manda"], ["vai"], ["bora"],
        ["yes"], ["sure"], ["go", "ahead"], ["do", "it"],
    )


def _has_fp4_disqualifier(message: str) -> bool:
    words = _message_words(message)
    word_set = set(words)
    return (
        bool({"mas", "exceto", "erro", "falhou", "porque", "why", "cena", "scene", "arvore", "modifier", "objeto"} & word_set)
        or _has_phrase(words, "so", "que")
        or _has_phrase(words, "depois", "de")
        or _has_phrase(words, "a", "nao", "ser")
        or _has_prefix(words, "ajust", "muda", "troca", "corrig", "consert", "refina", "reescrev")
        or _has_prefix(words, "adicion", "inclu", "expand", "cria", "gera", "implement")
        or _has_prefix(words, "falh")
        or _has_phrase(words, "deu", "errado")
        or _has_phrase(words, "nao", "deu")
        or _has_phrase(words, "nada", "aconteceu")
        or _has_phrase(words, "por", "que")
        or _has_phrase(words, "o", "que", "est")
    )


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
    through to the normal infer_turn_intent → workspace.handle → agent_loop flow.

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
