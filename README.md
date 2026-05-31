# Orthosis AI Agent

**An AI-powered Blender addon for parametric orthosis design using Geometry Nodes.**

Embeds a Claude-based copilot in the Blender sidebar. The agent reads the Geometry Nodes tree context, proposes Python scripts (*drafts*), and the designer reviews and executes them manually. The long-term goal is a fully parametric orthosis geometry that a clinical professional adjusts via a parameter panel — without any interaction with the AI agent.

---

## ⚠️ Disclaimer

**This is a research prototype.** It is not validated as medical or clinical software.
Do not use for clinical decision-making, patient treatment planning, or production orthosis fabrication without independent professional validation.
All generated scripts must be reviewed by a qualified engineer before execution.

---

## Features

- **Chat panel inside Blender** — sidebar copilot in the View3D viewport (N-panel → Orthosis tab)
- **Scene context reading** — agent reads node tree structure, sockets, frames, links, and parameters
- **Draft-based workflow** — agent proposes Python/bpy scripts; user reviews and runs them manually
- **Fast paths** — greetings, help, and simple reads resolved without an API call
- **Session persistence** — conversation history survives Blender restarts and file re-opens
- **Post-failure recovery** — structured diagnosis when a script does not produce the expected result
- **Automated tests** — 185 tests run without Blender or `bpy`

---

## Architecture

```
Blender UI  (ui/panel_chat_turn.py)
  └─ AgentRuntime.run_turn()  (core/runtime.py)
        ├─ Fast path          (fast_path.py)        ← no API call
        ├─ Pending decision   (runtime/pending_decision.py)
        ├─ Router             (runtime/router.py)   ← infer_turn_intent
        └─ Workspace handler  (handler/workspace.py)
              └─ Agent loop   (core/agent_loop.py)  ← Anthropic API + tool use
                    └─ TCP socket :65432 → Blender tool dispatcher
                          └─ tools/{draft, reads, edits, query, snapshots, ...}
```

Full step-by-step flow: [`docs/refactor_handoff/LIVE_FLOW.md`](docs/refactor_handoff/LIVE_FLOW.md)

---

## Operational Safety

The agent **never executes code autonomously**. The following tools are hard-blocked in the automatic flow (`core/tool_policy.py`):

| Tool | Status |
|---|---|
| `execute_code` | **Blocked** — user-triggered only |
| `make_plan` | **Blocked** |
| `apply_simulator_payload` | **Blocked** |

The agent writes drafts via `write_script_draft`. The user opens the draft in the Blender Text Editor, reviews it, and runs it manually via the addon's cycle operators (*Abrir Draft → Rodar Draft*).

---

## Prerequisites

- **Blender 4.0 or later**
- **`anthropic` Python package** — must be installed inside Blender's bundled Python (see [Installation](#installation))
- **Anthropic API key** — set in the addon preferences

---

## Installation

### 1. Get the repository

```bash
git clone <repo-url>
cd blend_IA_ort_v2
```

### 2. Install the addon in Blender

Create a zip of the `blender_addon/` folder and install it in Blender:

```
# From repo root:
# Compress blender_addon/ → blender_addon.zip
# Then in Blender: Edit → Preferences → Add-ons → Install from Disk → select the zip
```

Enable **"Orthosis AI Agent"** in the add-ons list.

### 3. Install `anthropic` inside Blender's Python

Blender ships its own Python interpreter. You must install `anthropic` inside it — **not** in your system Python.

**Find Blender's Python executable** — in the Blender Scripting workspace, run:
```python
import sys; print(sys.executable)
```

Then install `anthropic`:

```bash
# Windows (example path — use the path from the step above):
"C:\Program Files\Blender Foundation\Blender 4.x\4.x\python\bin\python.exe" -m pip install anthropic

# macOS / Linux (example):
/path/to/blender/4.x/python/bin/python3.xx -m pip install anthropic
```

> **Note:** `requirements.txt` in this repo covers development tools and the optional MCP server, **not** this Blender-internal install.

### 4. Configure the addon

**Edit → Preferences → Add-ons → Orthosis AI Agent:**

- **Claude API Key** — your Anthropic API key
- **Project Root Path** — path to the root of this repository (the folder containing `blender_addon/` and `knowledge/`)

---

## Usage

1. Open a `.blend` file containing a Geometry Nodes setup.
2. Open the **View3D sidebar** (press `N`) → **Orthosis** tab.
3. Type a prompt. Example: *"escreve um draft para parametrizar a escala do metacarpo"*
4. The agent reads the scene context, then proposes a Python script draft.
5. Click **Abrir Draft** to inspect the script in the Text Editor.
6. Review the script — verify it targets the correct nodes.
7. Click **Rodar Draft** to execute manually.
8. Report the result (success **✓** or describe the failure) to continue the conversation.

> **Language:** The agent responds in **Brazilian Portuguese** by default.

---

## Running Tests

The test suite runs without Blender or `bpy` (both are mocked internally):

```bash
python -m pytest -q
```

Expected output: **185 passed** in under 2 seconds.

---

## Project Structure

```
blend_IA_ort_v2/
├── blender_addon/          # Installable Blender addon package
│   ├── core/               # AgentRuntime, agent loop, Anthropic client, tool policy
│   ├── handler/            # Workspace handler, draft pipeline, feedback handlers
│   ├── runtime/            # Router, pending decision, tree renderer, observability
│   ├── session/            # Session schema, V1 JSON store, JSONL chat history
│   ├── tools/              # Tool dispatchers (Blender-side), schemas, TCP client
│   └── ui/                 # Blender panels, operators, cycle state machine
├── knowledge/              # Agent knowledge corpus (read-only by the retriever)
│   ├── domain/             # GN reference, orthosis domain, clinical parameters
│   ├── skills/             # Diagnosis, mutation, and navigation guides
│   └── recipes/            # Reusable GN patterns
├── docs/                   # Architecture documentation
│   └── refactor_handoff/   # LIVE_FLOW.md — live architecture reference
├── contracts/              # JSON schemas for tool calls and session events
├── tests/                  # Automated tests (no bpy required)
├── tools/                  # Dev utilities (telemetry, runtime validation)
├── server.py               # Optional MCP server (alternate integration path)
├── blender_connection.py   # TCP client used by the MCP server
├── CLAUDE.md               # Internal development log and agent behaviour rules
└── requirements.txt        # Dev/MCP dependencies (not for Blender-internal install)
```

---

## Current Status and Limitations

| Area | Status |
|---|---|
| Core agent loop | ✅ Functional — 185 tests pass |
| Session persistence | ✅ V1 JSON + JSONL chat history |
| Post-failure recovery | 🔶 Partial — diagnosis works; state sync has known edge cases |
| LLM provider | ⚠️ Coupled to Anthropic API — multi-LLM abstraction not yet implemented |
| GN tree scale | ⚠️ Validated at ~80–103 nodes; target is 400–500 |
| Test coverage | ⚠️ Several modules lack dedicated unit tests (router, workspace, fast_path) |
| GitHub readiness | 🔶 No LICENSE defined yet; not ready for public clinical use |

Known technical debt is documented in [`CLAUDE.md`](CLAUDE.md) (section *Dívida técnica atual*) and [`docs/refactor_handoff/LIVE_FLOW.md`](docs/refactor_handoff/LIVE_FLOW.md).

---

## ⚠️ Sensitive Data Warning

The following are **auto-generated at runtime and must never be committed**:

| Path | Content | Status |
|---|---|---|
| `runtime/` | Session state, chat history, journals, draft history | In `.gitignore` ✅ |
| `.claude/` | Claude Code workspace metadata | In `.gitignore` ✅ |
| `*.blend` / `*.blend1` | Blender files (may contain private geometry) | In `.gitignore` ✅ |

**Before every commit:** run `git status` to verify none of these appear as staged files.
Never use `git add -f` on `runtime/` — it contains local file paths and conversation history.

---

## License

License to be defined. This repository is currently **research use only**.
Do not redistribute without explicit permission from the project authors.

---

*VB Orthosis Project*
