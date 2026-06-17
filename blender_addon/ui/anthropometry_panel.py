"""Painel do addon antropométrico (Etapa 3).

Fluxo: sexo/percentil/idade → "Aplicar Antropometria" escreve os 25 sockets de
TAMANHO derivados no modifier do objeto ativo (árvore `Biomodelo`). Os sockets de
POSE e os overrides finos ficam no painel padrão do Modifier. Presets salvam/
carregam os valores do contrato (31 sockets, incl. o scan de referência).

Não altera a árvore de nós — só escreve em `modifier[identifier]`.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup
from bpy_extras.io_utils import ExportHelper, ImportHelper

from ..biomodel import anthropometry, presets

TREE_NAME = "Biomodelo"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _biomodel_modifier(obj):
    """Retorna o modifier Nodes que usa a árvore `Biomodelo`, ou None."""
    if obj is None:
        return None
    for mod in obj.modifiers:
        if mod.type == "NODES" and mod.node_group and mod.node_group.name == TREE_NAME:
            return mod
    return None


def _scan_reference_path():
    """Acha presets/scan_referencia.json. Tenta o project root resolvido e, como
    fallback, a pasta do .blend aberto (o arquivo do projeto fica no repo)."""
    from pathlib import Path

    candidates = []
    try:
        from ..project_paths import resolve_project_root
        candidates.append(resolve_project_root() / "presets" / "scan_referencia.json")
    except Exception:
        pass
    blend = bpy.data.filepath
    if blend:
        candidates.append(Path(blend).parent / "presets" / "scan_referencia.json")
    for path in candidates:
        try:
            if path.exists():
                return path
        except Exception:
            pass
    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class BiomodelAnthroProps(PropertyGroup):
    sexo: EnumProperty(
        name="Sexo",
        items=[("masculino", "Masculino", ""), ("feminino", "Feminino", "")],
        default="masculino",
    )
    percentil: FloatProperty(name="Percentil", default=50.0, min=5.0, max=95.0)
    idade: FloatProperty(name="Idade (anos)", default=30.0, min=1.0, max=100.0)
    usar_comp_palma: BoolProperty(
        name="Override comp. de palma",
        description="Fixa o comprimento da palma (âncora) e escala a mão uniformemente",
        default=False,
    )
    comp_palma: FloatProperty(name="Comp. de palma (mm)", default=78.62, min=10.0, max=300.0)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class BIOMODEL_OT_apply_anthropometry(Operator):
    bl_idname = "biomodel.apply_anthropometry"
    bl_label = "Aplicar Antropometria"
    bl_description = "Deriva os 25 sockets de tamanho de sexo/percentil/idade e escreve no modifier ativo"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        mod = _biomodel_modifier(obj)
        if mod is None:
            self.report({"ERROR"}, "Objeto ativo não usa a árvore 'Biomodelo'")
            return {"CANCELLED"}
        props = context.scene.biomodel_anthro
        comp = props.comp_palma if props.usar_comp_palma else None
        values = anthropometry.derive_params(props.sexo, props.percentil, props.idade, comp)
        applied = presets.write_socket_values(mod, values)
        obj.update_tag()
        self.report({"INFO"}, f"Antropometria aplicada: {len(applied)}/25 sockets de tamanho")
        return {"FINISHED"}


class BIOMODEL_OT_create_object(Operator):
    bl_idname = "biomodel.create_object"
    bl_label = "Criar Biomodelo"
    bl_description = "Cria um objeto novo com modifier apontando para a árvore 'Biomodelo'"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ng = bpy.data.node_groups.get(TREE_NAME)
        if ng is None:
            self.report({"ERROR"}, f"Árvore '{TREE_NAME}' não encontrada")
            return {"CANCELLED"}
        mesh = bpy.data.meshes.new("Biomodelo_Param")
        obj = bpy.data.objects.new("Biomodelo_Param", mesh)
        context.collection.objects.link(obj)
        mod = obj.modifiers.new("GeometryNodes", "NODES")
        mod.node_group = ng
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        self.report({"INFO"}, f"Criado '{obj.name}' (use 'Aplicar Antropometria')")
        return {"FINISHED"}


class BIOMODEL_OT_load_scan_reference(Operator):
    bl_idname = "biomodel.load_scan_reference"
    bl_label = "Carregar Scan de Referência"
    bl_description = "Carrega presets/scan_referencia.json nos sockets do modifier ativo"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mod = _biomodel_modifier(context.active_object)
        if mod is None:
            self.report({"ERROR"}, "Objeto ativo não usa a árvore 'Biomodelo'")
            return {"CANCELLED"}
        path = _scan_reference_path()
        if path is None or not path.exists():
            self.report({"ERROR"}, "scan_referencia.json não encontrado (use 'Carregar Preset')")
            return {"CANCELLED"}
        values = presets.load_preset_file(str(path))
        applied = presets.write_socket_values(mod, values)
        context.active_object.update_tag()
        self.report({"INFO"}, f"Scan de referência carregado: {len(applied)} sockets")
        return {"FINISHED"}


class BIOMODEL_OT_save_preset(Operator, ExportHelper):
    bl_idname = "biomodel.save_preset"
    bl_label = "Salvar Preset"
    bl_description = "Salva os valores atuais do modifier (31 sockets) num arquivo JSON"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})
    preset_name: StringProperty(name="Nome", default="preset")
    preset_desc: StringProperty(name="Descrição", default="")

    def execute(self, context):
        mod = _biomodel_modifier(context.active_object)
        if mod is None:
            self.report({"ERROR"}, "Objeto ativo não usa a árvore 'Biomodelo'")
            return {"CANCELLED"}
        presets.save_preset_file(self.filepath, mod, name=self.preset_name, description=self.preset_desc)
        self.report({"INFO"}, f"Preset salvo: {self.filepath}")
        return {"FINISHED"}


class BIOMODEL_OT_load_preset(Operator, ImportHelper):
    bl_idname = "biomodel.load_preset"
    bl_label = "Carregar Preset"
    bl_description = "Carrega um preset JSON nos sockets do modifier ativo"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        mod = _biomodel_modifier(context.active_object)
        if mod is None:
            self.report({"ERROR"}, "Objeto ativo não usa a árvore 'Biomodelo'")
            return {"CANCELLED"}
        values = presets.load_preset_file(self.filepath)
        applied = presets.write_socket_values(mod, values)
        context.active_object.update_tag()
        self.report({"INFO"}, f"Preset carregado: {len(applied)} sockets")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class BIOMODEL_PT_Anthropometry(Panel):
    bl_label = "Biomodelo Antropométrico"
    bl_idname = "BIOMODEL_PT_Anthropometry"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Biomodelo"

    def draw(self, context):
        layout = self.layout
        props = context.scene.biomodel_anthro
        obj = context.active_object
        mod = _biomodel_modifier(obj)

        box = layout.box()
        box.label(text="Antropometria", icon="OUTLINER_OB_ARMATURE")
        box.prop(props, "sexo")
        box.prop(props, "percentil")
        box.prop(props, "idade")
        box.prop(props, "usar_comp_palma")
        if props.usar_comp_palma:
            box.prop(props, "comp_palma")

        if mod is not None:
            box.operator("biomodel.apply_anthropometry", icon="MOD_DATA_TRANSFER")
            box.label(text=f"Alvo: {obj.name}", icon="OBJECT_DATA")
        else:
            box.label(text="Objeto ativo sem árvore 'Biomodelo'", icon="ERROR")
            box.operator("biomodel.create_object", icon="ADD")

        pbox = layout.box()
        pbox.label(text="Presets", icon="PRESET")
        pbox.operator("biomodel.load_scan_reference", icon="IMPORT")
        row = pbox.row(align=True)
        row.operator("biomodel.save_preset", icon="EXPORT")
        row.operator("biomodel.load_preset", icon="IMPORT")


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

_CLASSES = [
    BiomodelAnthroProps,
    BIOMODEL_OT_apply_anthropometry,
    BIOMODEL_OT_create_object,
    BIOMODEL_OT_load_scan_reference,
    BIOMODEL_OT_save_preset,
    BIOMODEL_OT_load_preset,
    BIOMODEL_PT_Anthropometry,
]


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.biomodel_anthro = PointerProperty(type=BiomodelAnthroProps)


def unregister() -> None:
    if hasattr(bpy.types.Scene, "biomodel_anthro"):
        del bpy.types.Scene.biomodel_anthro
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
