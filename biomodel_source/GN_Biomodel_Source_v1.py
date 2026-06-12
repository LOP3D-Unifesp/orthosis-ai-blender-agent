# GN_Biomodel_Source
# Biomodelo parametrizavel de membro superior — v1 (consolidado em 2026-06-12 18:54 UTC)
#
# Gerado automaticamente a partir da arvore de desenvolvimento validada
# (regressao numerica em 4 poses + validacao visual contra scan).
# Estrutura: 12 frames, FK matricial (polegar inline, dedos via node group),
# 41 parametros clinicos em 5 paineis. Defaults = valores clinicos da sessao.
#
# Executar este script no Blender cria/substitui SOMENTE:
#   - 'VB_FK_Cadeia_Dedo'      (node group FK reutilizavel dos dedos longos)
#   - 'VB_Biomodel_Generated'  (arvore Geometry Nodes do biomodelo)
# A arvore de referencia/desenvolvimento NAO e tocada.

import bpy

SOURCE_VERSION = "1.0.0"
GENERATED_TREE_NAME = "VB_Biomodel_Generated"
GENERATED_GROUP_NAME = "VB_FK_Cadeia_Dedo"

# Nos cujos sockets sao enderecados por NOME (identifiers de interface sao
# re-atribuidos pelo Blender a cada reconstrucao); demais usam socket.identifier.
NAME_ADDRESSED = {"NodeGroupInput", "NodeGroupOutput", "GeometryNodeGroup"}

# ============================ DADOS: INTERFACE =============================
INTERFACE = [
    {'kind': 'socket', 'name': 'Geometry', 'in_out': 'OUTPUT', 'socket_type': 'NodeSocketGeometry', 'parent': None},
    {'kind': 'panel', 'name': 'Antebraço', 'parent': None, 'closed': False},
    {'kind': 'socket', 'name': 'Comp Antebraço', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Antebraço', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 230.200012},
    {'kind': 'socket', 'name': 'Raio Cotovelo', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Antebraço', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 37.299999},
    {'kind': 'socket', 'name': 'Raio Punho', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Antebraço', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 24.929998},
    {'kind': 'socket', 'name': 'Desvio Rad/Ulnar Punho', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Antebraço', 'subtype': 'NONE', 'min_value': -35.0, 'max_value': 20.0, 'default': -5.37},
    {'kind': 'socket', 'name': 'Flex/Ext Punho', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Antebraço', 'subtype': 'NONE', 'min_value': -25.0, 'max_value': 40.0, 'default': 0.0},
    {'kind': 'panel', 'name': 'Palma', 'parent': None, 'closed': False},
    {'kind': 'socket', 'name': 'Curva Palma Metacarpo 1', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Palma', 'subtype': 'ANGLE', 'min_value': -3.14159, 'max_value': 6.28318, 'default': 0.0},
    {'kind': 'socket', 'name': 'Curva Palma Metacarpo 2', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Palma', 'subtype': 'ANGLE', 'min_value': -3.14159, 'max_value': 6.28318, 'default': 0.0},
    {'kind': 'socket', 'name': 'Comp Metacarpo', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Palma', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 78.620033},
    {'kind': 'socket', 'name': 'Largura Metacarpo', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Palma', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 35.739998},
    {'kind': 'socket', 'name': 'Espessura Metacarpo', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Palma', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 29.499996},
    {'kind': 'panel', 'name': 'Polegar', 'parent': None, 'closed': False},
    {'kind': 'socket', 'name': 'Comp Metacarpo Polegar', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Polegar', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 48.740002},
    {'kind': 'socket', 'name': 'Largura Metacarpo Polegar', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Polegar', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 26.369999},
    {'kind': 'socket', 'name': 'Espessura Metacarpo Polegar', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Polegar', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 25.940001},
    {'kind': 'socket', 'name': 'Flex/Ext Polegar', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Polegar', 'subtype': 'NONE', 'min_value': -3.0, 'max_value': 25.0, 'default': 0.0},
    {'kind': 'socket', 'name': 'Abdução Polegar', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Polegar', 'subtype': 'NONE', 'min_value': -15.0, 'max_value': 15.0, 'default': 15.0},
    {'kind': 'socket', 'name': 'Flex/Ext Falange Prox Polegar', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Polegar', 'subtype': 'NONE', 'min_value': -20.0, 'max_value': 110.0, 'default': 4.719998},
    {'kind': 'socket', 'name': 'Flex/Ext Falange Dist Polegar', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Polegar', 'subtype': 'NONE', 'min_value': -20.0, 'max_value': 110.0, 'default': -17.820004},
    {'kind': 'socket', 'name': 'Comp Falange Prox Polegar', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Polegar', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 27.799997},
    {'kind': 'socket', 'name': 'Espessura Falange Prox Polegar', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Polegar', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 26.109997},
    {'kind': 'socket', 'name': 'Comp Falange Dist Polegar', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Polegar', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 20.530001},
    {'kind': 'socket', 'name': 'Espessura Falange Dist Polegar', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Polegar', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 21.66},
    {'kind': 'panel', 'name': 'Dedos 1 (indicador+médio agrupados)', 'parent': None, 'closed': False},
    {'kind': 'socket', 'name': 'Abdução Dedo 1', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 1 (indicador+médio agrupados)', 'subtype': 'NONE', 'min_value': -15.0, 'max_value': 45.0, 'default': 26.99},
    {'kind': 'socket', 'name': 'Flex/Ext Falange Prox 1', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 1 (indicador+médio agrupados)', 'subtype': 'NONE', 'min_value': -20.0, 'max_value': 110.0, 'default': 0.0},
    {'kind': 'socket', 'name': 'Flex/Ext Falange Media 1', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 1 (indicador+médio agrupados)', 'subtype': 'NONE', 'min_value': -20.0, 'max_value': 110.0, 'default': 0.0},
    {'kind': 'socket', 'name': 'Flex/Ext Falange Dist 1', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 1 (indicador+médio agrupados)', 'subtype': 'NONE', 'min_value': -20.0, 'max_value': 110.0, 'default': 0.0},
    {'kind': 'socket', 'name': 'Comp Falange Prox 1', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 1 (indicador+médio agrupados)', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 53.039997},
    {'kind': 'socket', 'name': 'Espessura Falange Prox 1', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 1 (indicador+médio agrupados)', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 25.0},
    {'kind': 'socket', 'name': 'Comp Falange Media 1', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 1 (indicador+médio agrupados)', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 23.989998},
    {'kind': 'socket', 'name': 'Espessura Falange Media 1', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 1 (indicador+médio agrupados)', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 22.0},
    {'kind': 'socket', 'name': 'Comp Falange Dist 1', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 1 (indicador+médio agrupados)', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 30.310001},
    {'kind': 'socket', 'name': 'Espessura Falange Dist 1', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 1 (indicador+médio agrupados)', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 15.599999},
    {'kind': 'panel', 'name': 'Dedos 2 (anelar+mínimo agrupados)', 'parent': None, 'closed': False},
    {'kind': 'socket', 'name': 'Abdução Dedo 2', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 2 (anelar+mínimo agrupados)', 'subtype': 'NONE', 'min_value': -15.0, 'max_value': 45.0, 'default': 11.82},
    {'kind': 'socket', 'name': 'Flex/Ext Falange Prox 2', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 2 (anelar+mínimo agrupados)', 'subtype': 'NONE', 'min_value': -20.0, 'max_value': 110.0, 'default': 0.0},
    {'kind': 'socket', 'name': 'Flex/Ext Falange Media 2', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 2 (anelar+mínimo agrupados)', 'subtype': 'NONE', 'min_value': -20.0, 'max_value': 110.0, 'default': 0.0},
    {'kind': 'socket', 'name': 'Flex/Ext Falange Dist 2', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 2 (anelar+mínimo agrupados)', 'subtype': 'NONE', 'min_value': -20.0, 'max_value': 110.0, 'default': 0.0},
    {'kind': 'socket', 'name': 'Comp Falange Prox 2', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 2 (anelar+mínimo agrupados)', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 62.509995},
    {'kind': 'socket', 'name': 'Espessura Falange Prox 2', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 2 (anelar+mínimo agrupados)', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 24.709999},
    {'kind': 'socket', 'name': 'Comp Falange Media 2', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 2 (anelar+mínimo agrupados)', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 23.07},
    {'kind': 'socket', 'name': 'Espessura Falange Media 2', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 2 (anelar+mínimo agrupados)', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 19.23},
    {'kind': 'socket', 'name': 'Comp Falange Dist 2', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 2 (anelar+mínimo agrupados)', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 32.889999},
    {'kind': 'socket', 'name': 'Espessura Falange Dist 2', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': 'Dedos 2 (anelar+mínimo agrupados)', 'subtype': 'DISTANCE', 'min_value': 0.0, 'max_value': 3.4028234663852886e+38, 'default': 21.85},
]

GROUP_INTERFACE = [
    {'kind': 'socket', 'name': 'Matriz Prox', 'in_out': 'OUTPUT', 'socket_type': 'NodeSocketMatrix', 'parent': None},
    {'kind': 'socket', 'name': 'Matriz Media', 'in_out': 'OUTPUT', 'socket_type': 'NodeSocketMatrix', 'parent': None},
    {'kind': 'socket', 'name': 'Matriz Dist', 'in_out': 'OUTPUT', 'socket_type': 'NodeSocketMatrix', 'parent': None},
    {'kind': 'socket', 'name': 'Ponta MC', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': None, 'subtype': 'NONE', 'min_value': -3.4028234663852886e+38, 'max_value': 3.4028234663852886e+38, 'default': 0.0},
    {'kind': 'socket', 'name': 'Comp Prox', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': None, 'subtype': 'NONE', 'min_value': -3.4028234663852886e+38, 'max_value': 3.4028234663852886e+38, 'default': 30.0},
    {'kind': 'socket', 'name': 'Comp Media', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': None, 'subtype': 'NONE', 'min_value': -3.4028234663852886e+38, 'max_value': 3.4028234663852886e+38, 'default': 25.0},
    {'kind': 'socket', 'name': 'Comp Dist', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': None, 'subtype': 'NONE', 'min_value': -3.4028234663852886e+38, 'max_value': 3.4028234663852886e+38, 'default': 20.0},
    {'kind': 'socket', 'name': 'Flex Prox', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': None, 'subtype': 'NONE', 'min_value': -3.4028234663852886e+38, 'max_value': 3.4028234663852886e+38, 'default': 0.0},
    {'kind': 'socket', 'name': 'Flex Media', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': None, 'subtype': 'NONE', 'min_value': -3.4028234663852886e+38, 'max_value': 3.4028234663852886e+38, 'default': 0.0},
    {'kind': 'socket', 'name': 'Flex Dist', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': None, 'subtype': 'NONE', 'min_value': -3.4028234663852886e+38, 'max_value': 3.4028234663852886e+38, 'default': 0.0},
    {'kind': 'socket', 'name': 'Abducao', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': None, 'subtype': 'NONE', 'min_value': -3.4028234663852886e+38, 'max_value': 3.4028234663852886e+38, 'default': 0.0},
    {'kind': 'socket', 'name': 'Direcao Abd', 'in_out': 'INPUT', 'socket_type': 'NodeSocketFloat', 'parent': None, 'subtype': 'NONE', 'min_value': -3.4028234663852886e+38, 'max_value': 3.4028234663852886e+38, 'default': 1.0},
]

# ============================ DADOS: NOS ===================================
GROUP_NODES = [
    {'name': 'Entradas', 'type': 'NodeGroupInput', 'loc': [0.0, -300.0]},
    {'name': 'Saidas', 'type': 'NodeGroupOutput', 'loc': [3120.0, -300.0]},
    {'name': 'negPonta', 'type': 'ShaderNodeMath', 'loc': [240.0, 0.0], 'operation': 'MULTIPLY', 'defaults': [['Value_001', -1.0], ['Value_002', 0.5]]},
    {'name': 'j0v', 'type': 'ShaderNodeCombineXYZ', 'loc': [480.0, 0.0], 'defaults': [['X', 0.0], ['Z', 0.0]]},
    {'name': 'ctJ0', 'type': 'FunctionNodeCombineTransform', 'loc': [720.0, 0.0], 'defaults': [['Rotation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'abdRad', 'type': 'ShaderNodeMath', 'loc': [240.0, -150.0], 'operation': 'RADIANS', 'defaults': [['Value_001', 0.5], ['Value_002', 0.5]]},
    {'name': 'abdSigned', 'type': 'ShaderNodeMath', 'loc': [480.0, -150.0], 'operation': 'MULTIPLY', 'defaults': [['Value_002', 0.5]]},
    {'name': 'abdv', 'type': 'ShaderNodeCombineXYZ', 'loc': [720.0, -150.0], 'defaults': [['X', 0.0], ['Y', 0.0]]},
    {'name': 'etrA', 'type': 'FunctionNodeEulerToRotation', 'loc': [960.0, -150.0]},
    {'name': 'ctA', 'type': 'FunctionNodeCombineTransform', 'loc': [1200.0, -150.0], 'defaults': [['Translation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'JA', 'type': 'FunctionNodeMatrixMultiply', 'loc': [1440.0, 0.0]},
    {'name': 'rad0', 'type': 'ShaderNodeMath', 'loc': [240.0, -300.0], 'operation': 'RADIANS', 'defaults': [['Value_001', 0.5], ['Value_002', 0.5]]},
    {'name': 'rotv0', 'type': 'ShaderNodeCombineXYZ', 'loc': [480.0, -300.0], 'defaults': [['Y', 0.0], ['Z', 0.0]]},
    {'name': 'etr0', 'type': 'FunctionNodeEulerToRotation', 'loc': [720.0, -300.0]},
    {'name': 'ctR0', 'type': 'FunctionNodeCombineTransform', 'loc': [960.0, -300.0], 'defaults': [['Translation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'rad1', 'type': 'ShaderNodeMath', 'loc': [240.0, -450.0], 'operation': 'RADIANS', 'defaults': [['Value_001', 0.5], ['Value_002', 0.5]]},
    {'name': 'rotv1', 'type': 'ShaderNodeCombineXYZ', 'loc': [480.0, -450.0], 'defaults': [['Y', 0.0], ['Z', 0.0]]},
    {'name': 'etr1', 'type': 'FunctionNodeEulerToRotation', 'loc': [720.0, -450.0]},
    {'name': 'ctR1', 'type': 'FunctionNodeCombineTransform', 'loc': [960.0, -450.0], 'defaults': [['Translation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'rad2', 'type': 'ShaderNodeMath', 'loc': [240.0, -600.0], 'operation': 'RADIANS', 'defaults': [['Value_001', 0.5], ['Value_002', 0.5]]},
    {'name': 'rotv2', 'type': 'ShaderNodeCombineXYZ', 'loc': [480.0, -600.0], 'defaults': [['Y', 0.0], ['Z', 0.0]]},
    {'name': 'etr2', 'type': 'FunctionNodeEulerToRotation', 'loc': [720.0, -600.0]},
    {'name': 'ctR2', 'type': 'FunctionNodeCombineTransform', 'loc': [960.0, -600.0], 'defaults': [['Translation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'M0', 'type': 'FunctionNodeMatrixMultiply', 'loc': [1680.0, 0.0]},
    {'name': 'negHalf0', 'type': 'ShaderNodeMath', 'loc': [1920.0, -750.0], 'operation': 'MULTIPLY', 'defaults': [['Value_001', -0.5], ['Value_002', 0.5]]},
    {'name': 'offv0', 'type': 'ShaderNodeCombineXYZ', 'loc': [2160.0, -750.0], 'defaults': [['X', 0.0], ['Z', 0.0]]},
    {'name': 'ctOff0', 'type': 'FunctionNodeCombineTransform', 'loc': [2400.0, -750.0], 'defaults': [['Rotation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'cube0', 'type': 'FunctionNodeMatrixMultiply', 'loc': [2640.0, -750.0]},
    {'name': 'negLen1', 'type': 'ShaderNodeMath', 'loc': [1680.0, -900.0], 'operation': 'MULTIPLY', 'defaults': [['Value_001', -1.0], ['Value_002', 0.5]]},
    {'name': 'd1v', 'type': 'ShaderNodeCombineXYZ', 'loc': [1920.0, -900.0], 'defaults': [['X', 0.0], ['Z', 0.0]]},
    {'name': 'ctd1', 'type': 'FunctionNodeCombineTransform', 'loc': [2160.0, -900.0], 'defaults': [['Rotation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'A1', 'type': 'FunctionNodeMatrixMultiply', 'loc': [2400.0, -900.0]},
    {'name': 'M1', 'type': 'FunctionNodeMatrixMultiply', 'loc': [2640.0, -900.0]},
    {'name': 'negHalf1', 'type': 'ShaderNodeMath', 'loc': [1920.0, -1050.0], 'operation': 'MULTIPLY', 'defaults': [['Value_001', -0.5], ['Value_002', 0.5]]},
    {'name': 'offv1', 'type': 'ShaderNodeCombineXYZ', 'loc': [2160.0, -1050.0], 'defaults': [['X', 0.0], ['Z', 0.0]]},
    {'name': 'ctOff1', 'type': 'FunctionNodeCombineTransform', 'loc': [2400.0, -1050.0], 'defaults': [['Rotation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'cube1', 'type': 'FunctionNodeMatrixMultiply', 'loc': [2640.0, -1050.0]},
    {'name': 'negLen2', 'type': 'ShaderNodeMath', 'loc': [1680.0, -1200.0], 'operation': 'MULTIPLY', 'defaults': [['Value_001', -1.0], ['Value_002', 0.5]]},
    {'name': 'd2v', 'type': 'ShaderNodeCombineXYZ', 'loc': [1920.0, -1200.0], 'defaults': [['X', 0.0], ['Z', 0.0]]},
    {'name': 'ctd2', 'type': 'FunctionNodeCombineTransform', 'loc': [2160.0, -1200.0], 'defaults': [['Rotation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'A2', 'type': 'FunctionNodeMatrixMultiply', 'loc': [2400.0, -1200.0]},
    {'name': 'M2', 'type': 'FunctionNodeMatrixMultiply', 'loc': [2640.0, -1200.0]},
    {'name': 'negHalf2', 'type': 'ShaderNodeMath', 'loc': [1920.0, -1350.0], 'operation': 'MULTIPLY', 'defaults': [['Value_001', -0.5], ['Value_002', 0.5]]},
    {'name': 'offv2', 'type': 'ShaderNodeCombineXYZ', 'loc': [2160.0, -1350.0], 'defaults': [['X', 0.0], ['Z', 0.0]]},
    {'name': 'ctOff2', 'type': 'FunctionNodeCombineTransform', 'loc': [2400.0, -1350.0], 'defaults': [['Rotation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'cube2', 'type': 'FunctionNodeMatrixMultiply', 'loc': [2640.0, -1350.0]},
]

NODES = [
    {'name': 'Frame.007', 'type': 'NodeFrame', 'label': '📐 Antebraço / Punho', 'loc': [1810.0, 36.0]},
    {'name': 'Frame.008', 'type': 'NodeFrame', 'label': '🔄 Rotações Punho', 'loc': [3060.0, 36.0]},
    {'name': 'Frame.009', 'type': 'NodeFrame', 'label': '👍 Polegar — Primitivas', 'loc': [3530.0, -2514.0]},
    {'name': 'Frame.010', 'type': 'NodeFrame', 'label': '🔄 Rotações Polegar', 'loc': [5440.0, -2514.0]},
    {'name': 'Frame.011', 'type': 'NodeFrame', 'label': '🦴 Metacarpos', 'loc': [-30.0, -1208.0]},
    {'name': 'Frame.012', 'type': 'NodeFrame', 'label': '🦴 Dedo 1 (radial) — Falanges', 'loc': [3790.0, -1208.0]},
    {'name': 'Frame.013', 'type': 'NodeFrame', 'label': '🦴 Dedo 2 (ulnar) — Falanges', 'loc': [5700.0, -1208.0]},
    {'name': 'Frame.014', 'type': 'NodeFrame', 'label': '📥 Entradas', 'loc': [-30.0, 36.0]},
    {'name': 'Frame.015', 'type': 'NodeFrame', 'label': '🔗 Montagem Final', 'loc': [4640.0, 36.0]},
    {'name': 'Frame.016', 'type': 'NodeFrame', 'label': '⚙️ Cálculos Auxiliares', 'loc': [560.0, 36.0]},
    {'name': 'Frame_FK_Dedos', 'type': 'NodeFrame', 'label': '🧮 FK Dedos — grupo FK_Cadeia_Dedo', 'loc': [2540.0, -1208.0]},
    {'name': 'Frame_FK_Polegar', 'type': 'NodeFrame', 'label': '🧮 FK Polegar — cadeia matricial', 'loc': [-30.0, -2514.0]},
    {'name': 'Group Output', 'type': 'NodeGroupOutput', 'label': '', 'loc': [1020.0, -36.0], 'parent': 'Frame.015'},
    {'name': 'Cube_Polegar1', 'type': 'GeometryNodeMeshCube', 'label': 'Cube_Metacarpo_Polegar1', 'loc': [690.0, -36.0], 'parent': 'Frame.009', 'defaults': [['Vertices X', 2], ['Vertices Y', 2], ['Vertices Z', 2]]},
    {'name': 'TF_Polegar1', 'type': 'GeometryNodeTransform', 'label': 'TG_Metacarpo_Polegar1', 'loc': [1020.0, -320.0], 'parent': 'Frame.009', 'defaults': [['Mode', 'Matrix'], ['Translation', [27.100002, -85.250015, 0.0]], ['Rotation', [0.0, 0.0, 0.472984]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'Join_Polegar_Raw', 'type': 'GeometryNodeJoinGeometry', 'loc': [1350.0, -36.0], 'parent': 'Frame.009'},
    {'name': 'Join_Geral', 'type': 'GeometryNodeJoinGeometry', 'loc': [360.0, -36.0], 'parent': 'Frame.015'},
    {'name': 'Cube_Polegar2', 'type': 'GeometryNodeMeshCube', 'label': 'Cube_Falange_Proximal_Polegar2', 'loc': [690.0, -249.0], 'parent': 'Frame.009', 'defaults': [['Vertices X', 2], ['Vertices Y', 2], ['Vertices Z', 2]]},
    {'name': 'TF_Polegar2', 'type': 'GeometryNodeTransform', 'label': 'TG_Falange_Proximal_Polegar2', 'loc': [1020.0, -178.0], 'parent': 'Frame.009', 'defaults': [['Mode', 'Matrix'], ['Translation', [45.399998, -119.750023, 0.0]], ['Rotation', [0.0, 0.0, 0.397935]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'Cube_Polegar3', 'type': 'GeometryNodeMeshCube', 'label': 'Cube_Falange_Distal_Polegar3', 'loc': [690.0, -462.0], 'parent': 'Frame.009', 'defaults': [['Vertices X', 2], ['Vertices Y', 2], ['Vertices Z', 2]]},
    {'name': 'TF_Polegar3', 'type': 'GeometryNodeTransform', 'label': 'TG_Falange_Distal_Polegar4', 'loc': [1020.0, -36.0], 'parent': 'Frame.009', 'defaults': [['Mode', 'Matrix'], ['Translation', [58.600002, -148.950012, 0.0]], ['Rotation', [0.0, 0.0, 0.459022]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'Cube_Metacarpo2', 'type': 'GeometryNodeMeshCube', 'label': 'Cube_Falange_Proximal_11', 'loc': [690.0, -36.0], 'parent': 'Frame.012', 'defaults': [['Vertices X', 2], ['Vertices Y', 2], ['Vertices Z', 2]]},
    {'name': 'TF_Metacarpo2', 'type': 'GeometryNodeTransform', 'label': 'TG_Falange_Proximal_11', 'loc': [1020.0, -36.0], 'parent': 'Frame.012', 'defaults': [['Mode', 'Matrix'], ['Translation', [0.034, -126.049988, 0.0]], ['Rotation', [0.0, 0.0, -0.548033]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'Cube_Falange11', 'type': 'GeometryNodeMeshCube', 'label': 'Cube_Falange_Media_12', 'loc': [690.0, -249.0], 'parent': 'Frame.012', 'defaults': [['Vertices X', 2], ['Vertices Y', 2], ['Vertices Z', 2]]},
    {'name': 'TF_Falange11', 'type': 'GeometryNodeTransform', 'label': 'TG_Falange_Media_12', 'loc': [1020.0, -178.0], 'parent': 'Frame.012', 'defaults': [['Mode', 'Matrix'], ['Translation', [-29.800001, -147.950012, 0.0]], ['Rotation', [0.0, 0.0, -0.565487]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'Cube_Falange12', 'type': 'GeometryNodeMeshCube', 'label': 'Cube_Falange_Distal_13', 'loc': [690.0, -462.0], 'parent': 'Frame.012', 'defaults': [['Vertices X', 2], ['Vertices Y', 2], ['Vertices Z', 2]]},
    {'name': 'TF_Falange12', 'type': 'GeometryNodeTransform', 'label': 'TG_Falange_Distal_13', 'loc': [1020.0, -320.0], 'parent': 'Frame.012', 'defaults': [['Mode', 'Matrix'], ['Translation', [-47.299992, -175.849976, 0.0]], ['Rotation', [0.0, 0.0, -0.579449]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'Cube_Falange22', 'type': 'GeometryNodeMeshCube', 'label': 'Cube_FalangProximal_21', 'loc': [690.0, -36.0], 'parent': 'Frame.013', 'defaults': [['Vertices X', 2], ['Vertices Y', 2], ['Vertices Z', 2]]},
    {'name': 'TF_Falange22', 'type': 'GeometryNodeTransform', 'label': 'TG_Falange_Proximal_21', 'loc': [1020.0, -36.0], 'parent': 'Frame.013', 'defaults': [['Mode', 'Matrix'], ['Translation', [8.2, -137.050003, 0.0]], ['Rotation', [0.0, 0.0, 0.153589]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'Cube_Falange23', 'type': 'GeometryNodeMeshCube', 'label': 'Cube_Falange_Media_22', 'loc': [690.0, -249.0], 'parent': 'Frame.013', 'defaults': [['Vertices X', 2], ['Vertices Y', 2], ['Vertices Z', 2]]},
    {'name': 'TF_Falange23', 'type': 'GeometryNodeTransform', 'label': 'TG_Falange_Media_22', 'loc': [1020.0, -178.0], 'parent': 'Frame.013', 'defaults': [['Mode', 'Matrix'], ['Translation', [16.6, -178.25, 0.0]], ['Rotation', [0.0, 0.0, 0.15708]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'Join_Polegar', 'type': 'GeometryNodeJoinGeometry', 'loc': [30.0, -134.0], 'parent': 'Frame.015'},
    {'name': 'Join_Metacarpos', 'type': 'GeometryNodeJoinGeometry', 'loc': [1350.0, -36.0], 'parent': 'Frame.012'},
    {'name': 'Join_Falanges', 'type': 'GeometryNodeJoinGeometry', 'loc': [1350.0, -36.0], 'parent': 'Frame.013'},
    {'name': 'Join_MaoBruta', 'type': 'GeometryNodeJoinGeometry', 'loc': [360.0, -134.0], 'parent': 'Frame.015'},
    {'name': 'Math_UlnarRad', 'type': 'ShaderNodeMath', 'loc': [30.0, -36.0], 'parent': 'Frame.008', 'operation': 'RADIANS', 'defaults': [['Value_001', 0.5], ['Value_002', 0.5]]},
    {'name': 'CXYZ_UlnarRot', 'type': 'ShaderNodeCombineXYZ', 'loc': [360.0, -36.0], 'parent': 'Frame.008', 'defaults': [['X', 0.0], ['Y', 0.0]]},
    {'name': 'TF_DesvioUlnar', 'type': 'GeometryNodeTransform', 'label': 'TG_DesvioUlnar', 'loc': [690.0, -36.0], 'parent': 'Frame.008', 'defaults': [['Mode', 'Components'], ['Translation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'Math_AbdRad', 'type': 'ShaderNodeMath', 'loc': [360.0, -36.0], 'parent': 'Frame.010', 'operation': 'RADIANS', 'defaults': [['Value_001', 0.5], ['Value_002', 0.5]]},
    {'name': 'CXYZ_AbdRot', 'type': 'ShaderNodeCombineXYZ', 'loc': [690.0, -36.0], 'parent': 'Frame.010', 'defaults': [['X', 0.0], ['Y', 0.0]]},
    {'name': 'TF_AbducaoPolegar', 'type': 'GeometryNodeTransform', 'label': 'TG_AbducaoPolegar', 'loc': [1020.0, -36.0], 'parent': 'Frame.010', 'defaults': [['Mode', 'Components'], ['Translation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'Cube_Falange23.001', 'type': 'GeometryNodeMeshCube', 'label': 'Cube_Falange_Distal_23', 'loc': [690.0, -462.0], 'parent': 'Frame.013', 'defaults': [['Vertices X', 2], ['Vertices Y', 2], ['Vertices Z', 2]]},
    {'name': 'TF_Falange23.001', 'type': 'GeometryNodeTransform', 'label': 'TG_Falange_Distal23', 'loc': [1020.0, -320.0], 'parent': 'Frame.013', 'defaults': [['Mode', 'Matrix'], ['Translation', [17.000002, -209.650009, 0.0]], ['Rotation', [0.0, 0.0, 0.146608]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'Math_ExtFlexRad', 'type': 'ShaderNodeMath', 'loc': [30.0, -212.0], 'parent': 'Frame.008', 'operation': 'RADIANS', 'defaults': [['Value_001', 0.5], ['Value_002', 0.5]]},
    {'name': 'CXYZ_ExtFlexRot', 'type': 'ShaderNodeCombineXYZ', 'loc': [360.0, -205.0], 'parent': 'Frame.008', 'defaults': [['Y', 0.0], ['Z', 0.0]]},
    {'name': 'TF_ExtensaoFlexao', 'type': 'GeometryNodeTransform', 'label': 'TG_ExtensaoFlexao', 'loc': [1020.0, -36.0], 'parent': 'Frame.008', 'defaults': [['Mode', 'Components'], ['Translation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'Math_ExtFlexPolegarRad', 'type': 'ShaderNodeMath', 'loc': [360.0, -212.0], 'parent': 'Frame.010', 'operation': 'RADIANS', 'defaults': [['Value_001', 0.5], ['Value_002', 0.5]]},
    {'name': 'CXYZ_ExtFlexPolegarRot', 'type': 'ShaderNodeCombineXYZ', 'loc': [690.0, -205.0], 'parent': 'Frame.010', 'defaults': [['Y', 0.0], ['Z', 0.0]]},
    {'name': 'TF_ExtFlexPolegar', 'type': 'GeometryNodeTransform', 'label': 'TG_ExtFlexPolegar', 'loc': [1350.0, -36.0], 'parent': 'Frame.010', 'defaults': [['Mode', 'Components'], ['Translation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'Cone_Antebraco.001', 'type': 'GeometryNodeMeshCone', 'label': 'Cone_Antebraco', 'loc': [360.0, -36.0], 'parent': 'Frame.007', 'defaults': [['Vertices', 32], ['Side Segments', 1], ['Fill Segments', 1]]},
    {'name': 'TF_Antebraco.001', 'type': 'GeometryNodeTransform', 'label': 'TF_Antebraco', 'loc': [690.0, -36.0], 'parent': 'Frame.007', 'defaults': [['Mode', 'Components'], ['Translation', [0.0, 0.0, 0.0]], ['Rotation', [-1.570796, 0.0, 0.0]], ['Scale', [1.0, 0.8, 1.0]]]},
    {'name': 'UVSphere_Punho.001', 'type': 'GeometryNodeMeshUVSphere', 'label': 'UVSphere_Carpo', 'loc': [360.0, -383.0], 'parent': 'Frame.007', 'defaults': [['Segments', 32], ['Rings', 16]]},
    {'name': 'TF_Punho.001', 'type': 'GeometryNodeTransform', 'label': 'TF_Carpo', 'loc': [690.0, -408.0], 'parent': 'Frame.007', 'defaults': [['Mode', 'Components'], ['Translation', [0.0, 0.0, 0.0]], ['Rotation', [-1.570796, 0.0, 0.0]], ['Scale', [1.0, 0.8, 1.0]]]},
    {'name': 'Cube_Metacarpo1.001', 'type': 'GeometryNodeMeshCube', 'label': 'Cube_Metacarpo1', 'loc': [1350.0, -36.0], 'parent': 'Frame.011', 'defaults': [['Vertices X', 2], ['Vertices Y', 2], ['Vertices Z', 2]]},
    {'name': 'TF_Metacarpo1.001', 'type': 'GeometryNodeTransform', 'label': 'TF_Metacarpo1', 'loc': [1680.0, -36.0], 'parent': 'Frame.011', 'defaults': [['Mode', 'Components'], ['Rotation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'Cube_Falange21.001', 'type': 'GeometryNodeMeshCube', 'label': 'Cube_Metacarpo2', 'loc': [1350.0, -249.0], 'parent': 'Frame.011', 'defaults': [['Vertices X', 2], ['Vertices Y', 2], ['Vertices Z', 2]]},
    {'name': 'TF_Falange21.001', 'type': 'GeometryNodeTransform', 'label': 'TG_Metacarpo2', 'loc': [1680.0, -346.0], 'parent': 'Frame.011', 'defaults': [['Mode', 'Components'], ['Rotation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'Group Input.001', 'type': 'NodeGroupInput', 'label': '', 'loc': [30.0, -36.0], 'parent': 'Frame.007', 'hidden_out': ['Desvio Rad/Ulnar Punho', 'Flex/Ext Punho', 'Curva Palma Metacarpo 1', 'Curva Palma Metacarpo 2', 'Comp Metacarpo', 'Largura Metacarpo', 'Espessura Metacarpo', 'Comp Metacarpo Polegar', 'Largura Metacarpo Polegar', 'Espessura Metacarpo Polegar', 'Flex/Ext Polegar', 'Abdução Polegar', 'Flex/Ext Falange Prox Polegar', 'Flex/Ext Falange Dist Polegar', 'Comp Falange Prox Polegar', 'Espessura Falange Prox Polegar', 'Comp Falange Dist Polegar', 'Espessura Falange Dist Polegar', 'Abdução Dedo 1', 'Flex/Ext Falange Prox 1', 'Flex/Ext Falange Media 1', 'Flex/Ext Falange Dist 1', 'Comp Falange Prox 1', 'Espessura Falange Prox 1', 'Comp Falange Media 1', 'Espessura Falange Media 1', 'Comp Falange Dist 1', 'Espessura Falange Dist 1', 'Abdução Dedo 2', 'Flex/Ext Falange Prox 2', 'Flex/Ext Falange Media 2', 'Flex/Ext Falange Dist 2', 'Comp Falange Prox 2', 'Espessura Falange Prox 2', 'Comp Falange Media 2', 'Espessura Falange Media 2', 'Comp Falange Dist 2', 'Espessura Falange Dist 2', '']},
    {'name': 'Join_Geral.002', 'type': 'GeometryNodeJoinGeometry', 'label': 'Join_Geral', 'loc': [690.0, -36.0], 'parent': 'Frame.015'},
    {'name': 'Join_Geral.003', 'type': 'GeometryNodeJoinGeometry', 'label': 'Join_Geral', 'loc': [2010.0, -36.0], 'parent': 'Frame.011'},
    {'name': 'Join_Geral.004', 'type': 'GeometryNodeJoinGeometry', 'label': 'Join_Geral', 'loc': [30.0, -36.0], 'parent': 'Frame.015'},
    {'name': 'GI_Rotacoes.001', 'type': 'NodeGroupInput', 'label': 'GI_Rotacoes', 'loc': [30.0, -160.0], 'parent': 'Frame.014', 'hidden_out': ['Comp Antebraço', 'Raio Cotovelo', 'Raio Punho', 'Curva Palma Metacarpo 1', 'Curva Palma Metacarpo 2', 'Comp Metacarpo', 'Largura Metacarpo', 'Espessura Metacarpo', 'Comp Metacarpo Polegar', 'Largura Metacarpo Polegar', 'Espessura Metacarpo Polegar', 'Flex/Ext Polegar', 'Abdução Polegar', 'Flex/Ext Falange Prox Polegar', 'Flex/Ext Falange Dist Polegar', 'Comp Falange Prox Polegar', 'Espessura Falange Prox Polegar', 'Comp Falange Dist Polegar', 'Espessura Falange Dist Polegar', 'Abdução Dedo 1', 'Flex/Ext Falange Prox 1', 'Flex/Ext Falange Media 1', 'Flex/Ext Falange Dist 1', 'Comp Falange Prox 1', 'Espessura Falange Prox 1', 'Comp Falange Media 1', 'Espessura Falange Media 1', 'Comp Falange Dist 1', 'Espessura Falange Dist 1', 'Abdução Dedo 2', 'Flex/Ext Falange Prox 2', 'Flex/Ext Falange Media 2', 'Flex/Ext Falange Dist 2', 'Comp Falange Prox 2', 'Espessura Falange Prox 2', 'Comp Falange Media 2', 'Espessura Falange Media 2', 'Comp Falange Dist 2', 'Espessura Falange Dist 2', '']},
    {'name': 'Group Input', 'type': 'NodeGroupInput', 'label': 'GI_CompMetacarpo', 'loc': [30.0, -284.0], 'parent': 'Frame.014', 'hidden_out': ['Comp Antebraço', 'Raio Cotovelo', 'Raio Punho', 'Desvio Rad/Ulnar Punho', 'Flex/Ext Punho', 'Curva Palma Metacarpo 1', 'Curva Palma Metacarpo 2', 'Comp Metacarpo', 'Espessura Metacarpo', 'Comp Metacarpo Polegar', 'Largura Metacarpo Polegar', 'Espessura Metacarpo Polegar', 'Flex/Ext Polegar', 'Abdução Polegar', 'Flex/Ext Falange Prox Polegar', 'Flex/Ext Falange Dist Polegar', 'Comp Falange Prox Polegar', 'Espessura Falange Prox Polegar', 'Comp Falange Dist Polegar', 'Espessura Falange Dist Polegar', 'Abdução Dedo 1', 'Flex/Ext Falange Prox 1', 'Flex/Ext Falange Media 1', 'Flex/Ext Falange Dist 1', 'Comp Falange Prox 1', 'Espessura Falange Prox 1', 'Comp Falange Media 1', 'Espessura Falange Media 1', 'Comp Falange Dist 1', 'Espessura Falange Dist 1', 'Abdução Dedo 2', 'Flex/Ext Falange Prox 2', 'Flex/Ext Falange Media 2', 'Flex/Ext Falange Dist 2', 'Comp Falange Prox 2', 'Espessura Falange Prox 2', 'Comp Falange Media 2', 'Espessura Falange Media 2', 'Comp Falange Dist 2', 'Espessura Falange Dist 2', '']},
    {'name': 'Group Input.002', 'type': 'NodeGroupInput', 'label': 'GI_RaioPunhoMC', 'loc': [30.0, -36.0], 'parent': 'Frame.014', 'hidden_out': ['Comp Antebraço', 'Raio Cotovelo', 'Desvio Rad/Ulnar Punho', 'Flex/Ext Punho', 'Curva Palma Metacarpo 1', 'Curva Palma Metacarpo 2', 'Largura Metacarpo', 'Espessura Metacarpo', 'Comp Metacarpo Polegar', 'Largura Metacarpo Polegar', 'Espessura Metacarpo Polegar', 'Flex/Ext Polegar', 'Abdução Polegar', 'Flex/Ext Falange Prox Polegar', 'Flex/Ext Falange Dist Polegar', 'Comp Falange Prox Polegar', 'Espessura Falange Prox Polegar', 'Comp Falange Dist Polegar', 'Espessura Falange Dist Polegar', 'Abdução Dedo 1', 'Flex/Ext Falange Prox 1', 'Flex/Ext Falange Media 1', 'Flex/Ext Falange Dist 1', 'Comp Falange Prox 1', 'Espessura Falange Prox 1', 'Comp Falange Media 1', 'Espessura Falange Media 1', 'Comp Falange Dist 1', 'Espessura Falange Dist 1', 'Abdução Dedo 2', 'Flex/Ext Falange Prox 2', 'Flex/Ext Falange Media 2', 'Flex/Ext Falange Dist 2', 'Comp Falange Prox 2', 'Espessura Falange Prox 2', 'Comp Falange Media 2', 'Espessura Falange Media 2', 'Comp Falange Dist 2', 'Espessura Falange Dist 2', '']},
    {'name': 'Math', 'type': 'ShaderNodeMath', 'label': 'HalfComp_MC1', 'loc': [30.0, -36.0], 'parent': 'Frame.016', 'operation': 'DIVIDE', 'defaults': [['Value_001', 2.0], ['Value_002', 0.5]]},
    {'name': 'Math.001', 'type': 'ShaderNodeMath', 'label': 'AnchorY_MC1', 'loc': [360.0, -36.0], 'parent': 'Frame.016', 'operation': 'ADD', 'defaults': [['Value_002', 0.5]]},
    {'name': 'Math.002', 'type': 'ShaderNodeMath', 'label': 'NegAnchor_MC1', 'loc': [690.0, -36.0], 'parent': 'Frame.016', 'operation': 'MULTIPLY', 'defaults': [['Value_001', -1.0], ['Value_002', 0.5]]},
    {'name': 'Combine XYZ', 'type': 'ShaderNodeCombineXYZ', 'label': 'TFVec_MC1', 'loc': [30.0, -36.0], 'parent': 'Frame.011', 'defaults': [['Z', 0.0]]},
    {'name': 'Math.004', 'type': 'ShaderNodeMath', 'label': 'AnchorY_MC2', 'loc': [360.0, -234.0], 'parent': 'Frame.016', 'operation': 'ADD', 'defaults': [['Value_002', 0.5]]},
    {'name': 'Math.005', 'type': 'ShaderNodeMath', 'label': 'NegAnchor_MC2', 'loc': [690.0, -234.0], 'parent': 'Frame.016', 'operation': 'MULTIPLY', 'defaults': [['Value_001', -1.0], ['Value_002', 0.5]]},
    {'name': 'Combine XYZ.001', 'type': 'ShaderNodeCombineXYZ', 'label': 'TFVec_MC2', 'loc': [30.0, -205.0], 'parent': 'Frame.011', 'defaults': [['Z', 0.0]]},
    {'name': 'Math.006', 'type': 'ShaderNodeMath', 'label': 'PontaMC_Base', 'loc': [360.0, -36.0], 'parent': 'Frame_FK_Dedos', 'operation': 'ADD', 'defaults': [['Value_002', 0.5]]},
    {'name': 'Math.029', 'type': 'ShaderNodeMath', 'label': 'LargPalma_Div2', 'loc': [30.0, -234.0], 'parent': 'Frame.016', 'operation': 'DIVIDE', 'defaults': [['Value_001', 2.0], ['Value_002', 0.5]]},
    {'name': 'Math.030', 'type': 'ShaderNodeMath', 'label': 'LargPalma_NegX', 'loc': [360.0, -432.0], 'parent': 'Frame.016', 'operation': 'MULTIPLY', 'defaults': [['Value_001', -1.0], ['Value_002', 0.5]]},
    {'name': 'Math.031', 'type': 'ShaderNodeMath', 'label': 'Fator_Cube_Metacarpo1.001', 'loc': [360.0, -36.0], 'parent': 'Frame.011', 'operation': 'DIVIDE', 'defaults': [['Value_001', 32.409992], ['Value_002', 0.5]]},
    {'name': 'Math.032', 'type': 'ShaderNodeMath', 'label': 'XNovo_Cube_Metacarpo1.001', 'loc': [690.0, -36.0], 'parent': 'Frame.011', 'operation': 'MULTIPLY', 'defaults': [['Value_001', 33.800003], ['Value_002', 0.5]]},
    {'name': 'Combine XYZ.008', 'type': 'ShaderNodeCombineXYZ', 'label': 'SzVec_Cube_Metacarpo1.001', 'loc': [1020.0, -36.0], 'parent': 'Frame.011'},
    {'name': 'Math.034', 'type': 'ShaderNodeMath', 'label': 'XNovo_Cube_Falange21.001', 'loc': [690.0, -234.0], 'parent': 'Frame.011', 'operation': 'MULTIPLY', 'defaults': [['Value_001', 34.300003], ['Value_002', 0.5]]},
    {'name': 'Combine XYZ.009', 'type': 'ShaderNodeCombineXYZ', 'label': 'SzVec_Cube_Falange21.001', 'loc': [1020.0, -205.0], 'parent': 'Frame.011'},
    {'name': 'Math.036', 'type': 'ShaderNodeMath', 'label': 'XNovo_Cube_Metacarpo2', 'loc': [30.0, -36.0], 'parent': 'Frame.012', 'operation': 'MULTIPLY', 'defaults': [['Value_001', 63.699997], ['Value_002', 0.5]]},
    {'name': 'Combine XYZ.010', 'type': 'ShaderNodeCombineXYZ', 'label': 'SzVec_Cube_Metacarpo2', 'loc': [360.0, -36.0], 'parent': 'Frame.012'},
    {'name': 'Math.038', 'type': 'ShaderNodeMath', 'label': 'XNovo_Cube_Falange11', 'loc': [30.0, -234.0], 'parent': 'Frame.012', 'operation': 'MULTIPLY', 'defaults': [['Value_001', 68.800003], ['Value_002', 0.5]]},
    {'name': 'Combine XYZ.011', 'type': 'ShaderNodeCombineXYZ', 'label': 'SzVec_Cube_Falange11', 'loc': [360.0, -205.0], 'parent': 'Frame.012'},
    {'name': 'Math.040', 'type': 'ShaderNodeMath', 'label': 'XNovo_Cube_Falange12', 'loc': [30.0, -432.0], 'parent': 'Frame.012', 'operation': 'MULTIPLY', 'defaults': [['Value_001', 77.899994], ['Value_002', 0.5]]},
    {'name': 'Combine XYZ.012', 'type': 'ShaderNodeCombineXYZ', 'label': 'SzVec_Cube_Falange12', 'loc': [360.0, -374.0], 'parent': 'Frame.012'},
    {'name': 'Math.042', 'type': 'ShaderNodeMath', 'label': 'XNovo_Cube_Falange22', 'loc': [30.0, -36.0], 'parent': 'Frame.013', 'operation': 'MULTIPLY', 'defaults': [['Value_001', 57.699997], ['Value_002', 0.5]]},
    {'name': 'Combine XYZ.013', 'type': 'ShaderNodeCombineXYZ', 'label': 'SzVec_Cube_Falange22', 'loc': [360.0, -36.0], 'parent': 'Frame.013'},
    {'name': 'Math.044', 'type': 'ShaderNodeMath', 'label': 'XNovo_Cube_Falange23', 'loc': [30.0, -234.0], 'parent': 'Frame.013', 'operation': 'MULTIPLY', 'defaults': [['Value_001', 61.199997], ['Value_002', 0.5]]},
    {'name': 'Combine XYZ.014', 'type': 'ShaderNodeCombineXYZ', 'label': 'SzVec_Cube_Falange23', 'loc': [360.0, -205.0], 'parent': 'Frame.013'},
    {'name': 'Math.046', 'type': 'ShaderNodeMath', 'label': 'XNovo_Cube_Falange23.001', 'loc': [30.0, -432.0], 'parent': 'Frame.013', 'operation': 'MULTIPLY', 'defaults': [['Value_001', 70.400002], ['Value_002', 0.5]]},
    {'name': 'Combine XYZ.015', 'type': 'ShaderNodeCombineXYZ', 'label': 'SzVec_Cube_Falange23.001', 'loc': [360.0, -374.0], 'parent': 'Frame.013'},
    {'name': 'SzVec_Polegar1', 'type': 'ShaderNodeCombineXYZ', 'label': 'SzVec_Metacarpo_Polegar', 'loc': [360.0, -36.0], 'parent': 'Frame.009'},
    {'name': 'SzVec_Polegar2', 'type': 'ShaderNodeCombineXYZ', 'label': 'SzVec_FalangProx_Polegar', 'loc': [360.0, -205.0], 'parent': 'Frame.009', 'defaults': [['X', 20.5]]},
    {'name': 'SzVec_Polegar3', 'type': 'ShaderNodeCombineXYZ', 'label': 'SzVec_FalangDist_Polegar', 'loc': [360.0, -374.0], 'parent': 'Frame.009', 'defaults': [['X', 20.0]]},
    {'name': 'Math_FalangProxPolegarRad', 'type': 'ShaderNodeMath', 'label': 'FalangProxPolegar_Rad', 'loc': [360.0, -329.0], 'parent': 'Frame_FK_Polegar', 'operation': 'RADIANS', 'defaults': [['Value_001', 0.5], ['Value_002', 0.5]]},
    {'name': 'CXYZ_FalangProxPolegarRot', 'type': 'ShaderNodeCombineXYZ', 'label': 'FalangProxPolegar_Rot', 'loc': [1020.0, -36.0], 'parent': 'Frame_FK_Polegar', 'defaults': [['X', 0.0], ['Y', 0.0]]},
    {'name': 'Math_FalangDistPolegarRad', 'type': 'ShaderNodeMath', 'label': 'FalangDistPolegar_Rad', 'loc': [360.0, -505.0], 'parent': 'Frame_FK_Polegar', 'operation': 'RADIANS', 'defaults': [['Value_001', 0.5], ['Value_002', 0.5]]},
    {'name': 'CXYZ_FalangDistPolegarRot', 'type': 'ShaderNodeCombineXYZ', 'label': 'FalangDistPolegar_Rot', 'loc': [1020.0, -205.0], 'parent': 'Frame_FK_Polegar', 'defaults': [['X', 0.0], ['Y', 0.0]]},
    {'name': 'FK_TH_etrBase', 'type': 'FunctionNodeEulerToRotation', 'loc': [30.0, -226.0], 'parent': 'Frame_FK_Polegar', 'defaults': [['Euler', [0.0, 0.0, 0.473]]]},
    {'name': 'FK_TH_ctBase', 'type': 'FunctionNodeCombineTransform', 'loc': [360.0, -36.0], 'parent': 'Frame_FK_Polegar', 'defaults': [['Translation', [27.1, -85.25, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'FK_TH_negHalfMC', 'type': 'ShaderNodeMath', 'loc': [360.0, -1077.0], 'parent': 'Frame_FK_Polegar', 'operation': 'MULTIPLY', 'defaults': [['Value_001', -0.5], ['Value_002', 0.5]]},
    {'name': 'FK_TH_dMCv', 'type': 'ShaderNodeCombineXYZ', 'loc': [690.0, -770.0], 'parent': 'Frame_FK_Polegar', 'defaults': [['X', 0.0], ['Z', 0.0]]},
    {'name': 'FK_TH_ctdMC', 'type': 'FunctionNodeCombineTransform', 'loc': [1020.0, -1253.0], 'parent': 'Frame_FK_Polegar', 'defaults': [['Rotation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'FK_TH_A0', 'type': 'FunctionNodeMatrixMultiply', 'loc': [1350.0, -286.0], 'parent': 'Frame_FK_Polegar'},
    {'name': 'FK_TH_etr0', 'type': 'FunctionNodeEulerToRotation', 'loc': [1350.0, -36.0], 'parent': 'Frame_FK_Polegar'},
    {'name': 'FK_TH_ctR0', 'type': 'FunctionNodeCombineTransform', 'loc': [1680.0, -329.0], 'parent': 'Frame_FK_Polegar', 'defaults': [['Translation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'FK_TH_M0', 'type': 'FunctionNodeMatrixMultiply', 'loc': [2010.0, -36.0], 'parent': 'Frame_FK_Polegar'},
    {'name': 'FK_TH_negHalf1', 'type': 'ShaderNodeMath', 'loc': [360.0, -681.0], 'parent': 'Frame_FK_Polegar', 'operation': 'MULTIPLY', 'defaults': [['Value_001', -0.5], ['Value_002', 0.5]]},
    {'name': 'FK_TH_offv1', 'type': 'ShaderNodeCombineXYZ', 'loc': [690.0, -432.0], 'parent': 'Frame_FK_Polegar', 'defaults': [['X', 0.0], ['Z', 0.0]]},
    {'name': 'FK_TH_ctOff1', 'type': 'FunctionNodeCombineTransform', 'loc': [1020.0, -667.0], 'parent': 'Frame_FK_Polegar', 'defaults': [['Rotation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'FK_TH_cube1', 'type': 'FunctionNodeMatrixMultiply', 'loc': [2340.0, -36.0], 'parent': 'Frame_FK_Polegar'},
    {'name': 'FK_TH_negLen1', 'type': 'ShaderNodeMath', 'loc': [360.0, -879.0], 'parent': 'Frame_FK_Polegar', 'operation': 'MULTIPLY', 'defaults': [['Value_001', -1.0], ['Value_002', 0.5]]},
    {'name': 'FK_TH_d1v', 'type': 'ShaderNodeCombineXYZ', 'loc': [690.0, -601.0], 'parent': 'Frame_FK_Polegar', 'defaults': [['X', 0.0], ['Z', 0.0]]},
    {'name': 'FK_TH_ctd1', 'type': 'FunctionNodeCombineTransform', 'loc': [1020.0, -374.0], 'parent': 'Frame_FK_Polegar', 'defaults': [['Rotation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'FK_TH_A1', 'type': 'FunctionNodeMatrixMultiply', 'loc': [2340.0, -183.0], 'parent': 'Frame_FK_Polegar'},
    {'name': 'FK_TH_etr1', 'type': 'FunctionNodeEulerToRotation', 'loc': [1350.0, -161.0], 'parent': 'Frame_FK_Polegar'},
    {'name': 'FK_TH_ctR1', 'type': 'FunctionNodeCombineTransform', 'loc': [1680.0, -36.0], 'parent': 'Frame_FK_Polegar', 'defaults': [['Translation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'FK_TH_M1', 'type': 'FunctionNodeMatrixMultiply', 'loc': [2670.0, -36.0], 'parent': 'Frame_FK_Polegar'},
    {'name': 'FK_TH_negHalf2', 'type': 'ShaderNodeMath', 'loc': [360.0, -1275.0], 'parent': 'Frame_FK_Polegar', 'operation': 'MULTIPLY', 'defaults': [['Value_001', -0.5], ['Value_002', 0.5]]},
    {'name': 'FK_TH_offv2', 'type': 'ShaderNodeCombineXYZ', 'loc': [690.0, -939.0], 'parent': 'Frame_FK_Polegar', 'defaults': [['X', 0.0], ['Z', 0.0]]},
    {'name': 'FK_TH_ctOff2', 'type': 'FunctionNodeCombineTransform', 'loc': [1020.0, -960.0], 'parent': 'Frame_FK_Polegar', 'defaults': [['Rotation', [0.0, 0.0, 0.0]], ['Scale', [1.0, 1.0, 1.0]]]},
    {'name': 'FK_TH_cube2', 'type': 'FunctionNodeMatrixMultiply', 'loc': [3000.0, -36.0], 'parent': 'Frame_FK_Polegar'},
    {'name': 'FK_TH_negFlexProx', 'type': 'ShaderNodeMath', 'loc': [690.0, -36.0], 'parent': 'Frame_FK_Polegar', 'operation': 'MULTIPLY', 'defaults': [['Value_001', -1.0], ['Value_002', 0.5]]},
    {'name': 'FK_TH_negFlexDist', 'type': 'ShaderNodeMath', 'loc': [690.0, -234.0], 'parent': 'Frame_FK_Polegar', 'operation': 'MULTIPLY', 'defaults': [['Value_001', -1.0], ['Value_002', 0.5]]},
    {'name': 'FK_Dedo1', 'type': 'GeometryNodeGroup', 'loc': [690.0, -36.0], 'parent': 'Frame_FK_Dedos', 'node_tree': 'VB_FK_Cadeia_Dedo', 'defaults': [['Direcao Abd', -1.0]]},
    {'name': 'FK_Dedo2', 'type': 'GeometryNodeGroup', 'loc': [690.0, -402.0], 'parent': 'Frame_FK_Dedos', 'node_tree': 'VB_FK_Cadeia_Dedo', 'defaults': [['Direcao Abd', 1.0]]},
    {'name': 'GI_FK_Dedos', 'type': 'NodeGroupInput', 'label': 'Entradas (local)', 'loc': [30.0, -36.0], 'parent': 'Frame_FK_Dedos', 'hidden_out': ['Comp Antebraço', 'Raio Cotovelo', 'Desvio Rad/Ulnar Punho', 'Flex/Ext Punho', 'Curva Palma Metacarpo 1', 'Curva Palma Metacarpo 2', 'Largura Metacarpo', 'Espessura Metacarpo', 'Comp Metacarpo Polegar', 'Largura Metacarpo Polegar', 'Espessura Metacarpo Polegar', 'Flex/Ext Polegar', 'Abdução Polegar', 'Flex/Ext Falange Prox Polegar', 'Flex/Ext Falange Dist Polegar', 'Comp Falange Prox Polegar', 'Espessura Falange Prox Polegar', 'Comp Falange Dist Polegar', 'Espessura Falange Dist Polegar', 'Espessura Falange Prox 1', 'Espessura Falange Media 1', 'Espessura Falange Dist 1', 'Espessura Falange Prox 2', 'Espessura Falange Media 2', 'Espessura Falange Dist 2', '']},
    {'name': 'GI_FK_Polegar', 'type': 'NodeGroupInput', 'label': 'Entradas (local)', 'loc': [30.0, -36.0], 'parent': 'Frame_FK_Polegar', 'hidden_out': ['Comp Antebraço', 'Raio Cotovelo', 'Raio Punho', 'Desvio Rad/Ulnar Punho', 'Flex/Ext Punho', 'Curva Palma Metacarpo 1', 'Curva Palma Metacarpo 2', 'Comp Metacarpo', 'Largura Metacarpo', 'Espessura Metacarpo', 'Largura Metacarpo Polegar', 'Espessura Metacarpo Polegar', 'Flex/Ext Polegar', 'Abdução Polegar', 'Espessura Falange Prox Polegar', 'Espessura Falange Dist Polegar', 'Abdução Dedo 1', 'Flex/Ext Falange Prox 1', 'Flex/Ext Falange Media 1', 'Flex/Ext Falange Dist 1', 'Comp Falange Prox 1', 'Espessura Falange Prox 1', 'Comp Falange Media 1', 'Espessura Falange Media 1', 'Comp Falange Dist 1', 'Espessura Falange Dist 1', 'Abdução Dedo 2', 'Flex/Ext Falange Prox 2', 'Flex/Ext Falange Media 2', 'Flex/Ext Falange Dist 2', 'Comp Falange Prox 2', 'Espessura Falange Prox 2', 'Comp Falange Media 2', 'Espessura Falange Media 2', 'Comp Falange Dist 2', 'Espessura Falange Dist 2', '']},
    {'name': 'GI_F009', 'type': 'NodeGroupInput', 'label': 'Entradas (local)', 'loc': [30.0, -36.0], 'parent': 'Frame.009', 'hidden_out': ['Comp Antebraço', 'Raio Cotovelo', 'Raio Punho', 'Desvio Rad/Ulnar Punho', 'Flex/Ext Punho', 'Curva Palma Metacarpo 1', 'Curva Palma Metacarpo 2', 'Comp Metacarpo', 'Largura Metacarpo', 'Espessura Metacarpo', 'Flex/Ext Polegar', 'Abdução Polegar', 'Flex/Ext Falange Prox Polegar', 'Flex/Ext Falange Dist Polegar', 'Abdução Dedo 1', 'Flex/Ext Falange Prox 1', 'Flex/Ext Falange Media 1', 'Flex/Ext Falange Dist 1', 'Comp Falange Prox 1', 'Espessura Falange Prox 1', 'Comp Falange Media 1', 'Espessura Falange Media 1', 'Comp Falange Dist 1', 'Espessura Falange Dist 1', 'Abdução Dedo 2', 'Flex/Ext Falange Prox 2', 'Flex/Ext Falange Media 2', 'Flex/Ext Falange Dist 2', 'Comp Falange Prox 2', 'Espessura Falange Prox 2', 'Comp Falange Media 2', 'Espessura Falange Media 2', 'Comp Falange Dist 2', 'Espessura Falange Dist 2', '']},
    {'name': 'GI_F010', 'type': 'NodeGroupInput', 'label': 'Entradas (local)', 'loc': [30.0, -36.0], 'parent': 'Frame.010', 'hidden_out': ['Comp Antebraço', 'Raio Cotovelo', 'Raio Punho', 'Desvio Rad/Ulnar Punho', 'Flex/Ext Punho', 'Curva Palma Metacarpo 1', 'Curva Palma Metacarpo 2', 'Comp Metacarpo', 'Largura Metacarpo', 'Espessura Metacarpo', 'Comp Metacarpo Polegar', 'Largura Metacarpo Polegar', 'Espessura Metacarpo Polegar', 'Flex/Ext Falange Prox Polegar', 'Flex/Ext Falange Dist Polegar', 'Comp Falange Prox Polegar', 'Espessura Falange Prox Polegar', 'Comp Falange Dist Polegar', 'Espessura Falange Dist Polegar', 'Abdução Dedo 1', 'Flex/Ext Falange Prox 1', 'Flex/Ext Falange Media 1', 'Flex/Ext Falange Dist 1', 'Comp Falange Prox 1', 'Espessura Falange Prox 1', 'Comp Falange Media 1', 'Espessura Falange Media 1', 'Comp Falange Dist 1', 'Espessura Falange Dist 1', 'Abdução Dedo 2', 'Flex/Ext Falange Prox 2', 'Flex/Ext Falange Media 2', 'Flex/Ext Falange Dist 2', 'Comp Falange Prox 2', 'Espessura Falange Prox 2', 'Comp Falange Media 2', 'Espessura Falange Media 2', 'Comp Falange Dist 2', 'Espessura Falange Dist 2', '']},
    {'name': 'GI_F011', 'type': 'NodeGroupInput', 'label': 'Entradas (local)', 'loc': [30.0, -374.0], 'parent': 'Frame.011', 'hidden_out': ['Comp Antebraço', 'Raio Cotovelo', 'Raio Punho', 'Desvio Rad/Ulnar Punho', 'Flex/Ext Punho', 'Curva Palma Metacarpo 1', 'Curva Palma Metacarpo 2', 'Comp Metacarpo Polegar', 'Largura Metacarpo Polegar', 'Espessura Metacarpo Polegar', 'Flex/Ext Polegar', 'Abdução Polegar', 'Flex/Ext Falange Prox Polegar', 'Flex/Ext Falange Dist Polegar', 'Comp Falange Prox Polegar', 'Espessura Falange Prox Polegar', 'Comp Falange Dist Polegar', 'Espessura Falange Dist Polegar', 'Abdução Dedo 1', 'Flex/Ext Falange Prox 1', 'Flex/Ext Falange Media 1', 'Flex/Ext Falange Dist 1', 'Comp Falange Prox 1', 'Espessura Falange Prox 1', 'Comp Falange Media 1', 'Espessura Falange Media 1', 'Comp Falange Dist 1', 'Espessura Falange Dist 1', 'Abdução Dedo 2', 'Flex/Ext Falange Prox 2', 'Flex/Ext Falange Media 2', 'Flex/Ext Falange Dist 2', 'Comp Falange Prox 2', 'Espessura Falange Prox 2', 'Comp Falange Media 2', 'Espessura Falange Media 2', 'Comp Falange Dist 2', 'Espessura Falange Dist 2', '']},
    {'name': 'GI_F012', 'type': 'NodeGroupInput', 'label': 'Entradas (local)', 'loc': [30.0, -630.0], 'parent': 'Frame.012', 'hidden_out': ['Comp Antebraço', 'Raio Cotovelo', 'Raio Punho', 'Desvio Rad/Ulnar Punho', 'Flex/Ext Punho', 'Curva Palma Metacarpo 1', 'Curva Palma Metacarpo 2', 'Comp Metacarpo', 'Largura Metacarpo', 'Espessura Metacarpo', 'Comp Metacarpo Polegar', 'Largura Metacarpo Polegar', 'Espessura Metacarpo Polegar', 'Flex/Ext Polegar', 'Abdução Polegar', 'Flex/Ext Falange Prox Polegar', 'Flex/Ext Falange Dist Polegar', 'Comp Falange Prox Polegar', 'Espessura Falange Prox Polegar', 'Comp Falange Dist Polegar', 'Espessura Falange Dist Polegar', 'Abdução Dedo 1', 'Flex/Ext Falange Prox 1', 'Flex/Ext Falange Media 1', 'Flex/Ext Falange Dist 1', 'Abdução Dedo 2', 'Flex/Ext Falange Prox 2', 'Flex/Ext Falange Media 2', 'Flex/Ext Falange Dist 2', 'Comp Falange Prox 2', 'Espessura Falange Prox 2', 'Comp Falange Media 2', 'Espessura Falange Media 2', 'Comp Falange Dist 2', 'Espessura Falange Dist 2', '']},
    {'name': 'GI_F013', 'type': 'NodeGroupInput', 'label': 'Entradas (local)', 'loc': [30.0, -630.0], 'parent': 'Frame.013', 'hidden_out': ['Comp Antebraço', 'Raio Cotovelo', 'Raio Punho', 'Desvio Rad/Ulnar Punho', 'Flex/Ext Punho', 'Curva Palma Metacarpo 1', 'Curva Palma Metacarpo 2', 'Comp Metacarpo', 'Largura Metacarpo', 'Espessura Metacarpo', 'Comp Metacarpo Polegar', 'Largura Metacarpo Polegar', 'Espessura Metacarpo Polegar', 'Flex/Ext Polegar', 'Abdução Polegar', 'Flex/Ext Falange Prox Polegar', 'Flex/Ext Falange Dist Polegar', 'Comp Falange Prox Polegar', 'Espessura Falange Prox Polegar', 'Comp Falange Dist Polegar', 'Espessura Falange Dist Polegar', 'Abdução Dedo 1', 'Flex/Ext Falange Prox 1', 'Flex/Ext Falange Media 1', 'Flex/Ext Falange Dist 1', 'Comp Falange Prox 1', 'Espessura Falange Prox 1', 'Comp Falange Media 1', 'Espessura Falange Media 1', 'Comp Falange Dist 1', 'Espessura Falange Dist 1', 'Abdução Dedo 2', 'Flex/Ext Falange Prox 2', 'Flex/Ext Falange Media 2', 'Flex/Ext Falange Dist 2', '']},
]

# ===================== DADOS: LINKS (ordem = ordem de join) ================
GROUP_LINKS = [
    ['Entradas', 'Ponta MC', 'negPonta', 'Value'],
    ['negPonta', 'Value', 'j0v', 'Y'],
    ['j0v', 'Vector', 'ctJ0', 'Translation'],
    ['Entradas', 'Abducao', 'abdRad', 'Value'],
    ['abdRad', 'Value', 'abdSigned', 'Value'],
    ['Entradas', 'Direcao Abd', 'abdSigned', 'Value_001'],
    ['abdSigned', 'Value', 'abdv', 'Z'],
    ['abdv', 'Vector', 'etrA', 'Euler'],
    ['etrA', 'Rotation', 'ctA', 'Rotation'],
    ['ctJ0', 'Transform', 'JA', 'Matrix'],
    ['ctA', 'Transform', 'JA', 'Matrix_001'],
    ['Entradas', 'Flex Prox', 'rad0', 'Value'],
    ['rad0', 'Value', 'rotv0', 'X'],
    ['rotv0', 'Vector', 'etr0', 'Euler'],
    ['etr0', 'Rotation', 'ctR0', 'Rotation'],
    ['Entradas', 'Flex Media', 'rad1', 'Value'],
    ['rad1', 'Value', 'rotv1', 'X'],
    ['rotv1', 'Vector', 'etr1', 'Euler'],
    ['etr1', 'Rotation', 'ctR1', 'Rotation'],
    ['Entradas', 'Flex Dist', 'rad2', 'Value'],
    ['rad2', 'Value', 'rotv2', 'X'],
    ['rotv2', 'Vector', 'etr2', 'Euler'],
    ['etr2', 'Rotation', 'ctR2', 'Rotation'],
    ['JA', 'Matrix', 'M0', 'Matrix'],
    ['ctR0', 'Transform', 'M0', 'Matrix_001'],
    ['Entradas', 'Comp Prox', 'negHalf0', 'Value'],
    ['negHalf0', 'Value', 'offv0', 'Y'],
    ['offv0', 'Vector', 'ctOff0', 'Translation'],
    ['M0', 'Matrix', 'cube0', 'Matrix'],
    ['ctOff0', 'Transform', 'cube0', 'Matrix_001'],
    ['Entradas', 'Comp Prox', 'negLen1', 'Value'],
    ['negLen1', 'Value', 'd1v', 'Y'],
    ['d1v', 'Vector', 'ctd1', 'Translation'],
    ['M0', 'Matrix', 'A1', 'Matrix'],
    ['ctd1', 'Transform', 'A1', 'Matrix_001'],
    ['A1', 'Matrix', 'M1', 'Matrix'],
    ['ctR1', 'Transform', 'M1', 'Matrix_001'],
    ['Entradas', 'Comp Media', 'negHalf1', 'Value'],
    ['negHalf1', 'Value', 'offv1', 'Y'],
    ['offv1', 'Vector', 'ctOff1', 'Translation'],
    ['M1', 'Matrix', 'cube1', 'Matrix'],
    ['ctOff1', 'Transform', 'cube1', 'Matrix_001'],
    ['Entradas', 'Comp Media', 'negLen2', 'Value'],
    ['negLen2', 'Value', 'd2v', 'Y'],
    ['d2v', 'Vector', 'ctd2', 'Translation'],
    ['M1', 'Matrix', 'A2', 'Matrix'],
    ['ctd2', 'Transform', 'A2', 'Matrix_001'],
    ['A2', 'Matrix', 'M2', 'Matrix'],
    ['ctR2', 'Transform', 'M2', 'Matrix_001'],
    ['Entradas', 'Comp Dist', 'negHalf2', 'Value'],
    ['negHalf2', 'Value', 'offv2', 'Y'],
    ['offv2', 'Vector', 'ctOff2', 'Translation'],
    ['M2', 'Matrix', 'cube2', 'Matrix'],
    ['ctOff2', 'Transform', 'cube2', 'Matrix_001'],
    ['cube0', 'Matrix', 'Saidas', 'Matriz Prox'],
    ['cube1', 'Matrix', 'Saidas', 'Matriz Media'],
    ['cube2', 'Matrix', 'Saidas', 'Matriz Dist'],
]

LINKS = [
    ['Cube_Polegar1', 'Mesh', 'TF_Polegar1', 'Geometry'],
    ['Cube_Polegar2', 'Mesh', 'TF_Polegar2', 'Geometry'],
    ['Cube_Polegar3', 'Mesh', 'TF_Polegar3', 'Geometry'],
    ['Cube_Metacarpo2', 'Mesh', 'TF_Metacarpo2', 'Geometry'],
    ['Cube_Falange11', 'Mesh', 'TF_Falange11', 'Geometry'],
    ['Cube_Falange12', 'Mesh', 'TF_Falange12', 'Geometry'],
    ['Cube_Falange22', 'Mesh', 'TF_Falange22', 'Geometry'],
    ['Cube_Falange23', 'Mesh', 'TF_Falange23', 'Geometry'],
    ['TF_Polegar1', 'Geometry', 'Join_Polegar_Raw', 'Geometry'],
    ['Join_Polegar_Raw', 'Geometry', 'TF_AbducaoPolegar', 'Geometry'],
    ['Join_Polegar', 'Geometry', 'Join_MaoBruta', 'Geometry'],
    ['Join_MaoBruta', 'Geometry', 'TF_DesvioUlnar', 'Geometry'],
    ['Math_UlnarRad', 'Value', 'CXYZ_UlnarRot', 'Z'],
    ['CXYZ_UlnarRot', 'Vector', 'TF_DesvioUlnar', 'Rotation'],
    ['Math_AbdRad', 'Value', 'CXYZ_AbdRot', 'Z'],
    ['CXYZ_AbdRot', 'Vector', 'TF_AbducaoPolegar', 'Rotation'],
    ['Cube_Falange23.001', 'Mesh', 'TF_Falange23.001', 'Geometry'],
    ['TF_Falange23.001', 'Geometry', 'Join_Falanges', 'Geometry'],
    ['CXYZ_ExtFlexRot', 'Vector', 'TF_ExtensaoFlexao', 'Rotation'],
    ['TF_DesvioUlnar', 'Geometry', 'TF_ExtensaoFlexao', 'Geometry'],
    ['Math_ExtFlexRad', 'Value', 'CXYZ_ExtFlexRot', 'X'],
    ['Math_ExtFlexPolegarRad', 'Value', 'CXYZ_ExtFlexPolegarRot', 'X'],
    ['CXYZ_ExtFlexPolegarRot', 'Vector', 'TF_ExtFlexPolegar', 'Rotation'],
    ['TF_AbducaoPolegar', 'Geometry', 'TF_ExtFlexPolegar', 'Geometry'],
    ['TF_ExtFlexPolegar', 'Geometry', 'Join_Polegar', 'Geometry'],
    ['Cone_Antebraco.001', 'Mesh', 'TF_Antebraco.001', 'Geometry'],
    ['UVSphere_Punho.001', 'Mesh', 'TF_Punho.001', 'Geometry'],
    ['Cube_Metacarpo1.001', 'Mesh', 'TF_Metacarpo1.001', 'Geometry'],
    ['Cube_Falange21.001', 'Mesh', 'TF_Falange21.001', 'Geometry'],
    ['Join_Geral', 'Geometry', 'Join_Geral.002', 'Geometry'],
    ['Join_Geral.002', 'Geometry', 'Group Output', 'Geometry'],
    ['TF_Falange21.001', 'Geometry', 'Join_Geral.003', 'Geometry'],
    ['TF_Punho.001', 'Geometry', 'Join_Geral.004', 'Geometry'],
    ['Join_Geral.004', 'Geometry', 'Join_Geral', 'Geometry'],
    ['TF_Falange12', 'Geometry', 'Join_Metacarpos', 'Geometry'],
    ['Group Input.001', 'Raio Cotovelo', 'Cone_Antebraco.001', 'Radius Top'],
    ['Group Input.001', 'Raio Punho', 'Cone_Antebraco.001', 'Radius Bottom'],
    ['Group Input.001', 'Raio Punho', 'UVSphere_Punho.001', 'Radius'],
    ['GI_Rotacoes.001', 'Desvio Rad/Ulnar Punho', 'Math_UlnarRad', 'Value'],
    ['GI_Rotacoes.001', 'Flex/Ext Punho', 'Math_ExtFlexRad', 'Value'],
    ['Group Input.001', 'Comp Antebraço', 'Cone_Antebraco.001', 'Depth'],
    ['Group Input.002', 'Comp Metacarpo', 'Math', 'Value'],
    ['Group Input.002', 'Raio Punho', 'Math.001', 'Value'],
    ['Math', 'Value', 'Math.001', 'Value_001'],
    ['Math.001', 'Value', 'Math.002', 'Value'],
    ['Math.002', 'Value', 'Combine XYZ', 'Y'],
    ['Combine XYZ', 'Vector', 'TF_Metacarpo1.001', 'Translation'],
    ['Group Input.002', 'Raio Punho', 'Math.004', 'Value'],
    ['Math.004', 'Value', 'Math.005', 'Value'],
    ['Math.005', 'Value', 'Combine XYZ.001', 'Y'],
    ['Combine XYZ.001', 'Vector', 'TF_Falange21.001', 'Translation'],
    ['Group Input', 'Largura Metacarpo', 'Math.029', 'Value'],
    ['Math.029', 'Value', 'Math.030', 'Value'],
    ['Math.030', 'Value', 'Combine XYZ', 'X'],
    ['Math.029', 'Value', 'Combine XYZ.001', 'X'],
    ['Math.031', 'Value', 'Math.032', 'Value'],
    ['Math.032', 'Value', 'Combine XYZ.008', 'X'],
    ['Combine XYZ.008', 'Vector', 'Cube_Metacarpo1.001', 'Size'],
    ['Math.034', 'Value', 'Combine XYZ.009', 'X'],
    ['Combine XYZ.009', 'Vector', 'Cube_Falange21.001', 'Size'],
    ['Math.036', 'Value', 'Combine XYZ.010', 'X'],
    ['Combine XYZ.010', 'Vector', 'Cube_Metacarpo2', 'Size'],
    ['Math.038', 'Value', 'Combine XYZ.011', 'X'],
    ['Combine XYZ.011', 'Vector', 'Cube_Falange11', 'Size'],
    ['Math.040', 'Value', 'Combine XYZ.012', 'X'],
    ['Combine XYZ.012', 'Vector', 'Cube_Falange12', 'Size'],
    ['Math.042', 'Value', 'Combine XYZ.013', 'X'],
    ['Combine XYZ.013', 'Vector', 'Cube_Falange22', 'Size'],
    ['Math.044', 'Value', 'Combine XYZ.014', 'X'],
    ['Combine XYZ.014', 'Vector', 'Cube_Falange23', 'Size'],
    ['Math.046', 'Value', 'Combine XYZ.015', 'X'],
    ['Combine XYZ.015', 'Vector', 'Cube_Falange23.001', 'Size'],
    ['SzVec_Polegar1', 'Vector', 'Cube_Polegar1', 'Size'],
    ['SzVec_Polegar2', 'Vector', 'Cube_Polegar2', 'Size'],
    ['SzVec_Polegar3', 'Vector', 'Cube_Polegar3', 'Size'],
    ['FK_TH_etrBase', 'Rotation', 'FK_TH_ctBase', 'Rotation'],
    ['FK_TH_negHalfMC', 'Value', 'FK_TH_dMCv', 'Y'],
    ['FK_TH_dMCv', 'Vector', 'FK_TH_ctdMC', 'Translation'],
    ['FK_TH_ctBase', 'Transform', 'FK_TH_A0', 'Matrix'],
    ['FK_TH_ctdMC', 'Transform', 'FK_TH_A0', 'Matrix_001'],
    ['CXYZ_FalangProxPolegarRot', 'Vector', 'FK_TH_etr0', 'Euler'],
    ['FK_TH_etr0', 'Rotation', 'FK_TH_ctR0', 'Rotation'],
    ['FK_TH_A0', 'Matrix', 'FK_TH_M0', 'Matrix'],
    ['FK_TH_ctR0', 'Transform', 'FK_TH_M0', 'Matrix_001'],
    ['FK_TH_negHalf1', 'Value', 'FK_TH_offv1', 'Y'],
    ['FK_TH_offv1', 'Vector', 'FK_TH_ctOff1', 'Translation'],
    ['FK_TH_M0', 'Matrix', 'FK_TH_cube1', 'Matrix'],
    ['FK_TH_ctOff1', 'Transform', 'FK_TH_cube1', 'Matrix_001'],
    ['FK_TH_negLen1', 'Value', 'FK_TH_d1v', 'Y'],
    ['FK_TH_d1v', 'Vector', 'FK_TH_ctd1', 'Translation'],
    ['FK_TH_M0', 'Matrix', 'FK_TH_A1', 'Matrix'],
    ['FK_TH_ctd1', 'Transform', 'FK_TH_A1', 'Matrix_001'],
    ['CXYZ_FalangDistPolegarRot', 'Vector', 'FK_TH_etr1', 'Euler'],
    ['FK_TH_etr1', 'Rotation', 'FK_TH_ctR1', 'Rotation'],
    ['FK_TH_A1', 'Matrix', 'FK_TH_M1', 'Matrix'],
    ['FK_TH_ctR1', 'Transform', 'FK_TH_M1', 'Matrix_001'],
    ['FK_TH_negHalf2', 'Value', 'FK_TH_offv2', 'Y'],
    ['FK_TH_offv2', 'Vector', 'FK_TH_ctOff2', 'Translation'],
    ['FK_TH_M1', 'Matrix', 'FK_TH_cube2', 'Matrix'],
    ['FK_TH_ctOff2', 'Transform', 'FK_TH_cube2', 'Matrix_001'],
    ['FK_TH_ctBase', 'Transform', 'TF_Polegar1', 'Transform'],
    ['FK_TH_cube1', 'Matrix', 'TF_Polegar2', 'Transform'],
    ['FK_TH_cube2', 'Matrix', 'TF_Polegar3', 'Transform'],
    ['Math_FalangProxPolegarRad', 'Value', 'FK_TH_negFlexProx', 'Value'],
    ['FK_TH_negFlexProx', 'Value', 'CXYZ_FalangProxPolegarRot', 'Z'],
    ['Math_FalangDistPolegarRad', 'Value', 'FK_TH_negFlexDist', 'Value'],
    ['FK_TH_negFlexDist', 'Value', 'CXYZ_FalangDistPolegarRot', 'Z'],
    ['Math', 'Value', 'Math.004', 'Value_001'],
    ['Math.031', 'Value', 'Math.034', 'Value'],
    ['Math.031', 'Value', 'Math.036', 'Value'],
    ['Math.031', 'Value', 'Math.038', 'Value'],
    ['Math.031', 'Value', 'Math.040', 'Value'],
    ['Math.031', 'Value', 'Math.042', 'Value'],
    ['Math.031', 'Value', 'Math.044', 'Value'],
    ['Math.031', 'Value', 'Math.046', 'Value'],
    ['Math.006', 'Value', 'FK_Dedo1', 'Ponta MC'],
    ['FK_Dedo1', 'Matriz Prox', 'TF_Metacarpo2', 'Transform'],
    ['FK_Dedo1', 'Matriz Media', 'TF_Falange11', 'Transform'],
    ['FK_Dedo1', 'Matriz Dist', 'TF_Falange12', 'Transform'],
    ['Math.006', 'Value', 'FK_Dedo2', 'Ponta MC'],
    ['FK_Dedo2', 'Matriz Prox', 'TF_Falange22', 'Transform'],
    ['FK_Dedo2', 'Matriz Media', 'TF_Falange23', 'Transform'],
    ['FK_Dedo2', 'Matriz Dist', 'TF_Falange23.001', 'Transform'],
    ['GI_FK_Dedos', 'Raio Punho', 'Math.006', 'Value'],
    ['GI_FK_Dedos', 'Comp Metacarpo', 'Math.006', 'Value_001'],
    ['GI_FK_Dedos', 'Comp Falange Prox 1', 'FK_Dedo1', 'Comp Prox'],
    ['GI_FK_Dedos', 'Comp Falange Media 1', 'FK_Dedo1', 'Comp Media'],
    ['GI_FK_Dedos', 'Comp Falange Dist 1', 'FK_Dedo1', 'Comp Dist'],
    ['GI_FK_Dedos', 'Flex/Ext Falange Prox 1', 'FK_Dedo1', 'Flex Prox'],
    ['GI_FK_Dedos', 'Flex/Ext Falange Media 1', 'FK_Dedo1', 'Flex Media'],
    ['GI_FK_Dedos', 'Flex/Ext Falange Dist 1', 'FK_Dedo1', 'Flex Dist'],
    ['GI_FK_Dedos', 'Abdução Dedo 1', 'FK_Dedo1', 'Abducao'],
    ['GI_FK_Dedos', 'Comp Falange Prox 2', 'FK_Dedo2', 'Comp Prox'],
    ['GI_FK_Dedos', 'Comp Falange Media 2', 'FK_Dedo2', 'Comp Media'],
    ['GI_FK_Dedos', 'Comp Falange Dist 2', 'FK_Dedo2', 'Comp Dist'],
    ['GI_FK_Dedos', 'Flex/Ext Falange Prox 2', 'FK_Dedo2', 'Flex Prox'],
    ['GI_FK_Dedos', 'Flex/Ext Falange Media 2', 'FK_Dedo2', 'Flex Media'],
    ['GI_FK_Dedos', 'Flex/Ext Falange Dist 2', 'FK_Dedo2', 'Flex Dist'],
    ['GI_FK_Dedos', 'Abdução Dedo 2', 'FK_Dedo2', 'Abducao'],
    ['GI_FK_Polegar', 'Flex/Ext Falange Prox Polegar', 'Math_FalangProxPolegarRad', 'Value'],
    ['GI_FK_Polegar', 'Flex/Ext Falange Dist Polegar', 'Math_FalangDistPolegarRad', 'Value'],
    ['GI_FK_Polegar', 'Comp Metacarpo Polegar', 'FK_TH_negHalfMC', 'Value'],
    ['GI_FK_Polegar', 'Comp Falange Prox Polegar', 'FK_TH_negHalf1', 'Value'],
    ['GI_FK_Polegar', 'Comp Falange Prox Polegar', 'FK_TH_negLen1', 'Value'],
    ['GI_FK_Polegar', 'Comp Falange Dist Polegar', 'FK_TH_negHalf2', 'Value'],
    ['GI_F009', 'Largura Metacarpo Polegar', 'SzVec_Polegar1', 'X'],
    ['GI_F009', 'Comp Metacarpo Polegar', 'SzVec_Polegar1', 'Y'],
    ['GI_F009', 'Espessura Metacarpo Polegar', 'SzVec_Polegar1', 'Z'],
    ['GI_F009', 'Comp Falange Prox Polegar', 'SzVec_Polegar2', 'Y'],
    ['GI_F009', 'Espessura Falange Prox Polegar', 'SzVec_Polegar2', 'Z'],
    ['GI_F009', 'Comp Falange Dist Polegar', 'SzVec_Polegar3', 'Y'],
    ['GI_F009', 'Espessura Falange Dist Polegar', 'SzVec_Polegar3', 'Z'],
    ['GI_F010', 'Abdução Polegar', 'Math_AbdRad', 'Value'],
    ['GI_F010', 'Flex/Ext Polegar', 'Math_ExtFlexPolegarRad', 'Value'],
    ['GI_F011', 'Largura Metacarpo', 'Math.031', 'Value'],
    ['GI_F011', 'Comp Metacarpo', 'Combine XYZ.008', 'Y'],
    ['GI_F011', 'Comp Metacarpo', 'Combine XYZ.009', 'Y'],
    ['GI_F011', 'Espessura Metacarpo', 'Combine XYZ.008', 'Z'],
    ['GI_F011', 'Espessura Metacarpo', 'Combine XYZ.009', 'Z'],
    ['GI_F012', 'Comp Falange Prox 1', 'Combine XYZ.010', 'Y'],
    ['GI_F012', 'Comp Falange Media 1', 'Combine XYZ.011', 'Y'],
    ['GI_F012', 'Comp Falange Dist 1', 'Combine XYZ.012', 'Y'],
    ['GI_F012', 'Espessura Falange Prox 1', 'Combine XYZ.010', 'Z'],
    ['GI_F012', 'Espessura Falange Media 1', 'Combine XYZ.011', 'Z'],
    ['GI_F012', 'Espessura Falange Dist 1', 'Combine XYZ.012', 'Z'],
    ['GI_F013', 'Comp Falange Prox 2', 'Combine XYZ.013', 'Y'],
    ['GI_F013', 'Comp Falange Media 2', 'Combine XYZ.014', 'Y'],
    ['GI_F013', 'Comp Falange Dist 2', 'Combine XYZ.015', 'Y'],
    ['GI_F013', 'Espessura Falange Prox 2', 'Combine XYZ.013', 'Z'],
    ['GI_F013', 'Espessura Falange Media 2', 'Combine XYZ.014', 'Z'],
    ['GI_F013', 'Espessura Falange Dist 2', 'Combine XYZ.015', 'Z'],
    ['TF_Polegar2', 'Geometry', 'Join_Polegar_Raw', 'Geometry'],
    ['TF_Falange22', 'Geometry', 'Join_Falanges', 'Geometry'],
    ['Join_Metacarpos', 'Geometry', 'Join_MaoBruta', 'Geometry'],
    ['TF_ExtensaoFlexao', 'Geometry', 'Join_Geral', 'Geometry'],
    ['TF_Metacarpo1.001', 'Geometry', 'Join_Geral.003', 'Geometry'],
    ['TF_Antebraco.001', 'Geometry', 'Join_Geral.004', 'Geometry'],
    ['TF_Falange11', 'Geometry', 'Join_Metacarpos', 'Geometry'],
    ['TF_Polegar3', 'Geometry', 'Join_Polegar_Raw', 'Geometry'],
    ['TF_Metacarpo2', 'Geometry', 'Join_Metacarpos', 'Geometry'],
    ['TF_Falange23', 'Geometry', 'Join_Falanges', 'Geometry'],
    ['Join_Falanges', 'Geometry', 'Join_MaoBruta', 'Geometry'],
    ['Join_Geral.003', 'Geometry', 'Join_MaoBruta', 'Geometry'],
]


# ============================ MOTOR DE CONSTRUCAO ===========================

def fresh_tree(name):
    existing = bpy.data.node_groups.get(name)
    if existing is not None:
        bpy.data.node_groups.remove(existing)
    tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
    tree.use_fake_user = True
    return tree


def build_interface(tree, items):
    panels = {}
    for it in items:
        if it["kind"] == "panel":
            panel = tree.interface.new_panel(it["name"])
            if it.get("closed"):
                panel.default_closed = True
            panels[it["name"]] = panel
            continue
        sock = tree.interface.new_socket(
            name=it["name"], in_out=it["in_out"], socket_type=it["socket_type"]
        )
        if it.get("subtype") and hasattr(sock, "subtype"):
            sock.subtype = it["subtype"]
        for attr in ("min_value", "max_value"):
            if it.get(attr) is not None and hasattr(sock, attr):
                setattr(sock, attr, it[attr])
        if it.get("default") is not None and hasattr(sock, "default_value"):
            sock.default_value = it["default"]
        if it.get("parent"):
            tree.interface.move_to_parent(sock, panels[it["parent"]], 10_000)


def find_socket(sockets, key, by_name):
    for s in sockets:
        if (s.name if by_name else s.identifier) == key:
            return s
    raise KeyError("socket nao encontrado: %s" % key)


def build_nodes(tree, node_data):
    made = {}
    for d in node_data:
        n = tree.nodes.new(d["type"])
        n.name = d["name"]
        n.label = d.get("label") or d["name"]
        if d.get("node_tree"):
            n.node_tree = bpy.data.node_groups[d["node_tree"]]
        if d.get("operation"):
            n.operation = d["operation"]
        if d.get("use_clamp"):
            n.use_clamp = True
        made[d["name"]] = n
    for d in node_data:
        n = made[d["name"]]
        if d.get("parent"):
            n.parent = made[d["parent"]]
        n.location = d["loc"]
    for d in node_data:
        n = made[d["name"]]
        by_name = d["type"] in NAME_ADDRESSED
        for key, val in d.get("defaults", []):
            try:
                find_socket(n.inputs, key, by_name).default_value = val
            except Exception:
                pass
    return made


def build_links(tree, made, link_data):
    for fn, fs, tn, ts in link_data:
        a = find_socket(made[fn].outputs, fs, made[fn].bl_idname in NAME_ADDRESSED)
        b = find_socket(made[tn].inputs, ts, made[tn].bl_idname in NAME_ADDRESSED)
        tree.links.new(a, b)


def tidy_group_inputs(tree):
    for n in tree.nodes:
        if n.bl_idname == "NodeGroupInput":
            for s in n.outputs:
                s.hide = not s.is_linked


def build():
    grp = fresh_tree(GENERATED_GROUP_NAME)
    build_interface(grp, GROUP_INTERFACE)
    made = build_nodes(grp, GROUP_NODES)
    build_links(grp, made, GROUP_LINKS)
    tidy_group_inputs(grp)

    tree = fresh_tree(GENERATED_TREE_NAME)
    build_interface(tree, INTERFACE)
    made = build_nodes(tree, NODES)
    build_links(tree, made, LINKS)
    tidy_group_inputs(tree)

    bad = [l for l in tree.links if not l.is_valid] + [l for l in grp.links if not l.is_valid]
    print("[GN_Biomodel_Source] %s: %d nos / %d links | %s: %d nos / %d links | links invalidos: %d"
          % (GENERATED_GROUP_NAME, len(grp.nodes), len(grp.links),
             GENERATED_TREE_NAME, len(tree.nodes), len(tree.links), len(bad)))
    return tree


build()
