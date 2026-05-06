"""Reprocess existing routing_observation events with the corrected
infer_turn_intent + compute_shadow_handler logic and report divergence.

Usage:
    python tools/reprocess_routing_observations.py [<journal.jsonl> ...]

If no path is given, defaults to runtime/journal/sessions/sess-20260427T180409Z-ad39c9fa.jsonl
"""

from __future__ import annotations

import json
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _install_fake_bpy() -> None:
    if "bpy" in sys.modules:
        return
    bpy = types.ModuleType("bpy")
    bpy.app = types.SimpleNamespace(
        handlers=types.SimpleNamespace(persistent=lambda fn: fn, load_post=[], save_post=[]),
        timers=types.SimpleNamespace(register=lambda fn: fn()),
    )
    bpy.data = types.SimpleNamespace(filepath="", texts={}, node_groups={})
    sys.modules["bpy"] = bpy


_install_fake_bpy()

from blender_addon.runtime.routing_obs import (  # noqa: E402
    infer_turn_intent,
    compute_shadow_handler,
)


@dataclass
class _FakeDraft:
    block_name: str = "GN_Agent_Draft"


@dataclass
class _FakeES:
    phase: str = "idle"
    current_draft: Any = None
    draft_revision: int = 0
    last_executed_revision: int = 0
    last_execution_outcome: str = ""
    last_failure: Any = None
    retry_requires_draft_change: bool = False
    drafting_mode: bool = False
    draft_block_name: str = ""
    session_state: str = ""


@dataclass
class _FakeSession:
    execution_state: _FakeES = field(default_factory=_FakeES)


def _make_session(persisted_state: str) -> _FakeSession:
    """Build a fake session that mimics the persisted session_state.

    We use the persisted ``session_state`` value directly (the new
    `infer_session_state` honors a persisted label). We also seed an active
    draft for non-IDLE states so `_has_active_draft_obs` returns True.
    """
    s = _FakeSession()
    s.execution_state.session_state = persisted_state
    if persisted_state in ("DRAFTING", "PENDING_USER_EXECUTION", "REPAIRING", "RESOLVED"):
        s.execution_state.current_draft = _FakeDraft()
        s.execution_state.draft_revision = 1
        if persisted_state == "PENDING_USER_EXECUTION":
            s.execution_state.last_executed_revision = 0
        if persisted_state == "REPAIRING":
            s.execution_state.last_execution_outcome = "error"
        if persisted_state == "RESOLVED":
            s.execution_state.last_executed_revision = 1
            s.execution_state.last_execution_outcome = "success"
    return s


def reprocess_file(path: Path) -> dict:
    obs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("event_type") != "routing_observation":
            continue
        obs.append(e.get("payload", {}))

    rows = []
    for i, p in enumerate(obs, 1):
        msg = p.get("message_preview", "") or ""
        signals = list(p.get("signals", []) or [])
        chosen = str(p.get("turn_class", "") or "")
        old_intent = str(p.get("turn_intent", "") or "")
        old_shadow = str(p.get("handler_by_capability", "") or "")
        old_diverges = bool(p.get("diverges", False))
        state = str(p.get("session_state", "") or "IDLE")

        sess = _make_session(state)
        new_intent = infer_turn_intent(sess, msg, signals, chosen)
        new_shadow = compute_shadow_handler(new_intent, state, chosen)
        new_diverges = new_shadow != chosen

        rows.append({
            "i": i,
            "msg": msg[:80],
            "state": state,
            "chosen": chosen,
            "old_intent": old_intent,
            "new_intent": new_intent,
            "old_shadow": old_shadow,
            "new_shadow": new_shadow,
            "old_diverges": old_diverges,
            "new_diverges": new_diverges,
            "intent_changed": old_intent != new_intent,
        })

    return {"path": str(path), "rows": rows}


def _format_report(result: dict) -> str:
    rows = result["rows"]
    n = len(rows)
    if n == 0:
        return f"{result['path']}: no routing_observation events.\n"

    n_old_div = sum(1 for r in rows if r["old_diverges"])
    n_new_div = sum(1 for r in rows if r["new_diverges"])
    n_changed = sum(1 for r in rows if r["intent_changed"])

    out = []
    out.append(f"=== {result['path']} ===")
    out.append(f"turns: {n}")
    out.append(
        f"diverges: old={n_old_div}/{n} ({100*n_old_div/n:.1f}%) -> "
        f"new={n_new_div}/{n} ({100*n_new_div/n:.1f}%)"
    )
    out.append(f"intent changed: {n_changed}/{n} ({100*n_changed/n:.1f}%)")
    out.append("")
    out.append(
        f"{'#':>3} {'state':22} {'chosen':16} "
        f"{'old_intent':18} {'new_intent':18} {'div?':5} {'msg'}"
    )
    out.append("-" * 130)
    for r in rows:
        marker = ""
        if r["intent_changed"]:
            marker += "*"
        if r["new_diverges"] and not r["old_diverges"]:
            marker += "!"
        out.append(
            f"{r['i']:>3} {r['state']:22} {r['chosen']:16} "
            f"{r['old_intent']:18} {r['new_intent']:18} "
            f"{'Y' if r['new_diverges'] else 'n':5} "
            f"{marker} {r['msg']}"
        )
    return "\n".join(out) + "\n"


def main() -> int:
    paths = [Path(a) for a in sys.argv[1:]] or [
        ROOT / "runtime/journal/sessions/sess-20260427T180409Z-ad39c9fa.jsonl",
    ]
    for p in paths:
        if not p.exists():
            print(f"missing: {p}")
            continue
        result = reprocess_file(p)
        print(_format_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
