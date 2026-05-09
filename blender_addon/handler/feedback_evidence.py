"""Evidence and fallback analysis helpers for draft execution feedback."""

from __future__ import annotations

import ast
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from . import TurnContext

def _message_words(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", str(value or "").lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = "".join(ch if ch.isalnum() else " " for ch in normalized)
    return normalized.split()


def _has_prefix(words: list[str], *prefixes: str) -> bool:
    return any(any(word.startswith(prefix) for prefix in prefixes) for word in words)


def _has_phrase(words: list[str], *phrase_words: str) -> bool:
    size = len(phrase_words)
    if size == 0 or len(words) < size:
        return False
    return any(tuple(words[index:index + size]) == phrase_words for index in range(len(words) - size + 1))


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
    words = _message_words(text)
    keyword_count = sum(1 for word in words if word in {"opcao", "option", "strategy", "estrategia", "caminho"})
    labeled_count = 0
    for line in str(text or "").splitlines():
        stripped = line.strip().lstrip("-* ").strip()
        if not stripped:
            continue
        first = stripped.split(maxsplit=1)[0].strip(").:-").lower()
        if first in {"a", "b", "c", "1", "2", "3"}:
            labeled_count += 1
            continue
        parts = _message_words(stripped)
        if len(parts) >= 2 and parts[0] in {"strategy", "estrategia", "opcao", "option", "caminho"} and parts[1] in {"a", "b", "c", "1", "2", "3"}:
            labeled_count += 1
    return max(keyword_count, labeled_count)


def _analysis_has_diagnosis(text: str) -> bool:
    words = _message_words(text)
    return (
        _has_phrase(words, "likely", "failure")
        or _has_phrase(words, "falha", "provavel")
        or _has_prefix(words, "provavel", "diagnostic", "causa", "falhou", "errad", "problem")
        or "failed" in set(words)
    )


def _analysis_has_failure_reason(text: str) -> bool:
    words = _message_words(text)
    return (
        _has_phrase(words, "nao", "consegui")
        or _has_phrase(words, "sem", "dados")
        or _has_phrase(words, "could", "not")
        or _has_phrase(words, "failure", "reason")
        or _has_prefix(words, "insuficiente", "unable", "motivo")
    )


def _analysis_is_useful(text: str) -> bool:
    body = str(text or "").strip()
    if not body:
        return False
    if len(body) < 80 and _analysis_strategy_count(body) < 1 and not _analysis_has_failure_reason(body):
        return False
    return _analysis_strategy_count(body) >= 1 or _analysis_has_diagnosis(body) or _analysis_has_failure_reason(body)


def _post_failure_strategy_count(text: str) -> int:
    labeled = 0
    for line in str(text or "").splitlines():
        stripped = line.strip().lstrip("-* ").strip()
        if not stripped:
            continue
        first = stripped.split(maxsplit=1)[0].strip(").:-").lower()
        if first in {"a", "b"}:
            labeled += 1
    return max(labeled, _analysis_strategy_count(text))


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


def _attribute_chain(node: ast.AST) -> list[str]:
    parts: list[str] = []
    current: ast.AST | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return list(reversed(parts))


def _is_nodes_expr(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "nodes"
    if isinstance(node, ast.Attribute):
        return node.attr == "nodes" or _is_nodes_expr(node.value)
    return False


def _string_constant(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _subscript_key(node: ast.AST) -> str:
    return _string_constant(node.slice) if isinstance(node, ast.Subscript) else ""


def _is_default_value_target(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute) and node.attr == "default_value":
        return True
    if isinstance(node, ast.Subscript):
        return _is_default_value_target(node.value)
    return False


def _extract_failed_draft_static_evidence(content: str, structural_memory: dict[str, Any]) -> dict[str, Any]:
    code = str(content or "")
    alias_to_node: dict[str, str] = {}
    socket_alias_to_node: dict[str, str] = {}
    referenced_nodes: list[str] = []
    socket_writes: list[dict[str, str]] = []
    disconnect_targets: list[str] = []
    interface_reads: list[str] = []
    default_writes = 0
    nodes_new = 0
    links_new = 0
    links_removed = 0
    node_groups_new = 0
    interface_writes = 0

    def add_unique(items: list[str], value: str) -> None:
        text = str(value or "").strip()
        if text and text not in items:
            items.append(text)

    try:
        parsed = ast.parse(code)
    except SyntaxError:
        parsed = ast.Module(body=[], type_ignores=[])

    class StaticEvidenceVisitor(ast.NodeVisitor):
        def visit_Assign(self, node: ast.Assign) -> Any:
            for target in node.targets:
                self._record_assignment(target, node.value)
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
            if node.value is not None:
                self._record_assignment(node.target, node.value)
            self.generic_visit(node)

        def _record_assignment(self, target: ast.AST, value: ast.AST) -> None:
            nonlocal default_writes
            if isinstance(target, ast.Name):
                node_name = self._node_name_from_expr(value)
                if node_name:
                    alias_to_node[target.id] = node_name
                socket_node = self._socket_node_from_expr(value)
                if socket_node:
                    socket_alias_to_node[target.id] = socket_node
            for sub in ast.walk(target):
                if _is_default_value_target(sub):
                    default_writes += 1
                    self._record_default_write(sub)
                    break

        def visit_Call(self, node: ast.Call) -> Any:
            nonlocal nodes_new, links_new, links_removed, node_groups_new, interface_writes
            chain = _attribute_chain(node.func)
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "new" and _is_nodes_expr(node.func.value):
                    nodes_new += 1
                elif node.func.attr == "new" and self._is_links_expr(node.func.value):
                    links_new += 1
                elif node.func.attr == "remove" and self._is_links_expr(node.func.value):
                    links_removed += 1
                elif chain[-4:] == ["bpy", "data", "node_groups", "new"]:
                    node_groups_new += 1
                elif node.func.attr in {"new_socket", "remove", "move", "copy"} and self._is_interface_expr(node.func.value):
                    interface_writes += 1
            if isinstance(node.func, ast.Name) and node.func.id == "disconnect_translation" and node.args:
                alias = node.args[0].id if isinstance(node.args[0], ast.Name) else ""
                add_unique(disconnect_targets, alias_to_node.get(alias, alias))
            self.generic_visit(node)

        def visit_Compare(self, node: ast.Compare) -> Any:
            operands = [node.left, *node.comparators]
            has_identifier = any(
                self._is_identifier_expr(item)
                for item in operands
            )
            if has_identifier:
                for item in operands:
                    add_unique(interface_reads, _string_constant(item))
            self.generic_visit(node)

        @staticmethod
        def _is_identifier_expr(node: ast.AST) -> bool:
            if isinstance(node, ast.Attribute):
                return node.attr == "identifier"
            if isinstance(node, ast.Subscript):
                return _subscript_key(node) == "identifier"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
                return len(node.args) >= 2 and _string_constant(node.args[1]) == "identifier"
            return False

        @staticmethod
        def _is_links_expr(node: ast.AST) -> bool:
            if isinstance(node, ast.Name):
                return node.id == "links"
            if isinstance(node, ast.Attribute):
                return node.attr == "links"
            return False

        @staticmethod
        def _is_interface_expr(node: ast.AST) -> bool:
            if isinstance(node, ast.Name):
                return node.id == "interface"
            if isinstance(node, ast.Attribute):
                return node.attr == "interface"
            return False

        def _node_name_from_expr(self, node: ast.AST) -> str:
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"get", "new"} and _is_nodes_expr(node.func.value) and node.args:
                    name = _string_constant(node.args[0])
                    add_unique(referenced_nodes, name)
                    return name
            if isinstance(node, ast.Subscript) and _is_nodes_expr(node.value):
                name = _subscript_key(node)
                add_unique(referenced_nodes, name)
                return name
            return ""

        def _socket_node_from_expr(self, node: ast.AST) -> str:
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or not node.args:
                return ""
            func_name = node.func.id.lower()
            if not any(term in func_name for term in ("socket", "input", "translation")):
                return ""
            first = node.args[0]
            alias = first.id if isinstance(first, ast.Name) else ""
            return alias_to_node.get(alias, "")

        def _record_default_write(self, node: ast.AST) -> None:
            target = node
            while isinstance(target, ast.Subscript):
                target = target.value
            if not isinstance(target, ast.Attribute) or target.attr != "default_value":
                return
            owner = target.value
            if isinstance(owner, ast.Subscript) and isinstance(owner.value, ast.Attribute) and owner.value.attr == "inputs":
                alias_node = owner.value.value
                alias = alias_node.id if isinstance(alias_node, ast.Name) else ""
                socket = _subscript_key(owner)
                node_name = alias_to_node.get(alias, alias)
                socket_writes.append({"node": node_name, "socket": socket})
                if node_name and node_name != alias:
                    add_unique(referenced_nodes, node_name)
                return
            if isinstance(owner, ast.Name):
                node_name = socket_alias_to_node.get(owner.id, "")
                if node_name:
                    item = {"node": node_name, "socket": "Translation"}
                    if item not in socket_writes:
                        socket_writes.append(item)
                    add_unique(referenced_nodes, node_name)

    StaticEvidenceVisitor().visit(parsed)
    interface_reads = sorted(interface_reads)

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
