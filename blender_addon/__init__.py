"""Blender addon — TCP bridge for incremental GN authoring via Claude Code."""

bl_info = {
    "name": "Orthosis Bridge",
    "author": "VB Orthosis Project",
    "version": (0, 4, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Orthosis",
    "description": "TCP bridge for incremental GN authoring via Claude Code (port 65432)",
    "category": "Development",
}

import bpy


def register():
    from . import ui, server
    ui.register()
    server.register()


def unregister():
    from . import ui, server
    server.unregister()
    ui.unregister()
