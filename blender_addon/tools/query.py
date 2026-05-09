"""Blender API and node type query tool handlers."""

from __future__ import annotations


def handle_query_node_types(cmd: dict) -> dict:
    """Introspect available Geometry Nodes node types in the running Blender version.

    Modes:
    - search="matrix"        -> list all GN node type identifiers containing that word
    - node_type="FunctionNodeAlignEulerToVector"
                             -> return inputs, outputs, and editable properties for that type
    - api_type="NodeTreeInterface"
                             -> inspect any bpy.types.* object: lists its methods,
                               properties, and function signatures. Use this BEFORE
                               execute_code when unsure about Blender API (e.g. how to
                               call interface.new_socket() in this exact Blender version).
    """
    search = (cmd.get("search") or "").strip().lower()
    node_type = (cmd.get("node_type") or "").strip()
    api_type = (cmd.get("api_type") or "").strip()

    def _do():
        import bpy

        if api_type:
            rna_type = getattr(bpy.types, api_type, None)
            if rna_type is None:
                candidates = [n for n in dir(bpy.types) if api_type.lower() in n.lower()][:20]
                return {
                    "status": "not_found",
                    "api_type": api_type,
                    "candidates": candidates,
                    "hint": f"bpy.types.{api_type} not found. Did you mean one of these?",
                }
            import inspect

            methods = []
            properties = []
            for attr in sorted(dir(rna_type)):
                if attr.startswith("__"):
                    continue
                try:
                    obj = getattr(rna_type, attr)
                except Exception:
                    continue
                if callable(obj):
                    try:
                        sig = str(inspect.signature(obj))
                    except (ValueError, TypeError):
                        sig = "(...)"
                    methods.append({"name": attr, "signature": sig[:120]})
                else:
                    properties.append(attr)
            rna_props = []
            try:
                for prop in rna_type.bl_rna.properties:
                    rna_props.append(
                        {
                            "identifier": prop.identifier,
                            "type": prop.type,
                            "description": prop.description[:80] if prop.description else "",
                        }
                    )
            except Exception:
                pass
            return {
                "status": "ok",
                "api_type": f"bpy.types.{api_type}",
                "methods": methods[:40],
                "properties": properties[:40],
                "rna_properties": rna_props[:30],
            }

        if node_type:
            tmp = bpy.data.node_groups.new("__introspect_tmp__", "GeometryNodeTree")
            try:
                node = tmp.nodes.new(node_type)
                inputs = [
                    {"name": socket.name, "identifier": socket.identifier, "type": socket.type}
                    for socket in node.inputs
                ]
                outputs = [
                    {"name": socket.name, "identifier": socket.identifier, "type": socket.type}
                    for socket in node.outputs
                ]
                props = []
                for prop in node.bl_rna.properties:
                    if prop.identifier.startswith("_") or prop.identifier in {
                        "rna_type",
                        "name",
                        "label",
                        "type",
                        "location",
                        "width",
                        "height",
                        "color",
                        "use_custom_color",
                        "select",
                        "hide",
                        "mute",
                    }:
                        continue
                    props.append(prop.identifier)
                    if len(props) >= 20:
                        break
                return {
                    "status": "ok",
                    "node_type": node_type,
                    "inputs": inputs,
                    "outputs": outputs,
                    "properties": props,
                }
            except Exception as exc:
                return {"status": "error", "node_type": node_type, "error": str(exc)}
            finally:
                bpy.data.node_groups.remove(tmp)

        if search:
            matches = []
            for name in sorted(dir(bpy.types)):
                if not (
                    name.startswith("GeometryNode")
                    or name.startswith("FunctionNode")
                    or name.startswith("ShaderNode")
                ):
                    continue
                if search and search not in name.lower():
                    continue
                matches.append(name)
            return {"status": "ok", "search": search, "matches": matches[:60]}

        return {
            "status": "error",
            "error": "Provide 'search' (keyword), 'node_type' (exact type name), or 'api_type' (bpy.types name to inspect).",
        }

    from .handlers import execute_in_main_thread

    return execute_in_main_thread(_do)


__all__ = ["handle_query_node_types"]
