"""Draft execution and result-cycle operators for the GN Copilot UI."""

from __future__ import annotations

import bpy

from . import panel_runtime as _panel
from . import panel_workspace as _workspace
from .panel_chat_turn import _send_user_message
from .cycle_state import _get_work_cycle_info, _set_work_cycle_phase

SESSION = _panel.SESSION
_get_runtime = _panel._get_runtime
_open_current_draft_in_workspace = _workspace._open_current_draft_in_workspace
_run_current_draft_text = _workspace._run_current_draft_text
_schedule_redraw = _panel._schedule_redraw

class BLEND_OT_execute_draft(bpy.types.Operator):
    bl_idname = "blend.execute_draft"
    bl_label = "Abrir para executar"
    bl_description = "Abre o draft no Text Editor, cria snapshot de seguranca e avanca para estado de execucao"

    def execute(self, context):
        info = _get_work_cycle_info()
        blend_path = info["blend_path"]
        session_id = info["session_id"]
        revision = info["revision"]

        opened, detail = _open_current_draft_in_workspace(context)
        if not opened:
            self.report({"ERROR"}, detail)
            return {"CANCELLED"}

        # Call snapshot_manager directly — operators run on the main thread so
        # bpy.ops.wm.save_as_mainfile is safe to call here without a socket round-trip.
        if session_id and blend_path:
            try:
                from ..snapshot_manager import take_snapshot
                project_root = _get_runtime().project_root
                snap_path = take_snapshot(
                    blend_path=blend_path,
                    session_id=session_id,
                    revision=revision,
                    project_root=project_root,
                )
                self.report({"INFO"}, f"Snapshot salvo: {snap_path}")
            except Exception as exc:
                self.report({"WARNING"}, f"Snapshot falhou (continuando): {exc}")

        _set_work_cycle_phase("executing")
        _schedule_redraw()
        self.report({"INFO"}, f"Draft aberto: {detail}. Clique Run Script/Alt+P e depois 'Reportar resultado'.")
        return {"FINISHED"}


class BLEND_OT_open_draft(bpy.types.Operator):
    bl_idname = "blend.open_draft"
    bl_label = "Abrir Draft"
    bl_description = "Abre o Text Editor com o draft atual sem mudar o estado do ciclo"

    def execute(self, context):
        opened, detail = _open_current_draft_in_workspace(context)
        if not opened:
            self.report({"ERROR"}, detail)
            return {"CANCELLED"}
        self.report({"INFO"}, f"Draft aberto: {detail}")
        _schedule_redraw()
        return {"FINISHED"}


class BLEND_OT_run_draft(bpy.types.Operator):
    bl_idname = "blend.run_draft"
    bl_label = "Rodar Draft"
    bl_description = "Executa manualmente o draft atual no Text Editor"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        ok, detail = _run_current_draft_text(context)
        _set_work_cycle_phase("awaiting_feedback")
        try:
            context.scene.chat_result_failed_mode = False
            context.scene.chat_result_description = ""
        except Exception:
            pass
        if not ok:
            try:
                context.scene.chat_result_failed_mode = True
                context.scene.chat_result_description = detail
            except Exception:
                pass
            self.report({"ERROR"}, detail)
            _schedule_redraw()
            return {"CANCELLED"}
        self.report({"INFO"}, f"Draft executado: {detail}. Reporte o resultado visual.")
        _schedule_redraw()
        return {"FINISHED"}


class BLEND_OT_discard_draft(bpy.types.Operator):
    bl_idname = "blend.discard_draft"
    bl_label = "Descartar"
    bl_description = "Descarta o draft e volta ao estado de conversa"

    def execute(self, context):
        _set_work_cycle_phase("idle")
        _schedule_redraw()
        return {"FINISHED"}


class BLEND_OT_report_result(bpy.types.Operator):
    bl_idname = "blend.report_result"
    bl_label = "Reportar resultado"
    bl_description = "Avança para estado de resultado — descreva o que aconteceu"

    def execute(self, context):
        _set_work_cycle_phase("awaiting_feedback")
        try:
            context.scene.chat_result_failed_mode = False
            context.scene.chat_result_description = ""
        except Exception:
            pass
        _schedule_redraw()
        return {"FINISHED"}


class BLEND_OT_result_success(bpy.types.Operator):
    bl_idname = "blend.result_success"
    bl_label = "Funcionou"
    bl_description = "Script executado com sucesso — volta ao estado de conversa"

    def execute(self, context):
        info = _get_work_cycle_info()
        revision = info["revision"]
        _set_work_cycle_phase("idle")
        # No agent call needed for success — just acknowledge in the UI and
        # return to idle so the user can continue with the next task.
        SESSION.add("assistant", f"✓ Script v{revision} aplicado com sucesso. Pode continuar.")
        _schedule_redraw()
        return {"FINISHED"}


class BLEND_OT_result_failed(bpy.types.Operator):
    bl_idname = "blend.result_failed"
    bl_label = "Nao funcionou"
    bl_description = "Mostra campo para descrever o que aconteceu"

    def execute(self, context):
        try:
            context.scene.chat_result_failed_mode = True
        except Exception:
            pass
        _schedule_redraw()
        return {"FINISHED"}


class BLEND_OT_send_result_report(bpy.types.Operator):
    bl_idname = "blend.send_result_report"
    bl_label = "Enviar relatorio"
    bl_description = "Envia o relatório de falha ao agente como EXECUTION_FEEDBACK"

    def execute(self, context):
        info = _get_work_cycle_info()
        revision = info["revision"]
        try:
            description = str(getattr(context.scene, "chat_result_description", "") or "").strip()
        except Exception:
            description = ""
        if not description:
            self.report({"WARNING"}, "Descreva o que aconteceu antes de enviar.")
            return {"CANCELLED"}

        structured = (
            f"[RESULTADO DE EXECUÇÃO — Revisão v{revision}]\n"
            f"Resultado: FALHOU\n"
            f"Descrição: {description}\n"
        )
        _set_work_cycle_phase("idle")
        try:
            context.scene.chat_result_failed_mode = False
            context.scene.chat_result_description = ""
        except Exception:
            pass
        result, error = _send_user_message(context, structured, display_text=f"[Resultado: falhou] {description}")
        if "CANCELLED" in result and error:
            self.report({"WARNING"}, error)
        _schedule_redraw()
        return {"FINISHED"}


class BLEND_OT_send_and_revert(bpy.types.Operator):
    """Envia o relatorio de falha ao agente E reverte o snapshot ao mesmo tempo."""
    bl_idname = "blend.send_and_revert"
    bl_label = "Enviar e Reverter"
    bl_description = (
        "Envia a descricao da falha ao agente para discussao E reverte o Blender "
        "para o estado anterior ao script — tudo em um passo"
    )

    def execute(self, context):
        info = _get_work_cycle_info()
        revision = info["revision"]
        blend_path = info["blend_path"]
        session_id = info["session_id"]

        try:
            description = str(getattr(context.scene, "chat_result_description", "") or "").strip()
        except Exception:
            description = ""
        if not description:
            self.report({"WARNING"}, "Descreva o que aconteceu antes de enviar.")
            return {"CANCELLED"}

        # Step 1: send feedback to the agent (non-blocking). The snapshot is
        # restored only after a successful response so API/auth failures leave
        # the user's current Blender state and feedback form intact.
        structured = (
            f"[RESULTADO DE EXECUÇÃO — Revisão v{revision}]\n"
            f"Resultado: FALHOU\n"
            f"Descrição: {description}\n"
            f"Acao solicitada: apos a sua resposta, o Blender sera reaberto no snapshot anterior ao script.\n"
        )
        messages_before = len(SESSION.get_messages())
        result, error = _send_user_message(context, structured, display_text=f"[Falhou + Revertendo] {description}")
        if "CANCELLED" in result and error:
            self.report({"WARNING"}, f"Nao foi possivel enviar: {error}")
            return {"CANCELLED"}

        # Step 2: copy snapshot over the blend file NOW (disk state reverted
        # immediately), but defer the bpy.ops.wm.open_mainfile until the agent
        # background thread finishes — so the user sees the discussion response
        # before Blender reloads.
        if session_id and blend_path:
            try:
                from ..snapshot_manager import list_snapshots
                project_root = _get_runtime().project_root
                snapshots = list_snapshots(session_id=session_id, project_root=project_root)
                if snapshots:
                    latest = snapshots[0]["path"]
                    # Schedule the reopen for after the agent responds.
                    _panel._deferred_reopen_path = blend_path
                    _panel._deferred_reopen_snapshot_path = latest
                    _panel._deferred_reopen_min_messages = messages_before + 2
                    self.report({"INFO"}, "Feedback enviado. Aguardando resposta do agente — o arquivo sera reaberto logo apos.")
                else:
                    self.report({"WARNING"}, "Feedback enviado, mas nenhum snapshot encontrado para reverter.")
            except Exception as exc:
                self.report({"WARNING"}, f"Feedback enviado, mas o restore falhou: {exc}")
        else:
            self.report({"INFO"}, "Feedback enviado. Sem snapshot disponivel para reverter.")

        _schedule_redraw()
        return {"FINISHED"}


class BLEND_OT_revert_snapshot(bpy.types.Operator):
    bl_idname = "blend.revert_snapshot"
    bl_label = "Reverter snapshot"
    bl_description = "Restaura o arquivo .blend para o snapshot anterior à execução"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        info = _get_work_cycle_info()
        blend_path = info["blend_path"]
        session_id = info["session_id"]

        if not session_id or not blend_path:
            self.report({"ERROR"}, "Nenhum snapshot disponível para esta sessão.")
            return {"CANCELLED"}

        try:
            from ..snapshot_manager import list_snapshots, restore_snapshot
            project_root = _get_runtime().project_root
            snapshots = list_snapshots(session_id=session_id, project_root=project_root)
            if not snapshots:
                self.report({"WARNING"}, "Nenhum snapshot encontrado para esta sessão.")
                return {"CANCELLED"}
            latest = snapshots[0]["path"]
            restore_snapshot(snapshot_path=latest, target_path=blend_path)
            self.report({"INFO"}, "Snapshot restaurado. O arquivo será reaberto em breve.")
        except Exception as exc:
            self.report({"ERROR"}, f"Restore falhou: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


# ---------------------------------------------------------------------------




CYCLE_OPERATOR_CLASSES = (
    BLEND_OT_execute_draft,
    BLEND_OT_open_draft,
    BLEND_OT_run_draft,
    BLEND_OT_discard_draft,
    BLEND_OT_report_result,
    BLEND_OT_result_success,
    BLEND_OT_result_failed,
    BLEND_OT_send_result_report,
    BLEND_OT_send_and_revert,
    BLEND_OT_revert_snapshot,
)
