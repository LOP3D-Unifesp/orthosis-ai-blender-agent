"""Project-root resolution for the Blender add-on runtime.

Resolution prefers an explicit product-root preference when available, rejects
the old non-v2 sibling checkout during the transition, and falls back to the
folder that ships the add-on only when no better workspace root is known.
"""

from __future__ import annotations

import os
from pathlib import Path


_REPO_MARKERS = ("blender_addon", "knowledge")
_ADDON_IDS = ("blender_addon", "orthosis_mcp_bridge")


def _looks_like_project_root(path: Path) -> bool:
    return all((path / marker).exists() for marker in _REPO_MARKERS)


def canonical_project_root() -> Path:
    """Return the repository root that contains this add-on package."""
    return Path(__file__).resolve().parent.parent


def _legacy_root_name(canonical: Path) -> str:
    name = canonical.name
    return name[: -len("_v2")] if name.endswith("_v2") else ""


def _is_rejected_legacy_root(candidate: Path, canonical: Path) -> bool:
    legacy_name = _legacy_root_name(canonical)
    return bool(legacy_name) and candidate.name == legacy_name


def _candidate_roots() -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []

    for env_name in ("ORTHOSIS_PROJECT_ROOT", "BLENDER_ORTHOSIS_PROJECT_ROOT"):
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            candidates.append(("env", Path(env_value)))

    try:
        import bpy  # type: ignore

        for addon_id in _ADDON_IDS:
            addon = bpy.context.preferences.addons.get(addon_id)
            if not addon or not hasattr(addon, "preferences"):
                continue
            pref_path = str(getattr(addon.preferences, "project_root_path", "") or "").strip()
            if pref_path:
                candidates.append(("preference", Path(pref_path)))
    except Exception:
        pass

    candidates.append(("canonical", canonical_project_root()))
    return candidates


def _candidate_score(source: str, candidate: Path) -> tuple[int, int, int]:
    score = 0
    if source == "preference":
        score += 100
    elif source == "env":
        score += 90
    else:
        score += 50

    if candidate.name.endswith("_v2"):
        score += 30

    lower_parts = {part.lower() for part in candidate.parts}
    if {"scripts", "addons"}.issubset(lower_parts):
        score -= 20

    return (score, len(candidate.parts), len(str(candidate)))


def _is_addon_install_path(candidate: Path) -> bool:
    lower_parts = {part.lower() for part in candidate.parts}
    return {"scripts", "addons"}.issubset(lower_parts)


def resolve_project_root() -> Path:
    """Return the best valid project root for runtime/session persistence."""
    canonical = canonical_project_root().resolve()
    best: Path | None = None
    best_score: tuple[int, int, int] | None = None

    for source, candidate in _candidate_roots():
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        if not _looks_like_project_root(resolved):
            continue
        if _is_rejected_legacy_root(resolved, canonical):
            continue
        score = _candidate_score(source, resolved)
        if best is None or score > best_score:
            best = resolved
            best_score = score

    if best is not None:
        return best
    return canonical


def sync_addon_project_root_preference() -> Path:
    """Mirror the resolved runtime root into Blender add-on preferences."""
    resolved = resolve_project_root()
    canonical = canonical_project_root().resolve()
    try:
        import bpy  # type: ignore

        for addon_id in _ADDON_IDS:
            addon = bpy.context.preferences.addons.get(addon_id)
            if not addon or not hasattr(addon, "preferences"):
                continue
            prefs = addon.preferences
            current = str(getattr(prefs, "project_root_path", "") or "").strip()
            target = str(resolved)
            keep_current = False
            if current:
                try:
                    current_path = Path(current).expanduser().resolve()
                except Exception:
                    current_path = None
                if current_path is not None:
                    keep_current = (
                        _looks_like_project_root(current_path)
                        and not _is_rejected_legacy_root(current_path, canonical)
                        and not _is_addon_install_path(current_path)
                    )
            if _is_addon_install_path(resolved):
                continue
            if keep_current and current == target:
                continue
            if current != target:
                setattr(prefs, "project_root_path", target)
    except Exception:
        pass
    return resolved
