"""Draft response formatting and chat-safety helpers."""

from __future__ import annotations

import re

# Match any ``` block regardless of language specifier (including bare ```)
_CODE_FENCE_RE = re.compile(r"```\w*\s*\n(.*?)\n```", re.IGNORECASE | re.DOTALL)
_RAW_DRAFT_CODE_MARKER_RE = re.compile(
    r"\b(import\s+bpy|bpy\.data|node_groups|GeometryNodeTree|write_script_draft|tree\.nodes|tree\.links"
    r"|ng\.nodes|modifier\.node_group|\.node_group\s*=|nodes\.get\(|nodes\.new\(|links\.new\()",
    re.IGNORECASE,
)
_RAW_CODE_LINE_RE = re.compile(
    r"^\s*(import\s+\w+|from\s+\w+\s+import|def\s+\w+|class\s+\w+|if\s+.+:|for\s+.+:|while\s+.+:|try:|except\b|with\s+.+:|"
    r"[A-Za-z_]\w*\s*=|[A-Za-z_]\w*\.[A-Za-z_]\w*\s*=|print\s*\(|raise\s+|return\b|bpy\.|tree\.|nodes\.|links\.|#)",
    re.IGNORECASE,
)


def extract_code_fences(text: str) -> str:
    """Return concatenated Python-like fenced code blocks from assistant text."""
    blocks = [match.group(1).strip() for match in _CODE_FENCE_RE.finditer(str(text or ""))]
    return "\n\n".join(block for block in blocks if block.strip())


def _line_count(text: str) -> int:
    return len(str(text or "").splitlines()) if str(text or "") else 0


def _validate_agent_loop_code_fence(code: str, current_draft_content: str) -> tuple[bool, str]:
    """Reject low-confidence code fences before they can become real draft revisions."""
    candidate = str(code or "").strip()
    if not candidate:
        return False, "empty_code_fence"
    line_count = _line_count(candidate)
    char_count = len(candidate)
    current_len = len(str(current_draft_content or ""))
    if line_count < 8 or char_count < 300:
        return False, "code_fence_too_small"
    if current_len >= 600 and char_count < int(current_len * 0.35):
        return False, "code_fence_tiny_vs_current_draft"
    try:
        compile(candidate, "<agent_loop_code_fence>", "exec")
    except SyntaxError:
        return False, "code_fence_syntax_error"
    if "bpy" not in candidate and "node" not in candidate.lower() and "print(" not in candidate:
        return False, "code_fence_not_blender_or_python_draft_like"
    return True, ""


def _runtime_loop_blocker(runtime) -> str:
    if bool(getattr(runtime, "_last_agent_loop_truncated", False)):
        return (
            "A resposta do modelo foi truncada antes de concluir uma revisao segura. "
            "Eu nao vou tentar salvar codigo parcial no Text Editor. Podemos continuar "
            "numa nova tentativa mais focada ou quebrar a tarefa em partes menores."
        )
    if bool(getattr(runtime, "_last_agent_loop_round_limit_hit", False)):
        return (
            "O turno bateu no limite de rounds antes de concluir uma revisao segura do draft. "
            "Preferi nao salvar codigo incompleto. Se voce quiser, eu continuo a partir daqui "
            "com uma tentativa mais focada."
        )
    return ""


def _raw_python_draft_candidate(text: str) -> str:
    """Return likely raw Python draft emitted in chat instead of via tool."""
    body = str(text or "").strip()
    if not body or _CODE_FENCE_RE.search(body):
        return ""
    if not _RAW_DRAFT_CODE_MARKER_RE.search(body):
        return ""

    lines = body.splitlines()
    best_start = 0
    for idx, line in enumerate(lines):
        if _RAW_CODE_LINE_RE.search(line):
            best_start = idx
            break
    candidate = "\n".join(lines[best_start:]).strip()
    candidate_lines = candidate.splitlines()
    for end in range(len(candidate_lines), 7, -1):
        trimmed = "\n".join(candidate_lines[:end]).strip()
        try:
            compile(trimmed, "<raw_agent_chat_code>", "exec")
        except SyntaxError:
            continue
        if _RAW_DRAFT_CODE_MARKER_RE.search(trimmed):
            return trimmed
    nonempty = [line for line in candidate.splitlines() if line.strip()]
    if len(nonempty) < 8:
        return ""
    codey = sum(1 for line in nonempty if _RAW_CODE_LINE_RE.search(line))
    if codey / max(1, len(nonempty)) < 0.35:
        return ""
    return candidate


def _draft_summary(
    *,
    action: str,
    block_name: str,
    revision: int,
    char_count: int,
    line_count: int = 0,
    description: str = "",
    incomplete: str = "",
) -> str:
    lines = [
        f"{action} no Text Editor: **{block_name}**.",
        f"Versao interna: {revision} | tamanho: ~{line_count or max(1, char_count // 60)} linhas, {char_count} caracteres.",
    ]
    if description:
        lines.append(f"Resumo: {description[:220]}.")
    if incomplete:
        lines.append(f"Ainda falta: {incomplete[:220]}.")
    lines.append("Execute manualmente pelo Blender quando quiser testar; eu nao rodei o script.")
    return "\n".join(lines)


def _draft_source_note(info: dict) -> str:
    if not isinstance(info, dict) or not bool(info.get("legacy_fallback_used", False)):
        return ""
    version = int(info.get("version") or 0)
    block_name = str(info.get("legacy_block_name") or "")
    validity = str(info.get("current_revision_validity") or info.get("revision_validity") or "unknown")
    chars = int(info.get("char_count") or 0)
    return (
        f"Nota de migracao: o bloco principal `GN_Agent_Draft` nao estava disponivel, "
        f"entao usei o bloco legado `{block_name}` (versao {version}, `{validity}`, {chars} chars) "
        "como fonte temporaria ate o draft canonico voltar a existir."
    )


def _strip_code_fences_for_chat(text: str) -> str:
    cleaned = _CODE_FENCE_RE.sub("[codigo omitido: a analise nao escreve nem despeja script no chat]", str(text or ""))
    return cleaned.strip()


def _sanitize_draft_chat_response(text: str) -> str:
    """Never let generated draft Python leak into the addon chat panel."""
    body = _strip_code_fences_for_chat(text)
    if _raw_python_draft_candidate(body):
        return (
            "O modelo tentou devolver codigo Python no chat em vez de salvar no Text Editor. "
            "Eu bloqueei essa saida no painel. Quando eu gerar uma revisao, ela precisa ser escrita via `write_script_draft` "
            "no `GN_Agent_Draft`; se a escrita for bloqueada, vou reportar o motivo sem despejar o script aqui."
        )

    lines = body.splitlines()
    sanitized: list[str] = []
    raw_code_seen = False
    codey_streak = 0
    for line in lines:
        if _RAW_DRAFT_CODE_MARKER_RE.search(line) or _RAW_CODE_LINE_RE.search(line):
            codey_streak += 1
        else:
            codey_streak = 0
        if codey_streak >= 2:
            raw_code_seen = True
            while sanitized and (_RAW_DRAFT_CODE_MARKER_RE.search(sanitized[-1]) or _RAW_CODE_LINE_RE.search(sanitized[-1]) or not sanitized[-1].strip()):
                sanitized.pop()
            if sanitized and sanitized[-1].strip():
                sanitized.append("")
            sanitized.append("[codigo omitido: draft Python deve ser salvo no Text Editor, nao no chat]")
            break
        sanitized.append(line)
    result = "\n".join(sanitized).strip()
    if raw_code_seen:
        return result or "Bloqueei uma resposta com codigo no chat; o draft deve ser salvo no Text Editor."
    return body.strip()


def _brief_chat_summary(text: str, *, max_chars: int = 900) -> str:
    cleaned = _sanitize_draft_chat_response(text)
    if len(cleaned) <= max_chars:
        return cleaned
    cut = cleaned[:max_chars].rstrip()
    for sep in (". ", "\n- ", "\n"):
        idx = cut.rfind(sep)
        if idx >= max_chars // 2:
            cut = cut[: idx + (1 if sep == ". " else 0)].rstrip()
            break
    return cut.rstrip(" ,;:-") + "..."


def _finalize_round_limit_text(text: str) -> str:
    body = str(text or "").strip()
    if "Atingi o limite" not in body and "limite de" not in body and "round limit" not in body.lower():
        return body
    return (
        "Parei porque este turno chegou ao limite interno de investigacao antes de concluir uma acao confiavel. "
        "Nao vou fingir que finalizei: a leitura ficou parcial.\n\n"
        "Leitura parcial: eu estava tentando localizar o caminho/nos relevantes antes de alterar o draft. "
        "Melhor proximo passo: usar o contexto ja levantado para uma correcao focal do `GN_Agent_Draft`, "
        "com uma unica escrita completa e depois parar para voce testar manualmente."
    )
