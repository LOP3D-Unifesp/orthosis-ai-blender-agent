"""Draft-first tool policy constants for the slim runtime."""

from __future__ import annotations

from dataclasses import dataclass, field


BLOCKED_PRODUCT_TOOLS = frozenset({
    "make_plan",
    "execute_code",
    "apply_simulator_payload",
})

DRAFT_BROAD_READ_TOOLS = frozenset({
    "get_scene_summary",
    "get_gn_hosts",
    "prepare_draft_context",
    "resolve_gn_workspace",
    "build_tree_structural_memory",
    "list_tree_nodes",
    "get_tree_parameters",
})

DRAFT_FOCAL_READ_TOOLS = frozenset({
    "get_node_context",
    "get_selected_nodes_context",
    "get_active_frame_context",
    "get_local_subgraph_context",
    "find_tree_nodes",
    "get_changes_since_last_turn",
})


@dataclass
class DraftAttemptContract:
    require_read_before_write: bool = True
    allow_write_when_source_missing: bool = False
    require_target_tree_for_write: bool = False
    require_structural_memory_for_write: bool = False
    require_context_evidence_for_write: bool = False
    require_prepared_context_for_write: bool = False
    block_when_prepared_context_has_blockers: bool = False


@dataclass
class DraftAttemptState:
    source_read_attempted: bool = False
    source_read_succeeded: bool = False
    source_block_missing: bool = False
    target_tree: str = ""
    target_resolved: bool = False
    structural_memory_ready: bool = False
    evidence_reads: int = 0
    prepared_context_read: bool = False
    prepared_context_blockers: list[str] = field(default_factory=list)
    write_attempted: bool = False
    write_succeeded: bool = False
    last_block_reason: str = ""
