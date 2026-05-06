"""Automatic knowledge extraction from successful agent turns.

After a successful run_turn(), reads the operations from the journal,
identifies GN patterns (nodes created, connections made), and uses
claude-haiku to synthesize a compact markdown snippet that gets
appended to the relevant knowledge file.

Only triggers when:
  - The goal completed without errors
  - There were GN mutations (code_execution entries with bpy.data.node_groups)
  - The user didn't undo in the next message
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Pattern extraction from journal entries
# ---------------------------------------------------------------------------

_GN_MARKERS = (
    "node_groups", "nodes.new", "links.new", "nodes.remove",
    "default_value", "node_tree", ".inputs[", ".outputs[",
)


def _extract_gn_operations(session_file: Path, goal_id: str) -> list[dict[str, Any]]:
    """Read JSONL entries for a specific goal, return code_execution entries
    that contain GN-related code."""
    if not session_file or not session_file.exists():
        return []

    ops = []
    try:
        with session_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("goal_id") != goal_id:
                    continue
                if entry.get("type") != "code_execution":
                    continue
                code = entry.get("code", "")
                if any(marker in code for marker in _GN_MARKERS):
                    ops.append({
                        "code": code,
                        "status": entry.get("status", ""),
                        "stdout": entry.get("stdout", ""),
                    })
    except Exception:
        return []
    return ops


# ---------------------------------------------------------------------------
# Haiku synthesis
# ---------------------------------------------------------------------------

_SYNTHESIS_PROMPT = """\
Você é um assistente técnico que documenta padrões de Geometry Nodes no Blender.

Abaixo estão operações Python executadas com sucesso em uma sessão de edição de GN.
Extraia o PADRÃO reutilizável — não o caso específico.

Regras:
- Máximo 10 linhas de markdown
- Foco em: quais nós foram criados, como foram conectados, qual o propósito
- Use formato: ## Padrão: <nome curto>
- Se não houver padrão reutilizável claro, responda apenas: SKIP
- Não inclua valores específicos de coordenadas ou nomes de objetos

Operações executadas:
"""


_SYNTHESIS_TIMEOUT = 30.0  # seconds; raises APITimeoutError on expiry


def _synthesize_pattern(
    operations: list[dict[str, Any]],
    api_key: str,
    client: Any = None,
) -> str | None:
    """Call claude-haiku to synthesize a reusable pattern from operations.

    Returns markdown string or None if no pattern found.
    If *client* is provided it is reused (caller owns lifecycle); otherwise a
    short-lived client is created from *api_key* as a fallback.
    """
    ops_text = "\n\n".join(
        f"```python\n{op['code']}\n```\nStatus: {op['status']}"
        for op in operations[:8]  # limit to avoid large prompts
    )

    import anthropic
    _client = client if client is not None else anthropic.Anthropic(api_key=api_key)
    response = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        timeout=_SYNTHESIS_TIMEOUT,
        messages=[{
            "role": "user",
            "content": _SYNTHESIS_PROMPT + ops_text,
        }],
    )

    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    text = text.strip()
    if not text or text == "SKIP":
        return None
    return text


# ---------------------------------------------------------------------------
# Knowledge file appender
# ---------------------------------------------------------------------------

def _append_to_knowledge(knowledge_dir: Path, pattern_md: str) -> Path:
    """Append a pattern to the learned patterns knowledge file."""
    target = knowledge_dir / "learned_patterns.md"

    if not target.exists():
        header = (
            "# Padrões Aprendidos — Geometry Nodes\n\n"
            "> Gerado automaticamente pelo knowledge_updater.\n"
            "> Cada padrão foi extraído de uma sessão bem-sucedida.\n\n"
            "---\n\n"
        )
        target.write_text(header, encoding="utf-8")

    with target.open("a", encoding="utf-8") as f:
        f.write(f"{pattern_md}\n\n---\n\n")

    return target


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def maybe_extract_knowledge(
    *,
    journal_session_file: Path | None,
    goal_id: str,
    had_errors: bool,
    api_key: str,
    knowledge_dir: Path,
    client: Any = None,
) -> None:
    """Attempt to extract and save a GN pattern from the completed goal.

    Runs in a background thread to not block the UI.
    Does nothing if the goal had errors or no GN operations.

    *client* — optional pre-built Anthropic client owned by the caller.  If
    provided it is reused directly (no new client is created, no lifecycle
    responsibility).  Falls back to creating a short-lived client from
    *api_key* when None.
    """
    if had_errors or not journal_session_file or not goal_id:
        return

    def _worker():
        try:
            ops = _extract_gn_operations(journal_session_file, goal_id)
            if len(ops) < 2:
                # Need at least 2 GN operations to form a pattern
                return

            pattern = _synthesize_pattern(ops, api_key, client=client)
            if pattern:
                path = _append_to_knowledge(knowledge_dir, pattern)
                print(f"[KnowledgeUpdater] Pattern saved to {path}")
        except Exception as exc:
            print(f"[KnowledgeUpdater] Error: {exc}")

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
