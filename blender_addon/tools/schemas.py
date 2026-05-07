"""Tool schemas exposed to the Claude agent."""

from __future__ import annotations


TOOLS = [
    {
        "name": "get_scene_summary",
        "description": "Read global scene state and GN host presence.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_gn_hosts",
        "description": "List objects with Geometry Nodes modifiers.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_node_context",
        "description": "Read one node and nearby links/nodes by name or label.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tree_name": {"type": "string"},
                "node_name": {"type": "string"},
                "label": {"type": "string"},
                "radius": {"type": "integer", "default": 1},
            },
            "required": ["tree_name"],
        },
    },
    {
        "name": "get_selected_nodes_context",
        "description": "Read context only for currently selected nodes in one tree.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tree_name": {"type": "string"},
                "include_neighbors": {"type": "boolean", "default": True},
                "radius": {"type": "integer", "default": 1},
            },
            "required": ["tree_name"],
        },
    },
    {
        "name": "get_active_frame_context",
        "description": "Read context for active/selected frame and its child nodes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tree_name": {"type": "string"},
                "frame_name": {"type": "string"},
                "include_neighbors": {"type": "boolean", "default": False},
                "radius": {"type": "integer", "default": 1},
            },
            "required": ["tree_name"],
        },
    },
    {
        "name": "get_local_subgraph_context",
        "description": "Read focused local subgraph by node list or neighborhood center.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tree_name": {"type": "string"},
                "scope_mode": {"type": "string", "enum": ["by_nodes", "neighborhood"]},
                "node_names": {"type": "array", "items": {"type": "string"}},
                "center_node": {"type": "string"},
                "hops": {"type": "integer", "default": 1},
                "direction": {"type": "string", "enum": ["both", "upstream", "downstream"], "default": "both"},
                "max_nodes": {"type": "integer", "default": 80},
                "include_values": {"type": "boolean", "default": True},
                "include_properties": {"type": "boolean", "default": True},
            },
            "required": ["tree_name", "scope_mode"],
        },
    },
    {
        "name": "get_changes_since_last_turn",
        "description": "Compare focused tree marker to detect local changes since last turn.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tree_name": {"type": "string"},
                "update_marker": {"type": "boolean", "default": True},
                "limit": {"type": "integer", "default": 25},
            },
        },
    },
    {
        "name": "get_tree_parameters",
        "description": "Read live GN modifier input values for one tree.",
        "input_schema": {
            "type": "object",
            "properties": {"tree_name": {"type": "string"}},
            "required": ["tree_name"],
        },
    },
    {
        "name": "prepare_draft_context",
        "description": (
            "Aggregate the deterministic context needed to evolve the single canonical draft. "
            "Resolves the target GN workspace, prepares/reuses structural memory, summarizes "
            "phase classification and clinical parameter roles, and returns explicit write "
            "requirements/blockers for the next draft update, specialized by the turn goal mode."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tree_name": {"type": "string"},
                "user_message": {"type": "string"},
                "object_name": {"type": "string"},
                "modifier_name": {"type": "string"},
                "goal_mode": {"type": "string", "enum": ["diagnose_only", "focal_correction", "functional_expansion", "feedback_fix"]},
                "has_existing_draft": {"type": "boolean", "default": False},
                "stored_live_node_refs": {"type": "array", "items": {"type": "string"}},
                "stored_expected_parameter_refs": {"type": "array", "items": {"type": "string"}},
                "stored_expected_focus_regions": {"type": "array", "items": {"type": "string"}},
                "prefer_from_scratch": {"type": "boolean", "default": False},
                "force_refresh": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "resolve_gn_workspace",
        "description": (
            "Resolve the current Geometry Nodes workspace tree deterministically. "
            "Lists candidate GN trees, bindings, selected tree, confidence, and "
            "why that tree was chosen."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_message": {"type": "string"},
                "tree_name": {"type": "string"},
                "object_name": {"type": "string"},
                "modifier_name": {"type": "string"},
            },
        },
    },
    {
        "name": "build_tree_structural_memory",
        "description": (
            "Build and persist a reusable tree-first structural memory for a GN tree. "
            "Uses direct inventory reads and focused runtime data; does not require "
            "get_tree_structure as a public tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tree_name": {"type": "string"},
                "user_message": {"type": "string"},
                "force_refresh": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "classify_tree_phases",
        "description": (
            "Classify the GN tree and its regions into orthosis workflow phases "
            "using existing structural memory when fresh."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tree_name": {"type": "string"},
                "user_message": {"type": "string"},
                "force_refresh": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "map_clinical_parameter_roles",
        "description": (
            "Map GN interface parameters into initial clinical roles: measurements, "
            "positioning controls, uncertain parameters, and likely affected regions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tree_name": {"type": "string"},
                "user_message": {"type": "string"},
                "force_refresh": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "analyze_scene",
        "description": "Run scene_context_inspector (compact diagnostic summary).",
        "input_schema": {
            "type": "object",
            "properties": {
                "current_goal": {"type": "string"},
                "query": {"type": "string"},
                "output_mode": {"type": "string"},
            },
        },
    },
    {
        "name": "execute_code",
        "description": (
            "Execute Python directly in Blender when no structured tool can do the task. "
            "make_plan is mandatory before this tool. Each call runs in a fresh Python "
            "namespace, so every script must be self-contained."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "script": {"type": "string", "description": "Deprecated alias for code; normalized by runtime."},
            },
            "required": ["code"],
        },
    },
    {
        "name": "capture_screenshot",
        "description": "Capture viewport image and analyze visually in an isolated multimodal call.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_size": {"type": "integer", "default": 900},
            },
        },
    },
    {
        "name": "query_node_types",
        "description": (
            "Introspect the CURRENT Blender version's API directly — no API cost, runs locally. "
            "Use this BEFORE execute_code whenever you are unsure about node type identifiers OR "
            "about any bpy.types API (e.g. how to call interface.new_socket() in this exact version). "
            "Three modes:\n"
            "- search='matrix'           → lists all GN node type identifiers matching that keyword\n"
            "- node_type='GeometryNodeXxx' → inputs, outputs, properties for that node type\n"
            "- api_type='NodeTreeInterface' → methods, signatures, and RNA properties of any bpy.types.* "
            "class (use this to discover the correct API before writing code)"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": "Keyword to search in GN node type names (case-insensitive)",
                },
                "node_type": {
                    "type": "string",
                    "description": "Exact node type identifier to inspect (e.g. 'FunctionNodeAlignEulerToVector')",
                },
                "api_type": {
                    "type": "string",
                    "description": (
                        "Name of a bpy.types.* class to inspect (e.g. 'NodeTreeInterface', "
                        "'NodeGroup', 'NodesModifier'). Returns methods with signatures and "
                        "RNA properties — use this to discover the correct API for the running "
                        "Blender version before writing execute_code scripts."
                    ),
                },
            },
        },
    },
    {
        "name": "list_tree_nodes",
        "description": (
            "Return the COMPLETE node inventory of a GN tree by reading directly from bpy "
            "(no snapshot pipeline, no node cap). Use this BEFORE any operation on a large "
            "tree (100+ nodes) or whenever get_changes_since_last_turn warns that the "
            "snapshot was truncated. Returns name, bl_idname, label, and parent_frame for "
            "every node — including nodes beyond position 64 that snapshot tools would miss."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tree_name": {
                    "type": "string",
                    "description": "Name of the node group in bpy.data.node_groups",
                },
            },
            "required": ["tree_name"],
        },
    },
    {
        "name": "find_tree_nodes",
        "description": (
            "Search nodes in a GN tree by name fragment, label fragment, or bl_idname. "
            "Reads directly from bpy — no snapshot, no node cap. Case-insensitive. "
            "All filters (name_contains, label_contains, bl_idname) are optional and combinable. "
            "IMPORTANT: If NO filters are provided, ALL nodes are returned — this is a "
            "full listing equivalent to list_tree_nodes. The field 'is_full_listing' in the "
            "response will be True in that case. Use this to locate nodes by partial name/label "
            "before operating on them, especially in large trees where the snapshot may be truncated."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tree_name": {
                    "type": "string",
                    "description": "Name of the node group in bpy.data.node_groups",
                },
                "name_contains": {
                    "type": "string",
                    "description": "Case-insensitive fragment to match against node internal names",
                },
                "label_contains": {
                    "type": "string",
                    "description": "Case-insensitive fragment to match against node labels",
                },
                "bl_idname": {
                    "type": "string",
                    "description": "Node type identifier fragment (or exact if bl_idname_exact=true)",
                },
                "bl_idname_exact": {
                    "type": "boolean",
                    "description": "If true, match bl_idname exactly. Default false (fragment match).",
                },
            },
            "required": ["tree_name"],
        },
    },
    {
        "name": "write_script_draft",
        "description": (
            "Write a Python/bpy script to a Blender Text Editor block. "
            "The script is NOT executed — it is staged for the user to review, "
            "modify, and run manually from the Scripting workspace. "
            "Use this instead of execute_code when drafting_mode is active."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "block_name": {
                    "type": "string",
                    "default": "GN_Agent_Draft",
                    "description": "Name of the Blender text block to write to",
                },
                "code": {
                    "type": "string",
                    "description": "Complete Python/bpy script to draft",
                },
                "description": {
                    "type": "string",
                    "description": "What this script does (shown to user)",
                },
                "tree_name": {
                    "type": "string",
                    "description": "Target GN tree name (optional context)",
                },
                "revision_kind": {
                    "type": "string",
                    "description": "Revision kind: create, refine, or recovery",
                },
                "revision_changed_from_previous": {
                    "type": "string",
                    "description": "Short delta summary for this revision",
                },
            },
            "required": ["code", "description"],
        },
    },
    {
        "name": "read_script_draft",
        "description": (
            "Read the current content of a Blender Text Editor block. "
            "Use this to check what the user has modified before updating the draft."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "block_name": {
                    "type": "string",
                    "default": "GN_Agent_Draft",
                    "description": "Name of the Blender text block to read",
                },
            },
        },
    },
]


_DRAFT_FIRST_EXCLUDED_AGENT_TOOLS = {
    "execute_code",
}

AGENT_TOOLS: list[dict] = [
    tool for tool in TOOLS
    if str(tool.get("name") or "") not in _DRAFT_FIRST_EXCLUDED_AGENT_TOOLS
]
