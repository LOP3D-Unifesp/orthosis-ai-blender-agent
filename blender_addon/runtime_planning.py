"""Planning and intent utilities extracted from AgentRuntime."""

from __future__ import annotations

import re
import time
import unicodedata
from typing import Any
from uuid import uuid4


GN_KEYWORDS = re.compile(r"geometry\s*nodes?|node\s*tree|node\s*group|gn\b|geonodes|no\b|nos\b", re.IGNORECASE)
DIAGNOSIS_KEYWORDS = re.compile(r"problema|erro|bug|quebr|estranh|nao funciona|wrong|broken|diagnost", re.IGNORECASE)
ANALYSIS_REQUEST_KEYWORDS = re.compile(
    r"analis|analisa|analisar|olhada|inspec|revis|examinar|propor uma maneira|por etapas|qual contexto",
    re.IGNORECASE,
)
MUTATION_KEYWORDS = re.compile(r"muda|alter|cria|adicion|conect|desconect|remove|delet|set|define|ajust", re.IGNORECASE)
PARAMETER_ADJUSTMENT_KEYWORDS = re.compile(
    r"raio|raios|circunfer|diametr|espessur|largur|altura|compriment|valor|independente|independentes|separad|"
    r"controla|controlar|control|extremidad",
    re.IGNORECASE,
)
VISUAL_KEYWORDS = re.compile(r"screenshot|viewport|visual|imagem|foto|captura", re.IGNORECASE)
TREE_NAME_PATTERN = re.compile(r"(?:tree|arvore|node group)\s*[:=]?\s*['\"]?([A-Za-z0-9_. -]+)['\"]?", re.IGNORECASE)
EXPLICIT_READ_KEYWORDS = re.compile(r"inspec|diagnost|analis|resum|liste|mostre|valid|verif|check|estado da cena|scene summary|tree structure|node context|contexto", re.IGNORECASE)
SIMPLE_CONSTRUCTIVE_KEYWORDS = re.compile(r"criar|create|novo|new|do zero|from scratch|setup|pass-?through|group input|group output", re.IGNORECASE)
CONSTRUCTIVE_COMMAND_PREFIXES = re.compile(
    r"^\s*(come[cç]a|comeca|inicia|faz|fa[cç]a|gera|monta|prepara|cria|crie|adiciona|adicione|usa|use|designa)\b",
    re.IGNORECASE,
)
CONSTRUCTIVE_OBJECT_HINTS = re.compile(
    r"\b(cubo|cube|esfera|sphere|cilindro|cylinder|cone|torus|objeto|object|host|modifier|modificador|"
    r"geometry\s*nodes?|gn\b|geonodes|arvore|árvore|tree|curva|bezier|perfil|mesh|malha|n[oó]|nos|nós)\b",
    re.IGNORECASE,
)
AMBIGUITY_KEYWORDS = re.compile(r"nao sei|descobre|investiga|qualquer|tanto faz|something is wrong|algo estranho", re.IGNORECASE)
RISKY_REQUEST_HINTS = re.compile(r"execute_code|python|script|override|force|forcar|risky|arriscad", re.IGNORECASE)
ORGANIZATION_KEYWORDS = re.compile(r"organiza|organizar|frame|layout|legibilidade|rename|renomear|group node|agrupar|hierarquia", re.IGNORECASE)
MANUAL_ROUNDTRIP_KEYWORDS = re.compile(r"ja criei|j\W*criei|criei manualmente|criei os nos|eu adicionei|manualmente", re.IGNORECASE)
NODE_NAME_CANDIDATE = re.compile(r"[A-Za-z][A-Za-z0-9_ .-]{2,40}")
BEZIER_KEYWORDS = re.compile(r"bezier|curve|curva", re.IGNORECASE)
HOST_KEYWORDS = re.compile(r"host|objeto|object|modifier|modificador", re.IGNORECASE)
SCENE_CLEANUP_KEYWORDS = re.compile(
    r"\b(?:limpe a cena|limpar a cena|apague a cena|apaga a cena|apague tudo|apaga tudo|delete everything|clean scene|"
    r"esquece isso|esqueca isso|esqueça isso|pare|stop|cancele isso|cancel this)\b",
    re.IGNORECASE,
)
CONTINUATION_HINTS = re.compile(
    r"continua|continuar|continue|continuacao|continuação|retom|mesma arvore|mesmo objeto|nessa|nesta|nesse|"
    r"proxima etapa|próxima etapa|agora faça|agora faz|depois disso|seguinte",
    re.IGNORECASE,
)
NEW_START_HINTS = re.compile(
    r"do zero|from scratch|novo host|host novo|nova cena|cena nova|novo objeto|comecar do zero|começar do zero|"
    r"nova arvore|nova árvore",
    re.IGNORECASE,
)
OVERRIDE_HINTS = re.compile(
    r"em vez disso|ao inves|ao invés|muda o objetivo|novo objetivo|agora quero|desconsidere o anterior|"
    r"troca o objetivo|ignora o anterior",
    re.IGNORECASE,
)
MANUAL_CONTEXT_HINTS = re.compile(
    r"screenshot|print|imagem|foto|viewport|manual|eu descrevo|vou descrever|te mando|posso mandar",
    re.IGNORECASE,
)
GREETING_KEYWORDS = re.compile(
    r"^\s*(oi|ol[aá]|opa|e ai|e aí|hello|hey|bom dia|boa tarde|boa noite|vamos conversar|quero conversar|"
    r"podemos conversar|so conversar|s[oó] conversar|tudo bem)\s*[!.?]*\s*$",
    re.IGNORECASE,
)
CONVERSATION_ONLY_HINTS = re.compile(
    r"^\s*(vamos conversar|quero conversar|podemos conversar|so conversar|s[oó] conversar|"
    r"quero pensar junto|vamos pensar)\s*[!.?]*\s*$",
    re.IGNORECASE,
)


def _intent_text(text: str) -> str:
    """Lowercase + accent-fold user text for intent-only matching."""
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    asciiish = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", asciiish.lower()).strip()


def is_scene_wide_gn_inspection_request(message: str) -> bool:
    """Return True for read-only requests about all GN-bearing scene objects/trees."""
    text = _intent_text(message)
    if not text:
        return False

    has_scene_scope = any(
        token in text
        for token in (
            "cena", "scene", "objetos", "objects", "todos", "todas",
            "all gn", "scene-wide", "scene wide",
        )
    )
    has_gn_surface = any(
        token in text
        for token in (
            "gn", "geometry nodes", "geonodes", "arvore", "arvores",
            "rvore", "rvores",
            "tree", "trees", "node group", "node groups",
        )
    )
    has_read_intent = any(
        token in text
        for token in (
            "quais", "qual", "listar", "lista", "liste", "mostrar", "mostre",
            "ler", "leitura", "testar", "inspec", "ver", "verificar",
            "conferir", "read", "inspect", "list", "show", "which", "what",
        )
    )

    if re.search(r"\bquais?\s+(arvores|trees|objetos|objects)\b", text) and has_scene_scope:
        return True
    if re.search(r"\bobjetos?\s+(com|que\s+(recebem|tem|contem))\s+(gn|geometry nodes|geonodes)\b", text):
        return True
    if "leitura de objetos" in text and ("arvore" in text or "gn" in text or "geometry nodes" in text):
        return True
    return has_scene_scope and has_gn_surface and has_read_intent


def is_structured_operational_followup(message: str) -> bool:
    """Return True for short structured replies that provide operational context."""
    raw = str(message or "").strip()
    text = _intent_text(raw)
    if not text:
        return False

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    has_numbered_item = bool(re.search(r"(?m)^\s*\d+\s*[\).:-]", raw))
    structured = has_numbered_item or len(lines) >= 2
    if not structured:
        return False

    starts_acceptance = bool(re.match(r"^\s*(isso|sim|ok|certo|perfeito|beleza|pode)\b", text))
    grants_progress = any(
        token in text
        for token in (
            "pode seguir", "pode continuar", "pode ir", "siga", "seguir",
            "como achar melhor", "use esses parametros", "usar esses parametros",
            "esses parametros", "estes parametros",
        )
    )
    domain_context = any(
        token in text
        for token in (
            "parametro", "parametros", "grau", "graus", "curva", "medida",
            "raio", "largura", "comprimento", "espessura", "palma", "punho",
            "antebraco", "metacarpo", "falange", "polegar", "flexao",
            "extensao", "radial", "ulnar",
        )
    )
    return domain_context and (starts_acceptance or grants_progress)


def is_natural_continuation_request(message: str) -> bool:
    """Return True for natural resume/proceed phrases that need ongoing context."""
    text = _intent_text(message)
    if not text:
        return False
    if re.search(r"\b(tente|tentar|pode|consegue|vamos|bora)?\s*(continuar|continue|continua|prosseguir|prossiga|retomar|retoma)\b", text):
        return True
    if re.search(r"\b(pode|consegue|vamos|bora)?\s*(seguir|siga|esguir)\b", text):
        return True
    return any(
        phrase in text
        for phrase in (
            "consegue prosseguir",
            "prosseguir de onde",
            "continuar de onde",
            "continue de onde",
            "pode seguir",
            "pode esguir",
            "pode prosseguir",
            "pode continuar",
            "tente continuar",
            "segue de onde",
            "retoma de onde",
            "retomar de onde",
            "go on from",
            "continue where",
            "keep going",
        )
    )


def is_pending_plan_status_question(message: str) -> bool:
    """Return True for questions about the currently staged plan/approval state."""
    text = _intent_text(message)
    if not text:
        return False
    has_plan_state = any(
        phrase in text
        for phrase in (
            "cade", "cadê", "mostrar", "mostra", "executar ja", "executar agora",
            "ja tem o plano", "tem plano", "plano pronto", "aprovar agora",
            "e pra aprovar", "é pra aprovar", "aprovar ja", "aprovar já",
            "vai me mostrar", "me mostrar", "mostrou", "onde esta o plano",
            "where is it", "show me the plan", "execute now", "approve now",
        )
    )
    has_question_shape = "?" in str(message or "") or any(
        token in text for token in ("cade", "cadê", "onde", "mostrar", "aprovar", "executar")
    )
    return has_plan_state and has_question_shape

MUTATION_TOOLS = {
    "apply_simulator_payload", "rename_object", "move_to_collection", "execute_code",
}
BROAD_READ_TOOLS = {"get_scene_summary"}
FOCAL_READ_TOOLS = {"get_node_context", "get_selected_nodes_context", "get_active_frame_context", "get_local_subgraph_context", "get_changes_since_last_turn"}
CONTEXT_DISCOVERY_TOOLS = {
    "get_gn_hosts", "get_tree_parameters", "get_scene_summary", "get_node_context",
    "get_selected_nodes_context", "get_active_frame_context", "get_local_subgraph_context", "get_changes_since_last_turn", "capture_screenshot",
}

PLAN_TYPE_CONTEXT = "context_plan"
PLAN_TYPE_EXECUTION = "execution_plan"
PLAN_MODE_CONTEXT_QUESTION_ONLY = "question_only"
PLAN_MODE_CONTEXT_TOOLS = "tool_context"
PLAN_MODE_EXECUTION = "execution"


def normalize_plan_type(plan_type: str | None) -> str:
    text = str(plan_type or "").strip().lower()
    if text in {"", "execution", PLAN_TYPE_EXECUTION}:
        return PLAN_TYPE_EXECUTION
    if text in {"context", PLAN_TYPE_CONTEXT}:
        return PLAN_TYPE_CONTEXT
    return PLAN_TYPE_EXECUTION


def is_context_plan(plan_type: str | None) -> bool:
    return normalize_plan_type(plan_type) == PLAN_TYPE_CONTEXT


def is_execution_plan(plan_type: str | None) -> bool:
    return normalize_plan_type(plan_type) == PLAN_TYPE_EXECUTION


def normalize_plan_mode(plan_mode: str | None, *, plan_type: str | None = None) -> str:
    text = str(plan_mode or "").strip().lower()
    normalized_type = normalize_plan_type(plan_type)
    if normalized_type == PLAN_TYPE_EXECUTION:
        return PLAN_MODE_EXECUTION
    if text in {"question_only", PLAN_MODE_CONTEXT_QUESTION_ONLY}:
        return PLAN_MODE_CONTEXT_QUESTION_ONLY
    if text in {"tool_context", PLAN_MODE_CONTEXT_TOOLS}:
        return PLAN_MODE_CONTEXT_TOOLS
    return PLAN_MODE_CONTEXT_TOOLS if normalized_type == PLAN_TYPE_CONTEXT else PLAN_MODE_EXECUTION


def is_question_only_context_plan(plan_mode: str | None, *, plan_type: str | None = None) -> bool:
    return normalize_plan_mode(plan_mode, plan_type=plan_type) == PLAN_MODE_CONTEXT_QUESTION_ONLY


def is_tool_context_plan(plan_mode: str | None, *, plan_type: str | None = None) -> bool:
    return normalize_plan_mode(plan_mode, plan_type=plan_type) == PLAN_MODE_CONTEXT_TOOLS


# ---------------------------------------------------------------------------
# Phase 5 note: ~1400 lines of planning-pipeline functions removed here.
# Dead functions (detect_intent, classify_task, assess_continuity,
# build_plan_preview, build_plan_gate, build_plan_stages, etc.) were only
# called from agent_runtime methods deleted in Phase 4 and tombstoned modules
# (runtime_execution.py, execution_postprocess.py, runtime_governance.py).
# The helpers below are the only live exports of this module.
# ---------------------------------------------------------------------------

def extract_tree_name(tool_input: dict[str, Any]) -> str:
    for key in ("tree_name", "target_tree"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_node_name(tool_input: dict[str, Any]) -> str:
    for key in ("node_name", "node", "name", "from_node", "old_name", "object_name"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_manual_roundtrip(user_message: str) -> dict[str, Any]:
    text = str(user_message or "").strip()
    detected = bool(MANUAL_ROUNDTRIP_KEYWORDS.search(text))
    node_candidates: list[str] = []
    if detected:
        for token in NODE_NAME_CANDIDATE.findall(text):
            cleaned = token.strip()
            if cleaned and cleaned.lower() not in {"geometry nodes", "group input", "group output", "node", "nodes"}:
                node_candidates.append(cleaned)
            if len(node_candidates) >= 8:
                break
    return {"detected": detected, "nodes": node_candidates, "note": text[:220] if detected else ""}


def build_structural_index_entry(tree_payload: dict[str, Any]) -> dict[str, Any]:
    nodes = tree_payload.get("nodes", []) if isinstance(tree_payload.get("nodes"), list) else []
    links = tree_payload.get("links", []) if isinstance(tree_payload.get("links"), list) else []
    interface = tree_payload.get("interface", {}) if isinstance(tree_payload.get("interface"), dict) else {}
    frames = [str(node.get("name", "")) for node in nodes if isinstance(node, dict) and node.get("type") == "NodeFrame"]
    group_nodes = [str(node.get("name", "")) for node in nodes if isinstance(node, dict) and str(node.get("type", "")).lower() in {"geometrynodegroup", "nodegroup"}]
    known_parameters = []
    if isinstance(interface.get("inputs"), list):
        known_parameters = [str(inp.get("name", "")) for inp in interface.get("inputs", []) if isinstance(inp, dict)]
    return {
        "tree_name": str(tree_payload.get("name", "")),
        "node_count": int(tree_payload.get("node_count", len(nodes)) or 0),
        "link_count": len(links),
        "frames": [name for name in frames if name],
        "group_nodes": [name for name in group_nodes if name],
        "key_nodes": [str(node.get("name", "")) for node in nodes[:40] if isinstance(node, dict) and str(node.get("name", "")).strip()],
        "known_parameters": [name for name in known_parameters if name],
        "updated_at": int(time.time()),
    }
