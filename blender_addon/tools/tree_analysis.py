"""Pure-Python tree analysis helpers extracted from RuntimeDispatcher.

All functions here are free of bpy / Blender state.  They operate only on
plain dicts / lists produced by the capture layer and are safe to call from
tests without a Blender runtime.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Basic text / node helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _confidence(score: float) -> dict[str, Any]:
    score = max(0.0, min(float(score), 1.0))
    if score >= 0.8:
        level = "high"
    elif score >= 0.55:
        level = "medium"
    else:
        level = "low"
    return {"score": round(score, 2), "level": level}


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _contains_name(haystack: str, needle: str) -> bool:
    hay = haystack.lower()
    item = needle.strip().lower()
    return bool(item) and item in hay


def _node_type(node: dict[str, Any]) -> str:
    return str(node.get("bl_idname") or node.get("type") or "")


def _node_label(node: dict[str, Any]) -> str:
    return str(node.get("label") or node.get("name") or "")


def _keyword_hits(text: str, patterns: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for pat in patterns if pat in lowered)


def _tokenize_semantic_text(*values: Any) -> str:
    return " ".join(str(v or "") for v in values).lower()


def _match_keywords(text: str, keywords: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [kw for kw in keywords if kw in lowered]


def _bounded_list(values: Any, *, limit: int = 8) -> list[Any]:
    if not isinstance(values, list):
        return []
    return [item for item in values[:limit]]


# ---------------------------------------------------------------------------
# Phase scoring
# ---------------------------------------------------------------------------

def _phase_scores(nodes: list[dict[str, Any]]) -> dict[str, int]:
    p1 = (
        "primitive", "cube", "sphere", "cylinder", "transform", "join", "bio",
        "biomodel", "anatom", "radius", "ulna", "forearm", "hand", "measure",
        "position", "param", "mesh",
    )
    p2 = ("bezier", "curve", "path", "profile", "spline", "trim", "resample")
    p3 = ("orthosis", "ortese", "shell", "solidify", "thickness", "surface", "boolean", "offset")
    scores = {"phase_1": 0, "phase_2": 0, "phase_3": 0}
    for node in nodes:
        text = f"{node.get('name', '')} {node.get('label', '')} {_node_type(node)}"
        scores["phase_1"] += _keyword_hits(text, p1)
        scores["phase_2"] += _keyword_hits(text, p2)
        scores["phase_3"] += _keyword_hits(text, p3)
    return scores


def _dominant_phase(nodes: list[dict[str, Any]]) -> tuple[str, float, dict[str, int]]:
    scores = _phase_scores(nodes)
    total = sum(scores.values())
    if total <= 0:
        return "unknown", 0.2, scores
    phase = max(scores, key=scores.get)
    best = scores[phase]
    confidence = max(0.25, min(0.95, best / max(total, 1)))
    return phase, round(confidence, 2), scores


def _region_function(name: str, nodes: list[dict[str, Any]]) -> str:
    text = " ".join([name] + [_node_label(n) for n in nodes] + [_node_type(n) for n in nodes]).lower()
    if any(k in text for k in ("bezier", "curve", "path", "profile", "spline")):
        return "path_or_profile_curve_region"
    if any(k in text for k in ("bio", "biomodel", "anatom", "forearm", "radius", "ulna", "hand")):
        return "biomodel_or_anatomical_parameter_region"
    if any(k in text for k in ("join", "merge", "combine")):
        return "geometry_join_or_assembly_region"
    if any(k in text for k in ("output", "viewer")):
        return "output_or_preview_region"
    return "unknown_structural_region"


# ---------------------------------------------------------------------------
# Parameter summary
# ---------------------------------------------------------------------------

def _parameter_summary(params_result: dict[str, Any]) -> dict[str, Any]:
    params = []
    if params_result.get("status") == "success":
        result = params_result.get("result", {}) if isinstance(params_result.get("result"), dict) else {}
        params = result.get("parameters", []) if isinstance(result.get("parameters"), list) else []
    measure_words = (
        "radius", "raio", "diam", "width", "larg", "height", "altura", "length",
        "compr", "espess", "thick", "circum", "scale", "size", "medida",
    )
    position_words = (
        "pos", "offset", "location", "loc", "rotation", "rot", "angle", "x",
        "y", "z", "anchor", "start", "end", "orient",
    )
    measures = []
    positioning = []
    other = []
    for param in params:
        if not isinstance(param, dict):
            continue
        name = str(param.get("name") or param.get("identifier") or "")
        lowered = name.lower()
        entry = {
            "name": name,
            "identifier": param.get("identifier", ""),
            "socket_type": param.get("socket_type", ""),
            "has_value": bool(param.get("has_value", False)),
        }
        if any(word in lowered for word in measure_words):
            measures.append(entry)
        elif any(
            word in lowered if len(word) > 1 else re.search(rf"(^|[_\s.-]){re.escape(word)}($|[_\s.-])", lowered)
            for word in position_words
        ):
            positioning.append(entry)
        else:
            other.append(entry)
    return {
        "parameter_count": len(params),
        "measures": measures,
        "positioning": positioning,
        "other": other[:24],
    }


def _organization_assessment(
    *,
    node_count: int,
    frame_count: int,
    group_count: int,
    unframed_count: int,
) -> dict[str, Any]:
    signals = {
        "node_count": node_count,
        "frame_count": frame_count,
        "group_count": group_count,
        "unframed_count": unframed_count,
    }
    if node_count >= 40 and frame_count == 0 and group_count < 2:
        return {"level": "low_modularity", "signals": signals}
    if node_count >= 80 and unframed_count > node_count * 0.65:
        return {"level": "confusing", "signals": signals}
    if frame_count >= 3 or group_count >= 3:
        return {"level": "good", "signals": signals}
    return {"level": "reasonable", "signals": signals}


# ---------------------------------------------------------------------------
# Semantic phase signals
# ---------------------------------------------------------------------------

def _semantic_phase_signals() -> dict[str, dict[str, Any]]:
    return {
        "phase_1": {
            "label": "biomodel_and_anatomical_parameterization",
            "keywords": (
                "primitive", "cube", "sphere", "cylinder", "transform", "join", "bio",
                "biomodel", "anatom", "forearm", "antebraco", "antebraço", "wrist",
                "punho", "palm", "palma", "metacarp", "metacarpo", "thumb", "polegar",
                "phalange", "falange", "measure", "medida", "radius", "raio", "position",
                "posicion", "param",
            ),
            "evidence_label": "anatomical primitives, joins, transforms, or measurement/position parameters",
        },
        "phase_2": {
            "label": "path_and_profile_curves",
            "keywords": (
                "bezier", "curve", "curva", "path", "caminho", "profile", "perfil",
                "spline", "anchor", "ancor", "resample", "trim",
            ),
            "evidence_label": "Bezier/path/profile curve logic anchored to the biomodel",
        },
        "phase_3": {
            "label": "orthosis_geometry_formation",
            "keywords": (
                "orthosis", "ortese", "órtese", "shell", "casca", "solidify", "thickness",
                "espess", "hole", "furo", "boolean", "offset", "surface", "mesh to volume",
                "extrude",
            ),
            "evidence_label": "orthosis shell, thickness, holes, boolean, or final geometry formation",
        },
    }


# ---------------------------------------------------------------------------
# Region phase classification
# ---------------------------------------------------------------------------

def _classify_region_phase(region: dict[str, Any]) -> dict[str, Any]:
    text = _tokenize_semantic_text(
        region.get("name"),
        region.get("label"),
        region.get("probable_function"),
        " ".join(str(n) for n in region.get("key_nodes", []) if str(n).strip()),
    )
    phase_signals = _semantic_phase_signals()
    scores: dict[str, int] = {}
    matches_by_phase: dict[str, list[str]] = {}
    for phase, spec in phase_signals.items():
        matches = _match_keywords(text, spec["keywords"])
        scores[phase] = len(matches)
        matches_by_phase[phase] = matches[:10]
    total = sum(scores.values())
    if total <= 0:
        phase = str(region.get("local_phase") or "unknown")
        confidence = float(region.get("local_phase_confidence") or 0.2)
        evidence = []
    else:
        phase = max(scores, key=scores.get)
        confidence = max(0.25, min(0.9, scores[phase] / max(total, 1)))
        if phase == "phase_3":
            confidence = min(confidence, 0.65)
        evidence = [
            {
                "phase": ph,
                "score": score,
                "matches": matches_by_phase[ph],
                "signal": phase_signals[ph]["evidence_label"],
            }
            for ph, score in scores.items()
            if score > 0
        ]
    return {
        "name": region.get("name", ""),
        "label": region.get("label", ""),
        "type": region.get("type", ""),
        "phase": phase,
        "confidence": round(confidence, 2),
        "evidence": evidence,
        "probable_function": region.get("probable_function", ""),
    }


# ---------------------------------------------------------------------------
# Clinical parameter roles
# ---------------------------------------------------------------------------

def _clinical_parameter_role(param: dict[str, Any]) -> dict[str, Any]:
    name = _norm_text(param.get("name") or param.get("identifier"))
    text = name.lower()
    measurement_roles = {
        "forearm_length": ("antebraco", "antebraço", "forearm", "compr", "length"),
        "wrist_radius": ("punho", "wrist", "raio", "radius"),
        "elbow_radius": ("cotovelo", "elbow", "raio", "radius"),
        "metacarpal_measure": ("metacarp", "metacarpo"),
        "phalange_measure": ("phalange", "falange"),
        "thumb_measure": ("thumb", "polegar"),
        "width": ("larg", "width"),
        "thickness": ("espess", "thick", "thickness"),
        "diameter": ("diam", "diameter"),
    }
    positioning_roles = {
        "radial_ulnar_deviation": ("radial", "ulnar", "desvio"),
        "wrist_flexion_extension": ("punho", "wrist", "flex", "extens", "extension"),
        "palm_curve": ("palma", "palm", "curva", "curve"),
        "thumb_abduction": ("thumb", "polegar", "abduc", "abduction"),
        "phalange_flexion_extension": ("phalange", "falange", "flex", "extens"),
        "rotation_or_orientation": ("rot", "rotation", "orient", "angle", "angulo", "ângulo"),
        "offset_or_anchor": ("offset", "anchor", "ancora", "âncora", "pos", "location"),
    }

    def _role_match(role_map: dict[str, tuple[str, ...]]) -> tuple[str, list[str]]:
        best_role = ""
        best_hits: list[str] = []
        for role, kws in role_map.items():
            hits = [kw for kw in kws if kw in text]
            if len(hits) > len(best_hits):
                best_role = role
                best_hits = hits
        return best_role, best_hits

    measurement_role, measurement_hits = _role_match(measurement_roles)
    positioning_role, positioning_hits = _role_match(positioning_roles)
    if len(positioning_hits) > len(measurement_hits):
        group = "positioning"
        role = positioning_role
        hits = positioning_hits
    elif measurement_hits:
        group = "measurement"
        role = measurement_role
        hits = measurement_hits
    else:
        group = "uncertain"
        role = "unknown_clinical_role"
        hits = []
    confidence = 0.25 + min(0.65, 0.16 * len(hits))
    return {
        "name": name,
        "identifier": param.get("identifier", ""),
        "socket_type": param.get("socket_type", ""),
        "group": group,
        "role": role,
        "confidence": round(confidence, 2),
        "evidence": hits,
        "has_value": bool(param.get("has_value", False)),
    }


def _likely_regions_for_parameter(role: dict[str, Any], regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text = _tokenize_semantic_text(role.get("name"), role.get("role"))
    out = []
    for region in regions:
        if not isinstance(region, dict):
            continue
        region_text = _tokenize_semantic_text(
            region.get("name"),
            region.get("label"),
            region.get("probable_function"),
            " ".join(str(n) for n in region.get("key_nodes", []) if str(n).strip()),
        )
        name_tokens = [tok for tok in re.split(r"[^a-zA-ZÀ-ÿ0-9]+", text) if len(tok) >= 4]
        hits = [tok for tok in name_tokens if tok.lower() in region_text]
        if hits:
            out.append(
                {
                    "parameter": role.get("name", ""),
                    "region": region.get("name", ""),
                    "region_type": region.get("type", ""),
                    "matches": hits[:8],
                }
            )
    return out[:8]
