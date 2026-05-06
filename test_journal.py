import sys
import json
from unittest.mock import MagicMock
sys.modules["bpy"] = MagicMock()

import os
from pathlib import Path
from blender_addon.agent_runtime import AgentRuntime
from blender_addon.runtime.core import Runtime
from blender_addon.runtime.handlers.drafting import handle_draft_workspace
from blender_addon.runtime.handlers import TurnContext

def run_tests():
    root = Path(os.getcwd())
    
    # Setup test runtime
    runtime = AgentRuntime(project_root=root)
    # Patch the LLM call to just return our mock and intercept the prompt
    def mock_agent_loop(system, messages, excluded_tools=None, max_rounds=None, **kwargs):
        with open("mock_prompt_capture.txt", "a", encoding="utf-8") as f:
            f.write(f"\n--- PROMPT CAPTURE ---\n{system}\n----------------------\n")
        return "Respondi usando o contexto do usuário!"
    
    runtime._agent_loop = mock_agent_loop
    
    # 1. Start a fresh session and inject our broad memory
    state = runtime.bridge.get_session_state()
    state["agent_session_active"] = True
    runtime.bridge.set_modes(agent_session_active=True)
    
    # Inject memory directly to session state
    runtime._session_memory = {
        "last_goal": "Criar um castelo procedimental",
        "last_hypothesis": "A estrutura base deve ser um cubo subdividido",
        "relevant_nodes": ["Transform", "Subdivide Mesh"]
    }
    
    # Caso A: Pergunta meta
    print(">>> Teste Caso A")
    runtime.run_turn("Você tem ideia do que eu pretendo fazer?", is_ui_command=False)
    
    # Dump the journal lines
    journal_file = runtime.journal.get_paths()["session_file"]
    with open(journal_file, "r") as f:
        print("\n--- JOURNAL CASO A ---")
        for line in f:
            if '"session_memory_used"' in line or '"tree_structural_memory_used"' in line:
                data = json.loads(line)
                if data.get("type") == "runtime_event" and data.get("event_type") in ("session_memory_used", "tree_structural_memory_used"):
                    print(json.dumps(data, indent=2))
                
if __name__ == "__main__":
    run_tests()
