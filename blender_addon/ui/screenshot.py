"""Screenshot capture via Windows Snipping Tool.

Runs in a background thread so the Blender UI is never blocked.
Uses SESSION from chat_session to signal completion; notifies the panel
via a direct tag_redraw call (no bpy.app.timers dependency here).
"""

from __future__ import annotations

import os
import subprocess
import threading

from .chat_session import SESSION

import bpy


def _request_redraw() -> None:
    """Trigger a UI redraw from any thread."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


def _run_screenshot_capture() -> None:
    """Capture a screenshot asynchronously using Windows Snipping Tool."""
    ps_script = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

[System.Windows.Forms.Clipboard]::Clear()
Start-Process "SnippingTool.exe" "/clip" -Wait
Start-Sleep -Milliseconds 800
$img = [System.Windows.Forms.Clipboard]::GetImage()
if ($img) {
    $path = [System.IO.Path]::Combine($env:TEMP, "blender_chat_screenshot.png")
    $img.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $img.Dispose()
    Write-Output $path
} else {
    Write-Output "NO_IMAGE"
}
'''
    notice = ""
    png_data: bytes | None = None
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=180,
        )
        output_lines = [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip()]
        path = output_lines[-1] if output_lines else ""
        if path and path != "NO_IMAGE" and os.path.exists(path):
            with open(path, "rb") as f:
                png_data = f.read()
            try:
                os.remove(path)
            except Exception:
                pass
            if len(png_data) > 8 * 1024 * 1024:
                notice = "Screenshot too large (>8MB). Capture a smaller region."
                png_data = None
            else:
                notice = f"Screenshot attached ({len(png_data) // 1024}KB)."
        else:
            notice = "No screenshot captured."
    except subprocess.TimeoutExpired:
        notice = "Screenshot capture timed out."
    except Exception as exc:
        notice = f"Screenshot failed: {exc}"

    with SESSION._lock:
        SESSION.screenshot_running = False
        if png_data is not None:
            SESSION.pending_screenshots.append(png_data)
            queue_size = len(SESSION.pending_screenshots)
            total_kb = sum(len(blob) for blob in SESSION.pending_screenshots) // 1024
            SESSION.screenshot_notice = (
                f"Screenshot attached ({queue_size} pending, {total_kb}KB total)."
            )
        else:
            SESSION.screenshot_notice = notice
    _request_redraw()


class CHAT_OT_AttachScreenshot(bpy.types.Operator):
    bl_idname = "chat.attach_screenshot"
    bl_label = "Attach Screenshot"
    bl_description = "Open Windows Snipping Tool for region capture, then attach to next message"

    def execute(self, context):
        with SESSION._lock:
            if SESSION.screenshot_running:
                self.report({"WARNING"}, "Screenshot capture already running.")
                return {"CANCELLED"}
            SESSION.screenshot_running = True
            SESSION.screenshot_notice = "Select a region in Snipping Tool..."

        thread = threading.Thread(target=_run_screenshot_capture, daemon=True)
        thread.start()
        self.report({"INFO"}, "Snipping Tool opened. Select a region to attach.")
        return {"FINISHED"}
