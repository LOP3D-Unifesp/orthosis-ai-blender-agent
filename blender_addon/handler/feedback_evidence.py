"""Evidence and fallback analysis helpers for draft execution feedback."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import TurnContext

_POST_FAILURE_REQUIRED_SECTIONS = (
    "Sintoma",
    "Hipotese",
    "Evidencia",
    "Confianca",
    "Limitacoes",
    "Opcoes",
    "Pergunta",
)


def _read_draft_info(ctx: TurnContext, block_name: str) -> dict:
    raw_info = _read_draft_payload(ctx, block_name)
    result = raw_info.get("result")
    return result if isinstance(result, dict) else {}


def _read_draft_payload(ctx: TurnContext, block_name: str) -> dict:
    try:
        raw = ctx.execute_tool("read_script_draft", {"block_name": block_name})
        if str(raw).startswith(("ERROR:", "BLOCKED:")):
            return {"status": "error", "error": str(raw), "result": {}}
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return {"status": "", "error": "", "result": {}}
        result = parsed.get("result", parsed)
        return {
            "status": str(parsed.get("status") or ""),
            "error": str(parsed.get("error") or ""),
            "result": result if isinstance(result, dict) else {},
        }
    except Exception:
        return {"status": "error", "error": "read_script_draft_exception", "result": {}}


def _safe_draft_history_part(value: str, *, fallback: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("._")
    return safe[:80] or fallback


def _read_archived_draft_revision(
    ctx: TurnContext,
    *,
    block_name: str,
    revision: int,
) -> dict[str, Any]:
    """Read the failed draft from runtime/draft_history before using Blender UI state."""
    runtime = getattr(ctx, "_runtime", None)
    project_root = getattr(runtime, "project_root", None)
    if not project_root:
        project_root = getattr(getattr(runtime, "runtime", None), "project_root", None)
    session_id = str(getattr(getattr(ctx.session, "identity", None), "session_id", "") or "").strip()
    if not project_root or not session_id:
        return {}
    try:
        root = Path(project_root).expanduser().resolve()
    except Exception:
        return {}
    archive_dir = root / "runtime" / "draft_history" / _safe_draft_history_part(session_id, fallback="unsessioned")
    if not archive_dir.exists():
        return {}
    safe_block = _safe_draft_history_part(block_name, fallback="GN_Agent_Draft")
    candidates: list[Path] = []
    if revision > 0:
        exact = archive_dir / f"r{int(revision):06d}_{safe_block}.py"
        if exact.exists():
            candidates.append(exact)
    if not candidates:
        try:
            candidates = sorted(
                archive_dir.glob(f"r*_{safe_block}.py"),
                key=lambda p: p.name,
                reverse=True,
            )
        except Exception:
            candidates = []
    if not candidates:
        return {}
    path = candidates[0]
    match = re.match(r"r(\d{6})_", path.name)
    archived_revision = int(match.group(1)) if match else int(revision or 0)
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    if not content.strip():
        return {}
    return {
        "block_name": block_name or "GN_Agent_Draft",
        "content": content,
        "version": archived_revision,
        "char_count": len(content),
        "draft_archive_path": str(path),
        "source": "draft_history",
    }


def _read_failed_draft_info(
    ctx: TurnContext,
    *,
    block_name: str,
    revision: int,
) -> dict[str, Any]:
    archived = _read_archived_draft_revision(ctx, block_name=block_name, revision=revision)
    if archived:
        return archived
    info = _read_draft_info(ctx, block_name)
    if isinstance(info, dict) and str(info.get("content") or "").strip():
        info = dict(info)
        info.setdefault("source", "text_editor")
        return info
    return {}


def _analysis_strategy_count(text: str) -> int:
    body = str(text or "")
    keyword_count = len(re.findall(r"\b(opcao|option|strategy|estrategia|caminho|strategy\s+[abc]|estrategia\s+[abc])\b", body, re.I))
    labeled_count = len(re.findall(r"(?im)^\s*(?:[-*]\s*)?(?:strategy|estrategia|opcao|option|caminho)?\s*[ABC123][\).:-]\s+\S+", body))
    return max(keyword_count, labeled_count)


def _analysis_has_diagnosis(text: str) -> bool:
    return bool(re.search(r"\b(likely failure|falha provavel|provavel|diagn[oó]stico|diagnostico|causa|failed|falhou|errad[oa]|problema)\b", str(text or ""), re.I))


def _analysis_has_failure_reason(text: str) -> bool:
    return bool(re.search(r"\b(n[aã]o consegui|nao consegui|insuficiente|sem dados|could not|unable|failure reason|motivo)\b", str(text or ""), re.I))


def _analysis_is_useful(text: str) -> bool:
    body = str(text or "").strip()
    if not body:
        return False
    if len(body) < 80 and _analysis_strategy_count(body) < 1 and not _analysis_has_failure_reason(body):
        return False
    return _analysis_strategy_count(body) >= 1 or _analysis_has_diagnosis(body) or _analysis_has_failure_reason(body)


def _post_failure_missing_sections(text: str) -> list[str]:
    body = str(text or "")
    missing: list[str] = []
    for section in _POST_FAILURE_REQUIRED_SECTIONS:
        if not re.search(rf"(?im)^\s*{re.escape(section)}\s*:", body):
            missing.append(section)
    return missing


def _post_failure_strategy_count(text: str) -> int:
    body = str(text or "")
    labeled = len(re.findall(r"(?im)^\s*(?:[-*]\s*)?[AB][\).:-]\s+\S+", body))
    return max(labeled, _analysis_strategy_count(body))


def _post_failure_contract_status(text: str) -> tuple[bool, list[str], int]:
    missing = _post_failure_missing_sections(text)
    strategy_count = _post_failure_strategy_count(text)
    return not missing, missing, strategy_count


def _post_failure_quality_status(text: str, evidence: dict[str, Any]) -> tuple[bool, list[str], int]:
    body = str(text or "").strip()
    strategy_count = _post_failure_strategy_count(body)
    missing: list[str] = []
    if not body:
        return False, ["empty_response"], strategy_count
    if len(body) < 80 and not _analysis_is_useful(body):
        missing.append("too_sparse")
    evidence = evidence if isinstance(evidence, dict) else {}
    mismatches = [str(item) for item in (evidence.get("semantic_mismatches") or []) if str(item).strip()]
    if mismatches:
        if not _text_mentions_any(body, mismatches):
            missing.append("static_evidence_mismatch")
    else:
        concrete_terms = _concrete_evidence_terms(evidence)
        if concrete_terms and not _text_mentions_any(body, concrete_terms):
            missing.append("concrete_static_evidence")
    return not missing, missing, strategy_count


def _text_mentions_any(text: str, terms: list[str]) -> bool:
    lowered = str(text or "").lower()
    for term in terms:
        candidate = str(term or "").strip().lower()
        if len(candidate) < 2:
            continue
        if candidate in lowered:
            return True
    return False


def _concrete_evidence_terms(evidence: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for key in ("touched_nodes", "disconnect_translation_targets", "interface_socket_reads", "missing_referenced_nodes"):
        values = evidence.get(key) if isinstance(evidence.get(key), list) else []
        for value in values:
            text = str(value or "").strip()
            if text:
                terms.append(text)
    for item in evidence.get("socket_writes") or []:
        if not isinstance(item, dict):
            continue
        node = str(item.get("node") or "").strip()
        socket = str(item.get("socket") or "").strip()
        if node:
            terms.append(node)
        if socket:
            terms.append(socket)
        if node and socket:
            terms.append(f"{node}.{socket}")
    for item in evidence.get("touched_node_context") or []:
        if not isinstance(item, dict):
            continue
        for key in ("node", "parent_frame", "label"):
            text = str(item.get(key) or "").strip()
            if text:
                terms.append(text)
    return terms


def _node_name_terms(name: str) -> set[str]:
    lowered = str(name or "").lower()
    terms: set[str] = set()
    if "falange" in lowered or "phalange" in lowered:
        terms.add("falange")
    if "metacarpo" in lowered or "metacarp" in lowered:
        terms.add("metacarpo")
    if "palma" in lowered or "palm" in lowered:
        terms.add("palma")
    return terms


def _structural_node_index(memory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(memory, dict):
        return {}
    index: dict[str, dict[str, Any]] = {}
    nodes = memory.get("nodes") if isinstance(memory.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        name = str(node.get("name") or "").strip()
        if not name:
            continue
        index[name] = {
            "name": name,
            "label": str(node.get("label") or ""),
            "parent_frame": str(node.get("parent_frame") or node.get("parent") or ""),
            "bl_idname": str(node.get("bl_idname") or node.get("type") or ""),
        }
    regions = memory.get("major_regions") if isinstance(memory.get("major_regions"), list) else memory.get("frames", [])
    if not isinstance(regions, list):
        regions = []
    for region in regions:
        if not isinstance(region, dict):
            continue
        region_name = str(region.get("name") or region.get("label") or region.get("region") or "").strip()
        key_nodes = region.get("key_nodes") if isinstance(region.get("key_nodes"), list) else []
        for node_name in key_nodes:
            name = str(node_name or "").strip()
            if not name:
                continue
            entry = index.setdefault(name, {"name": name, "label": "", "parent_frame": "", "bl_idname": ""})
            if region_name and not str(entry.get("parent_frame") or ""):
                entry["parent_frame"] = region_name
    marker = memory.get("marker") if isinstance(memory.get("marker"), dict) else {}
    marker_names = marker.get("node_names") if isinstance(marker.get("node_names"), list) else []
    for node_name in marker_names:
        name = str(node_name or "").strip()
        if name:
            index.setdefault(name, {"name": name, "label": "", "parent_frame": "", "bl_idname": ""})
    return index


def _extract_failed_draft_static_evidence(content: str, structural_memory: dict[str, Any]) -> dict[str, Any]:
    code = str(content or "")
    alias_to_node: dict[str, str] = {}
    socket_alias_to_node: dict[str, str] = {}
    for match in re.finditer(
        r"(?m)^\s*([A-Za-z_]\w*)\s*=\s*(?:nodes|tree\.nodes)\.(?:get|new)\(\s*['\"]([^'\"]+)['\"]",
        code,
    ):
        alias_to_node[match.group(1)] = match.group(2)
    for match in re.finditer(
        r"(?m)^\s*([A-Za-z_]\w*)\s*=\s*(?:nodes|tree\.nodes)\[\s*['\"]([^'\"]+)['\"]\s*\]",
        code,
    ):
        alias_to_node[match.group(1)] = match.group(2)
    for match in re.finditer(
        r"(?m)^\s*([A-Za-z_]\w*)\s*=\s*[A-Za-z_]\w*(?:socket|input|translation)[A-Za-z_]*\(\s*([A-Za-z_]\w*)\s*\)",
        code,
        re.IGNORECASE,
    ):
        socket_alias, node_alias = match.group(1), match.group(2)
        node = alias_to_node.get(node_alias)
        if node:
            socket_alias_to_node[socket_alias] = node

    referenced_nodes: list[str] = []
    for pattern in (
        r"(?:nodes|tree\.nodes)\.get\(\s*['\"]([^'\"]+)['\"]",
        r"(?:nodes|tree\.nodes)\[\s*['\"]([^'\"]+)['\"]\s*\]",
    ):
        for name in re.findall(pattern, code):
            if name not in referenced_nodes:
                referenced_nodes.append(name)

    socket_writes: list[dict[str, str]] = []
    for match in re.finditer(
        r"(?m)([A-Za-z_]\w*)\.inputs\[\s*['\"]([^'\"]+)['\"]\s*\]\.default_value\s*=",
        code,
    ):
        alias, socket = match.group(1), match.group(2)
        node = alias_to_node.get(alias, alias)
        socket_writes.append({"node": node, "socket": socket})
        if node not in referenced_nodes and node != alias:
            referenced_nodes.append(node)
    for match in re.finditer(
        r"(?m)([A-Za-z_]\w*)\.default_value(?:\s*\[\s*\d+\s*\])?\s*=",
        code,
    ):
        socket_alias = match.group(1)
        node = socket_alias_to_node.get(socket_alias)
        if not node:
            continue
        item = {"node": node, "socket": "Translation"}
        if item not in socket_writes:
            socket_writes.append(item)
        if node not in referenced_nodes:
            referenced_nodes.append(node)

    default_writes = len(re.findall(r"\.default_value(?:\s*\[\s*\d+\s*\])?\s*=", code))
    nodes_new = len(re.findall(r"\b(?:nodes|tree\.nodes)\.new\(", code))
    links_new = len(re.findall(r"\b(?:links|tree\.links)\.new\(", code))
    links_removed = len(re.findall(r"\b(?:links|tree\.links)\.remove\(", code))
    node_groups_new = len(re.findall(r"\bbpy\.data\.node_groups\.new\(", code))
    interface_writes = len(re.findall(r"\b(?:tree\.)?interface\.(?:new_socket|items_tree|remove|move|copy)\b", code))
    interface_reads = sorted(set(re.findall(r"identifier[\"']?\s*,?\s*(?:None)?\)?\s*==\s*['\"]([^'\"]+)['\"]", code)))
    if not interface_reads:
        interface_reads = sorted(set(re.findall(r"identifier[\"']?[^=\n]*==\s*['\"]([^'\"]+)['\"]", code)))

    disconnect_targets: list[str] = []
    for match in re.finditer(r"\bdisconnect_translation\(\s*([A-Za-z_]\w*)\s*\)", code):
        alias = match.group(1)
        node = alias_to_node.get(alias, alias)
        if node not in disconnect_targets:
            disconnect_targets.append(node)

    node_index = _structural_node_index(structural_memory)
    known_names = set(node_index.keys())
    missing_refs = [name for name in referenced_nodes if known_names and name not in known_names]
    touched_nodes = []
    for item in socket_writes:
        node = item["node"]
        if node not in touched_nodes:
            touched_nodes.append(node)
    for node in disconnect_targets:
        if node not in touched_nodes:
            touched_nodes.append(node)

    node_context: list[dict[str, str]] = []
    mismatches: list[str] = []
    for node in touched_nodes:
        entry = node_index.get(node, {})
        parent = str(entry.get("parent_frame") or "")
        label = str(entry.get("label") or "")
        node_context.append({"node": node, "parent_frame": parent, "label": label})
        node_terms = _node_name_terms(node)
        parent_terms = _node_name_terms(parent + " " + label)
        if node_terms and parent_terms and not (node_terms & parent_terms):
            mismatches.append(
                f"{node} name suggests {', '.join(sorted(node_terms))} "
                f"but parent_frame={parent or '?'} label={label or '?'} suggests {', '.join(sorted(parent_terms))}"
            )

    lower_code = code.lower()
    claims: list[str] = []
    if "nenhuma falange" in lower_code or "falanges nao alteradas" in lower_code or "falanges não alteradas" in lower_code:
        claims.append("draft claims no phalanges/falanges were altered")
        if any("falange" in node.lower() or "falange" in ctx.get("parent_frame", "").lower() for node in touched_nodes for ctx in node_context if ctx.get("node") == node):
            mismatches.append("draft claims no falanges changed, but touched nodes/frames include falange-related names")

    return {
        "referenced_nodes": referenced_nodes[:40],
        "touched_nodes": touched_nodes[:20],
        "socket_writes": socket_writes[:24],
        "disconnect_translation_targets": disconnect_targets[:12],
        "interface_socket_reads": interface_reads[:12],
        "counts": {
            "default_value_writes": default_writes,
            "nodes_new": nodes_new,
            "links_new": links_new,
            "links_removed": links_removed,
            "node_groups_new": node_groups_new,
            "interface_touches": interface_writes,
        },
        "missing_referenced_nodes": missing_refs[:20],
        "touched_node_context": node_context[:20],
        "semantic_mismatches": mismatches[:12],
        "claims": claims[:8],
        "known_node_count": len(known_names),
    }


def _render_failed_draft_evidence_pack(evidence: dict[str, Any], *, max_chars: int = 1800) -> str:
    if not isinstance(evidence, dict) or not evidence:
        return ""
    lines = ["Failed draft static evidence:"]
    counts = evidence.get("counts") if isinstance(evidence.get("counts"), dict) else {}
    if counts:
        lines.append(
            "- operation_counts: "
            + ", ".join(f"{k}={v}" for k, v in counts.items() if int(v or 0) > 0)
        )
    socket_writes = evidence.get("socket_writes") if isinstance(evidence.get("socket_writes"), list) else []
    if socket_writes:
        lines.append(
            "- writes_default_value: "
            + "; ".join(f"{item.get('node')}.{item.get('socket')}" for item in socket_writes[:8] if isinstance(item, dict))
        )
    disconnects = evidence.get("disconnect_translation_targets") if isinstance(evidence.get("disconnect_translation_targets"), list) else []
    if disconnects:
        lines.append("- removes_translation_links_from: " + ", ".join(str(item) for item in disconnects[:8]))
    interface_reads = evidence.get("interface_socket_reads") if isinstance(evidence.get("interface_socket_reads"), list) else []
    if interface_reads:
        lines.append("- reads_interface_sockets: " + ", ".join(str(item) for item in interface_reads[:8]))
    contexts = evidence.get("touched_node_context") if isinstance(evidence.get("touched_node_context"), list) else []
    context_bits = []
    for item in contexts[:8]:
        if not isinstance(item, dict):
            continue
        node = str(item.get("node") or "")
        parent = str(item.get("parent_frame") or "")
        label = str(item.get("label") or "")
        if node:
            context_bits.append(f"{node} parent={parent or '?'} label={label or '?'}")
    if context_bits:
        lines.append("- touched_node_context: " + "; ".join(context_bits))
    missing = evidence.get("missing_referenced_nodes") if isinstance(evidence.get("missing_referenced_nodes"), list) else []
    if missing:
        lines.append("- referenced_nodes_missing_from_structural_memory: " + ", ".join(str(item) for item in missing[:8]))
    mismatches = evidence.get("semantic_mismatches") if isinstance(evidence.get("semantic_mismatches"), list) else []
    if mismatches:
        lines.append("- suspicious_mismatches: " + " | ".join(str(item) for item in mismatches[:5]))
    claims = evidence.get("claims") if isinstance(evidence.get("claims"), list) else []
    if claims:
        lines.append("- draft_claims: " + " | ".join(str(item) for item in claims[:4]))
    text = "\n".join(line for line in lines if line.strip())
    return text[:max_chars]


def _minimum_useful_analysis_response(
    *,
    block_name: str,
    revision: int,
    content: str,
    outcome: str,
    notes: str,
    structural_memory: dict,
) -> str:
    draft_hint = "alterar a arvore alvo a partir do script salvo"
    lowered = str(content or "").lower()
    if "slider" in lowered or "socket" in lowered or "interface" in lowered:
        draft_hint = "conectar parametros/sliders da interface aos nos da arvore"
    if "transform" in lowered or "rotation" in lowered or "rot" in lowered:
        draft_hint = "controlar transforms/rotacoes de partes da mao na arvore"
    memory_hint = ""
    if structural_memory:
        node_count = int(structural_memory.get("node_count", structural_memory.get("total_nodes", 0)) or 0)
        memory_hint = f" Usei a memoria estrutural disponivel ({node_count} nos) como referencia."
    feedback_hint = notes or outcome or "sem feedback de execucao detalhado"
    return (
        f"Draft read: li a versao interna {revision} do draft **{block_name}**.\n"
        f"Intended GN behavior: o draft parece tentar {draft_hint}.{memory_hint}\n"
        f"Likely failure: o ultimo feedback foi `{feedback_hint[:220]}`; a causa precisa ser amarrada ao alvo/socket/link concreto antes de escrever de novo.\n"
        "Direcao de reparo: fazer uma correcao focal no draft atual, preservando a estrutura existente e alterando apenas o trecho diretamente ligado a falha observada.\n"
        "Next step: se voce confirmar, eu escrevo uma nova revisao usando essa direcao concreta."
    )


def _fallback_post_failure_diagnosis(
    *,
    block_name: str,
    revision: int,
    content: str,
    outcome: str,
    notes: str,
    structural_memory: dict,
    failed_draft_source: str,
    reverted: bool,
    evidence_pack_text: str = "",
    evidence: dict[str, Any] | None = None,
) -> str:
    evidence = evidence if isinstance(evidence, dict) else {}
    mismatches = [str(item) for item in (evidence.get("semantic_mismatches") or []) if str(item).strip()]
    concrete_terms = _concrete_evidence_terms(evidence)
    lowered = str(content or "").lower()
    likely_area = "alvo/socket/link"
    if "slider" in lowered or "interface" in lowered or "socket" in lowered:
        likely_area = "interface de sliders, sockets ou links"
    elif "rotation" in lowered or "rot" in lowered or "transform" in lowered:
        likely_area = "transform/rotacao aplicado no alvo errado"
    node_count = int(structural_memory.get("node_count", structural_memory.get("total_nodes", 0)) or 0) if isinstance(structural_memory, dict) else 0
    evidence_bits = [f"revisei a revisao {revision} de {block_name} a partir de {failed_draft_source or 'fonte desconhecida'}"]
    if node_count:
        evidence_bits.append(f"a memoria estrutural disponivel aponta {node_count} nos")
    if evidence_pack_text:
        first_evidence = "; ".join(
            line.strip("- ").strip()
            for line in evidence_pack_text.splitlines()[1:4]
            if line.strip()
        )
        if first_evidence:
            evidence_bits.append(first_evidence[:360])
    if reverted:
        evidence_bits.append("a cena foi marcada como revertida pelo usuario")
    feedback = (notes or outcome or "falha relatada pelo usuario").strip()
    if mismatches:
        primary_mismatch = next((item for item in mismatches if "draft claims no falanges changed" in item.lower()), mismatches[0])
        hypothesis = (
            "A hipotese principal e o conflito detectado na evidencia estatica: "
            f"{primary_mismatch}. Isso combina com o feedback e deve guiar a proxima correcao."
        )
        direction = "Minha direção seria isolar esse conflito e reescrever só a região afetada usando o mismatch como restrição central antes de religar controles."
    else:
        concrete_hint = f" O item concreto mais util e {concrete_terms[0]}." if concrete_terms else ""
        hypothesis = (
            f"A causa mais provavel esta em {likely_area}, com o draft alterando um alvo diferente do pretendido "
            f"ou desconectando parte da cadeia existente.{concrete_hint}"
        )
        direction = "Minha direção seria fazer uma correção focal, preservando a estrutura atual e ajustando apenas os alvos concretos que a evidência apontar."
    return (
        f"Você relatou: {feedback[:260]}.\n\n"
        f"{hypothesis}\n\n"
        f"Evidência usada: {'; '.join(evidence_bits)}. A evidência ainda é parcial porque não houve uma nova leitura ampla da cena neste turno.\n\n"
        f"{direction}\n\n"
        "Quer que eu siga por essa direção na próxima revisão?"
    )
