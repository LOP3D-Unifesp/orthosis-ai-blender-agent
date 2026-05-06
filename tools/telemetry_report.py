"""Developer telemetry report for blend_IA_ort.

Reads journal JSONL files from ``blender_addon/runtime/journal/sessions/``
and prints aggregate metrics useful for stabilization diagnostics:

  - Truncation rate per turn class
  - Continuation usage and failure rate
  - Discovery skip reasons
  - Session-memory cleanup frequency
  - Round-count distribution by turn class

Usage (from project root):
    python tools/telemetry_report.py
    python tools/telemetry_report.py --journal path/to/journal/sessions

No runtime dependencies beyond the standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_events(sessions_dir: Path) -> list[dict]:
    """Read all JSONL events from every session file in *sessions_dir*."""
    events: list[dict] = []
    for path in sorted(sessions_dir.glob("*.jsonl")):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        except OSError:
            pass
    return events


def _get(event: dict, *keys: str, default=None):
    """Safely traverse a nested dict."""
    obj = event
    for key in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key, default)
    return obj


# ---------------------------------------------------------------------------
# Metric collectors
# ---------------------------------------------------------------------------

def _collect_truncation(events: list[dict]) -> dict:
    """Truncation events per turn class."""
    truncated_by_class: Counter = Counter()
    handler_by_class: Counter = Counter()

    for ev in events:
        etype = str(ev.get("event_type") or "")
        payload = ev.get("payload") or {}
        tc = str(payload.get("turn_class") or "")
        if etype == "handler_completed":
            if tc:
                handler_by_class[tc] += 1
        if etype in ("truncation_applied", "response_truncated", "max_tokens_hit"):
            if tc:
                truncated_by_class[tc] += 1

    result: dict[str, dict] = {}
    all_classes = set(handler_by_class) | set(truncated_by_class)
    for tc in sorted(all_classes):
        total = handler_by_class.get(tc, 0)
        trunc = truncated_by_class.get(tc, 0)
        rate = f"{100*trunc/total:.1f}%" if total else "n/a"
        result[tc] = {"handler_completions": total, "truncations": trunc, "rate": rate}
    return result


def _collect_continuation(events: list[dict]) -> dict:
    """Continuation dispatch, degradation, and delegated turns."""
    dispatched = 0
    degraded = 0
    degraded_reasons: Counter = Counter()

    for ev in events:
        etype = str(ev.get("event_type") or "")
        if etype == "continuation_dispatched":
            dispatched += 1
        elif etype == "continuation_degraded":
            degraded += 1
            reason = str(_get(ev, "payload", "reason") or "unknown")
            degraded_reasons[reason] += 1

    return {
        "dispatched": dispatched,
        "degraded": degraded,
        "degraded_reasons": dict(degraded_reasons),
    }


def _collect_discovery(events: list[dict]) -> dict:
    """Discovery phase skip reasons and run counts."""
    skipped_reasons: Counter = Counter()
    ran = 0

    for ev in events:
        etype = str(ev.get("event_type") or "")
        if etype == "discovery_phase_skipped":
            reason = str(_get(ev, "payload", "reason") or "unknown")
            skipped_reasons[reason] += 1
        elif etype == "discovery_phase_done":
            ran += 1

    return {
        "ran": ran,
        "skipped": dict(skipped_reasons),
    }


def _collect_session_memory(events: list[dict]) -> dict:
    """session_memory use/update/cleanup events."""
    cleanup_count = 0
    used_count = 0
    updated_count = 0
    stale_cleared_count = 0

    for ev in events:
        etype = str(ev.get("event_type") or "")
        if etype in ("session_memory_cleanup", "session_memory_cleared", "session_memory_trimmed"):
            cleanup_count += 1
        if etype == "session_memory_stale_cleared":
            stale_cleared_count += 1
        if etype == "session_memory_used":
            used_count += 1
        if etype == "session_memory_updated":
            updated_count += 1

    return {
        "cleanup_events": cleanup_count,
        "stale_cleared_events": stale_cleared_count,
        "used_events": used_count,
        "updated_events": updated_count,
    }


def _collect_round_distribution(events: list[dict]) -> dict:
    """Tool-call distribution broken down by turn class."""
    # The agent_loop logs a 'handler_completed' event with tool_calls_made count.
    # We approximate round count from tool_calls_made (each tool call ≈ 1 round).
    rounds_by_class: dict[str, list[int]] = defaultdict(list)
    current_turn_tools = 0

    for ev in events:
        etype = str(ev.get("event_type") or "")
        if etype == "tool_dispatched":
            current_turn_tools += 1
            continue
        if etype == "handler_completed":
            payload = ev.get("payload") or {}
            tc = str(payload.get("turn_class") or "")
            if tc:
                rounds_by_class[tc].append(current_turn_tools)
            current_turn_tools = 0

    result: dict[str, dict] = {}
    for tc in sorted(rounds_by_class):
        counts = rounds_by_class[tc]
        result[tc] = {
            "samples": len(counts),
            "min": min(counts),
            "max": max(counts),
            "avg": round(sum(counts) / len(counts), 1),
        }
    return result


def _collect_goal_outcomes(events: list[dict]) -> dict:
    """Goal completion vs error outcomes."""
    outcomes: Counter = Counter()
    elapsed_ms_by_class: dict[str, list[int]] = defaultdict(list)

    for ev in events:
        etype = str(ev.get("event_type") or "")
        payload = ev.get("payload") or {}
        if etype == "handler_completed":
            tc = str(payload.get("turn_class") or "")
            elapsed = int(payload.get("elapsed_ms") or 0)
            phase = str(payload.get("phase_transition") or "")
            if phase == "failed":
                outcomes["failed"] += 1
            elif tc:
                outcomes["completed"] += 1
            if tc and elapsed:
                elapsed_ms_by_class[tc].append(elapsed)

    latency: dict[str, str] = {}
    for tc, vals in elapsed_ms_by_class.items():
        avg_s = round(sum(vals) / len(vals) / 1000, 2)
        latency[tc] = f"{avg_s}s avg over {len(vals)} turns"

    return {"outcomes": dict(outcomes), "latency_by_class": latency}


# ---------------------------------------------------------------------------
# Report renderer
# ---------------------------------------------------------------------------

def _section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def render_report(events: list[dict]) -> None:
    print(f"\nblen_IA_ort Telemetry Report — {len(events)} journal events analysed")

    _section("Truncation Rate by Turn Class")
    trunc = _collect_truncation(events)
    if trunc:
        for tc, data in trunc.items():
            print(f"  {tc:<30} completions={data['handler_completions']:<5} "
                  f"truncations={data['truncations']:<4} rate={data['rate']}")
    else:
        print("  (no handler_completed events found)")

    _section("Continuation Usage")
    cont = _collect_continuation(events)
    print(f"  Dispatched:  {cont['dispatched']}")
    print(f"  Degraded:    {cont['degraded']}")
    if cont["degraded_reasons"]:
        for reason, count in cont["degraded_reasons"].items():
            print(f"    {reason}: {count}")

    _section("Discovery Phase")
    disc = _collect_discovery(events)
    print(f"  Ran:         {disc['ran']}")
    print(f"  Skipped:")
    if disc["skipped"]:
        for reason, count in disc["skipped"].items():
            print(f"    {reason}: {count}")
    else:
        print("    (none logged)")

    _section("Session Memory")
    smem = _collect_session_memory(events)
    print(f"  Cleanup events:              {smem['cleanup_events']}")
    print(f"  Stale cleared events:        {smem['stale_cleared_events']}")
    print(f"  Used events:                 {smem['used_events']}")
    print(f"  Updated events:              {smem['updated_events']}")

    _section("Tool-Call Distribution by Turn Class")
    rdist = _collect_round_distribution(events)
    if rdist:
        for tc, data in rdist.items():
            print(f"  {tc:<30} n={data['samples']:<4} min={data['min']} "
                  f"max={data['max']} avg={data['avg']}")
    else:
        print("  (no data)")

    _section("Goal Outcomes & Latency")
    goals = _collect_goal_outcomes(events)
    for outcome, count in goals["outcomes"].items():
        print(f"  {outcome}: {count}")
    if goals["latency_by_class"]:
        print()
        for tc, lat in goals["latency_by_class"].items():
            print(f"  {tc:<30} {lat}")

    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _default_sessions_dir() -> Path:
    here = Path(__file__).parent
    project_root = here.parent
    root_sessions = project_root / "runtime" / "journal" / "sessions"
    if root_sessions.exists():
        return root_sessions
    return project_root / "blender_addon" / "runtime" / "journal" / "sessions"


def main() -> None:
    parser = argparse.ArgumentParser(description="blend_IA_ort telemetry report")
    parser.add_argument(
        "--journal",
        default=None,
        help="Path to journal/sessions directory (default: auto-detected from project root)",
    )
    args = parser.parse_args()

    sessions_dir = Path(args.journal) if args.journal else _default_sessions_dir()
    if not sessions_dir.is_dir():
        print(f"ERROR: journal sessions directory not found: {sessions_dir}", file=sys.stderr)
        print("Run the addon in Blender first to generate journal data.", file=sys.stderr)
        sys.exit(1)

    events = _load_events(sessions_dir)
    render_report(events)


if __name__ == "__main__":
    main()
