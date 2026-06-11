"""Minimal bridge status panel — socket on/off + last connection timestamp."""

from __future__ import annotations

import bpy


class BRIDGE_PT_Status(bpy.types.Panel):
    bl_label = "Bridge"
    bl_idname = "BRIDGE_PT_Status"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Orthosis"

    def draw(self, context):
        layout = self.layout
        from .. import server as _server_mod

        srv = _server_mod._server
        running = srv.running

        row = layout.row()
        if running:
            row.label(text="localhost:65432", icon="LINKED")
            layout.operator("bridge.stop_server", text="Stop Bridge", icon="X")
        else:
            row.label(text="Bridge stopped", icon="UNLINKED")
            layout.operator("bridge.start_server", text="Start Bridge", icon="PLAY")

        last = getattr(srv, "_last_connection_at", "")
        if last:
            layout.label(text=f"Last connection: {last}", icon="CHECKMARK")


class BRIDGE_OT_StartServer(bpy.types.Operator):
    bl_idname = "bridge.start_server"
    bl_label = "Start Bridge"
    bl_description = "Start the TCP bridge server on localhost:65432"

    def execute(self, context):
        from .. import server as _server_mod
        _server_mod._server.start()
        return {"FINISHED"}


class BRIDGE_OT_StopServer(bpy.types.Operator):
    bl_idname = "bridge.stop_server"
    bl_label = "Stop Bridge"
    bl_description = "Stop the TCP bridge server"

    def execute(self, context):
        from .. import server as _server_mod
        _server_mod._server.stop()
        return {"FINISHED"}


_CLASSES = [BRIDGE_PT_Status, BRIDGE_OT_StartServer, BRIDGE_OT_StopServer]


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
