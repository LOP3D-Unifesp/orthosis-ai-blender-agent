"""Temporary diagnostic script — session file audit. Remove after use."""
import hashlib, json, os, sys
from pathlib import Path
from datetime import datetime

# Force UTF-8 output on Windows console
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TARGET = r"C:\Users\Eduardo\Desktop\blend_IA_ort_v2\testeAgenteBlender.blend"
target_norm = Path(TARGET).resolve().as_posix().lower()
target_h = hashlib.md5(target_norm.encode("utf-8")).hexdigest()[:8]
LOADED_SESSION_ID = "sess-20260418T044136Z-b9d73f6b"


def norm(p):
    try:
        return Path(p).resolve().as_posix().lower()
    except Exception:
        return str(p).replace("\\", "/").lower()


def ts(mtime):
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")


def inspect_v1(path):
    try:
        d = json.loads(path.read_text("utf-8"))
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    identity = d.get("identity") or {}
    focus    = d.get("focus") or {}
    history  = d.get("history") or {}
    msgs = history.get("messages", []) if isinstance(history, dict) else []
    if not isinstance(msgs, list):
        msgs = []
    bp = str(focus.get("blend_path", "") or "")
    bp_norm = norm(bp) if bp else ""
    h_of_bp = hashlib.md5(bp_norm.encode("utf-8")).hexdigest()[:8] if bp_norm else "(empty)"
    first = msgs[0].get("content", "")[:80] if msgs else ""
    last  = msgs[-1].get("content", "")[:80] if msgs else ""
    last3 = [(m.get("role", ""), m.get("content", "")[:70]) for m in msgs[-3:]]
    has_routing = any(
        "routing_observation" in (m.get("content", "") or "")
        for m in msgs
    )
    return {
        "schema": "V1",
        "session_id": str(identity.get("session_id", "") or ""),
        "last_active": str(identity.get("last_active_at", "") or ""),
        "focus_blend_path": bp,
        "focus_bp_norm": bp_norm,
        "hash_of_focus_bp": h_of_bp,
        "msg_count": len(msgs),
        "first": first,
        "last": last,
        "last3": last3,
        "has_routing_obs": has_routing,
        "matches_target": bp_norm == target_norm,
        "hash_matches_target": h_of_bp == target_h,
    }


def inspect_legacy(path):
    try:
        d = json.loads(path.read_text("utf-8"))
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    msgs = d.get("chat_history", []) if isinstance(d.get("chat_history"), list) else []
    bp = str(d.get("blend_path", "") or "")
    bp_norm = norm(bp) if bp else ""
    h_of_bp = hashlib.md5(bp_norm.encode("utf-8")).hexdigest()[:8] if bp_norm else "(empty)"
    first = msgs[0].get("text", "")[:80] if msgs else ""
    last  = msgs[-1].get("text", "")[:80] if msgs else ""
    last3 = [(m.get("role", ""), m.get("text", "")[:70]) for m in msgs[-3:]]
    return {
        "schema": "LEGACY",
        "session_id": str(d.get("session_id", "") or ""),
        "last_active": str(d.get("updated_at", "") or d.get("session_started_at", "") or ""),
        "focus_blend_path": bp,
        "focus_bp_norm": bp_norm,
        "hash_of_focus_bp": h_of_bp,
        "msg_count": len(msgs),
        "first": first,
        "last": last,
        "last3": last3,
        "has_routing_obs": False,
        "matches_target": bp_norm == target_norm,
        "hash_matches_target": h_of_bp == target_h,
    }


results = []
for dirpath in [Path("runtime/sessions_v1"), Path("runtime/sessions")]:
    if not dirpath.exists():
        continue
    for f in sorted(dirpath.glob("*.json")):
        mtime = f.stat().st_mtime
        is_v1_dir = dirpath.name == "sessions_v1"
        info = inspect_v1(f) if is_v1_dir else inspect_legacy(f)
        if info is None:
            # Try the other parser
            info = inspect_legacy(f) if is_v1_dir else inspect_v1(f)
        if info is None:
            info = {"schema": "UNREADABLE"}
        info["filename"] = f.name
        info["filepath"] = str(f)
        info["mtime"] = mtime
        info["mtime_str"] = ts(mtime)
        info["dir"] = dirpath.name
        info["is_target_hash"] = (f.name == f"session_{target_h}.json")
        info["is_loaded_session"] = (info.get("session_id", "") == LOADED_SESSION_ID)
        results.append(info)

# Sort by mtime desc
results.sort(key=lambda x: x.get("mtime", 0), reverse=True)

print("=" * 70)
print("SESSION FILE AUDIT")
print("=" * 70)
print(f"Target blend_path  : {TARGET}")
print(f"Target normalized  : {target_norm}")
print(f"Expected hash file : session_{target_h}.json")
print(f"Currently loaded   : {LOADED_SESSION_ID}")
print(f"Total files found  : {len(results)}")
print()

for r in results:
    markers = []
    if r.get("is_target_hash"):    markers.append("TARGET_HASH")
    if r.get("is_loaded_session"): markers.append("CURRENTLY_LOADED")
    if r.get("matches_target"):    markers.append("PATH_MATCH")
    if r.get("hash_matches_target") and not r.get("is_target_hash"):
        markers.append("HASH_MATCH_BUT_DIFF_FILE")
    marker_str = "  [" + ", ".join(markers) + "]" if markers else ""
    print(f"--- {r['dir']}/{r['filename']}{marker_str} ---")
    print(f"  schema         : {r.get('schema', '?')}")
    print(f"  session_id     : {r.get('session_id', '?')}")
    print(f"  last_active    : {r.get('last_active', '?')}")
    print(f"  mtime          : {r.get('mtime_str', '?')}")
    print(f"  focus.bp       : {r.get('focus_blend_path', '?')!r}")
    print(f"  focus.bp_norm  : {r.get('focus_bp_norm', '?')}")
    print(f"  hash_of_fp     : {r.get('hash_of_focus_bp', '?')}")
    print(f"  msg_count      : {r.get('msg_count', 0)}")
    print(f"  first_msg      : {r.get('first', '(empty)')!r}")
    print(f"  last_msg       : {r.get('last', '(empty)')!r}")
    if r.get("last3"):
        print(f"  last 3 turns   :")
        for role, txt in r["last3"]:
            print(f"    [{role:9s}] {txt!r}")
    print(f"  has_routing    : {r.get('has_routing_obs', False)}")
    print(f"  path_match     : {r.get('matches_target', False)}")
    print()

# Summary table
print("=" * 70)
print("SUMMARY TABLE (sorted by mtime desc)")
print("=" * 70)
print(f"{'File':<30} {'schema':<6} {'msgs':>5} {'mtime':<20} {'flags'}")
print("-" * 70)
for r in results:
    flags = []
    if r.get("is_target_hash"):    flags.append("TARGET_HASH")
    if r.get("is_loaded_session"): flags.append("LOADED")
    if r.get("matches_target"):    flags.append("PATH_MATCH")
    fname = r["dir"][:8] + "/" + r["filename"]
    print(f"{fname:<30} {r.get('schema','?'):<6} {r.get('msg_count',0):>5} {r.get('mtime_str','?'):<20} {' '.join(flags)}")
