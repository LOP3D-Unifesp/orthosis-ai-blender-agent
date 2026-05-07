"""Classifiers for user feedback after running a drafted script."""

from __future__ import annotations

import re


_EXECUTION_DIAGNOSIS_RE = re.compile(
    r"\b("
    r"erro|falh|deu\s+errado|n[aÃ£]o\s+(deu|funcionou|foi)|nada\s+aconteceu|"
    r"sem\s+efeito|ctrl\s*\+?\s*z|desfiz|revert|apagou|sumiu|problemas?|sliders?.*n[aÃ£]o|"
    r"por\s+que|porque|o\s+que\s+.*errad|n[aÃ£]o\s+esta\s+funcionando|why|wrong|failed|nothing\s+happened|no\s+effect"
    r")\b",
    re.IGNORECASE,
)


def _classify_execution_feedback(message: str) -> tuple[str, bool]:
    msg = (message or "").lower()
    reverted = bool(re.search(r"\b(desfiz|undo|ctrl\s*\+?\s*z|control\s*\+?\s*z|voltei\s+atr[aÃ¡]s|reverti|revertido|reverted)\b", msg))
    if reverted:
        return "reverted_by_user", True
    if re.search(r"\b(nada\s+aconteceu|sem\s+efeito|no\s+effect)\b", msg):
        return "executed_no_effect", False
    if re.search(r"\b(nenhum|nenhuma|none)\b.*\b(slider|sliders|controle|controles)\b.*\b(funcion|mex|move|alter|respond)", msg):
        return "executed_no_effect", False
    if re.search(r"\b(slider|sliders|controle|controles)\b.*\b(nao|n[aã]o)\b.*\b(funcion|mex|move|alter|respond)", msg):
        return "executed_no_effect", False
    if re.search(r"\b(nao|n[aã]o)\b.*\b(slider|sliders|controle|controles)\b.*\b(funcion|mex|move|alter|respond)", msg):
        return "executed_no_effect", False
    if re.search(r"\b(deu\s+errado|(nao|n[aã]o)\s+deu\s+certo|n[aÃ£]o\s+funcionou|falhou|erro|failed|wrong|sumiu|sumiram|sumindo|desapareceu|desapareceram|apagou)\b", msg):
        return "executed_failed", False
    if re.search(r"\b(parcial|partial|metade|incomplet[oa])\b", msg):
        return "executed_partial_failure", False
    return "executed", False
