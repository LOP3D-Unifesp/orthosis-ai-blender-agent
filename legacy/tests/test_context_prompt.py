import unittest

from blender_addon.context_prompt import build_system_prompt


class ContextPromptTests(unittest.TestCase):
    def test_build_system_prompt_uses_compact_sections(self):
        prompt = build_system_prompt(
            base_system_prompt="Base prompt.",
            intent={"primary": "mutation", "intents": ["mutation", "gn_context"]},
            knowledge=[],
            analytical=[],
            task_class="localized_mutation",
            routing_policy={
                "reason": "local_scope_first",
                "allow_broad_reads": False,
                "session_memory_sufficient": True,
                "structural_index_sufficient": True,
                "local_scope_sufficient": True,
            },
            plan_gate={"requires_approval": True, "user_explicit_approval": False},
            continuity={"status": "continuation", "summary": "Mesmo alvo da sessao anterior."},
            context_sources={"preferred_sources": ["session_memory", "local_scope"], "missing_context": []},
            next_step_strategy={"strategy": "use_session_memory_then_execute", "summary": "Usar memoria antes de reler."},
            session_state={
                "runtime_phase": "planning",
                "current_plan_type": "execution_plan",
                "current_plan_status": "presented",
                "approval_required": True,
                "approval_status": "pending",
            },
            session_memory={"target_tree": "GN_Teste", "relevant_nodes": ["Curve.001"]},
            local_scope={"tree_name": "GN_Teste", "node_names": ["Curve.001"]},
            structural_index={"GN_Teste": {"node_count": 8}},
            current_stage={"stage_title": "Etapa 1", "stage_goal": "Ajustar curva", "stage_status": "pending"},
            recent_session_summary="Resumo recente.",
        )

        self.assertIn("Task snapshot:", prompt)
        self.assertIn("Context budget:", prompt)
        self.assertIn("Runtime state:", prompt)
        self.assertIn("Working memory:", prompt)
        self.assertIn("Behavior guide:", prompt)
        self.assertIn("Never use Markdown tables in Blender UI", prompt)
        self.assertIn("Keep responses concise by default", prompt)
        self.assertIn("Current turn is plan-only.", prompt)
        self.assertNotIn("Execution governance:", prompt)
        self.assertNotIn("Staged execution:", prompt)

    def test_build_system_prompt_truncates_large_sections(self):
        huge_text = "x" * 3000
        prompt = build_system_prompt(
            base_system_prompt="Base prompt.",
            intent={"primary": "diagnosis", "intents": ["diagnosis"]},
            knowledge=[{"source": "knowledge/test.md", "content": huge_text}],
            analytical=[{"skill": "scene_context_inspector", "status": "success", "result": {"blob": huge_text}}],
            task_class="diagnostic",
            routing_policy={},
            plan_gate={"requires_approval": False},
            continuity={},
            context_sources={},
            next_step_strategy={},
            session_state={},
            session_memory={},
            local_scope={},
            structural_index={},
            current_stage={},
            recent_session_summary=huge_text,
        )

        self.assertIn("[truncated]", prompt)
        self.assertIn("Selected knowledge:", prompt)
        self.assertIn("Analytical outputs:", prompt)
        self.assertIn("Recent session context:", prompt)


if __name__ == "__main__":
    unittest.main()
