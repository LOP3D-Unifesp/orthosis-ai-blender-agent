"""Smoke test: Claude Code → socket bridge → Blender (canal direto).

Prova o ciclo mínimo de pilotagem incremental:
  1. Ping — Blender responde via capture_scene
  2. Inventário — list_tree_nodes lista uma árvore real
  3. Inspeção — get_node_context lê um nó real com seus sockets
  4. Patch inofensivo — execute_code roda, imprime, não muta nada
  5. Patch real + restauração — altera um valor, verifica, restaura

Uso:
    python smoke_bridge.py
    python smoke_bridge.py --tree Biomodelo
    python smoke_bridge.py --tree Biomodelo --node "Group Input"

Requer Blender rodando com o addon ativo na porta 65432.
"""

from __future__ import annotations

import argparse
import sys
import textwrap

from blender_connection import BlenderConnection, BlenderConnectionError


# ---------------------------------------------------------------------------
# Helpers de output
# ---------------------------------------------------------------------------

def _ok(label: str, detail: str = "") -> None:
    suffix = f"  ({detail})" if detail else ""
    print(f"  OK   {label}{suffix}")


def _fail(label: str, detail: str = "") -> None:
    suffix = f"  {detail}" if detail else ""
    print(f"  FAIL {label}{suffix}")


def _skip(label: str, reason: str = "") -> None:
    suffix = f"  ({reason})" if reason else ""
    print(f"  SKIP {label}{suffix}")


def _section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ---------------------------------------------------------------------------
# Passo 1 — Ping
# ---------------------------------------------------------------------------

def step_ping(conn: BlenderConnection) -> dict | None:
    _section("Passo 1 — Ping (capture_scene)")
    try:
        result = conn.send_command({"type": "capture_scene"})
    except BlenderConnectionError as exc:
        _fail("capture_scene", str(exc))
        return None

    if result.get("status") != "success":
        _fail("capture_scene", f"status={result.get('status')} error={result.get('error')}")
        return None

    r = result.get("result", {})
    blend_file = r.get("blend_file") or r.get("filepath") or "(desconhecido)"
    obj_count = r.get("object_count", "?")
    _ok("capture_scene", f"blend={blend_file}, {obj_count} objeto(s)")
    return r


# ---------------------------------------------------------------------------
# Passo 2 — Inventário
# ---------------------------------------------------------------------------

def step_list_nodes(conn: BlenderConnection, tree_name: str) -> list[dict] | None:
    _section(f"Passo 2 — Inventário (list_tree_nodes: '{tree_name}')")
    result = conn.list_tree_nodes(tree_name)

    if result.get("status") != "success":
        _fail("list_tree_nodes", f"status={result.get('status')} error={result.get('error')}")
        return None

    r = result.get("result", {})
    nodes = r.get("nodes", [])
    _ok(f"list_tree_nodes", f"{r.get('node_count', '?')} nós na árvore '{tree_name}'")

    frames = [n for n in nodes if n.get("bl_idname") == "NodeFrame"]
    groups = [n for n in nodes if "Group" in str(n.get("bl_idname", ""))]
    _ok(f"  {len(frames)} frame(s), {len(groups)} group(s)")

    sample = nodes[:6]
    for n in sample:
        frame = f"  [frame: {n['parent_frame']}]" if n.get("parent_frame") else ""
        print(f"       {n['name']!r:40s} {n['bl_idname']}{frame}")
    if len(nodes) > 6:
        print(f"       ... +{len(nodes) - 6} nós")

    return nodes


# ---------------------------------------------------------------------------
# Passo 3 — Inspeção
# ---------------------------------------------------------------------------

def step_inspect_node(conn: BlenderConnection, tree_name: str, node_name: str) -> dict | None:
    _section(f"Passo 3 — Inspeção (get_node_context: '{node_name}')")
    result = conn.get_node_context(tree_name, node_name, radius=1)

    if result.get("status") != "success":
        _fail("get_node_context", f"status={result.get('status')} error={result.get('error')}")
        return None

    r = result.get("result", {})
    _ok(f"get_node_context", f"nó='{r.get('target_node')}' vizinhança={r.get('node_count')} nós")

    target = next((n for n in r.get("nodes", []) if n.get("is_target")), None)
    if target:
        inputs = target.get("inputs", [])
        _ok(f"  tipo={target.get('type')}, {len(inputs)} input(s)")
        for sock in inputs[:4]:
            val = sock.get("default_value", "(sem valor)")
            print(f"       input '{sock['name']}': {val}")
        if len(inputs) > 4:
            print(f"       ... +{len(inputs) - 4} inputs")

    links = r.get("links", [])
    if links:
        _ok(f"  {len(links)} link(s) na vizinhança")
        for lk in links[:3]:
            print(f"       {lk['from_node']}.{lk['from_socket']} → {lk['to_node']}.{lk['to_socket']}")

    return r


# ---------------------------------------------------------------------------
# Passo 4 — Patch inofensivo (leitura via execute_code, sem mutação)
# ---------------------------------------------------------------------------

def step_noop_patch(conn: BlenderConnection, tree_name: str) -> bool:
    _section(f"Passo 4 — Patch inofensivo (execute_code, sem mutação)")

    code = textwrap.dedent(f"""\
        # PATCH: leitura inofensiva via execute_code
        # ALVO: {tree_name!r}
        # RISCO: nenhum (sem mutação)
        import bpy
        tree = bpy.data.node_groups.get({tree_name!r})
        assert tree is not None, f"FAIL: árvore '{tree_name}' nao encontrada"
        node_count = len(tree.nodes)
        link_count = len(tree.links)
        print(f"PATCH_NOOP_OK: árvore={{tree.name!r}}, nos={{node_count}}, links={{link_count}}")
    """)

    result = conn.execute_code(code)

    if result.get("status") != "success":
        _fail("execute_code noop", f"error={result.get('error')}")
        traceback = result.get("traceback", "")
        if traceback:
            print(f"       {traceback[:400]}")
        return False

    stdout = result.get("stdout", "").strip()
    if "PATCH_NOOP_OK" not in stdout:
        _fail("execute_code noop", f"stdout inesperado: {stdout!r}")
        return False

    _ok("execute_code noop", stdout)
    return True


# ---------------------------------------------------------------------------
# Passo 5 — Patch real + restauração
# ---------------------------------------------------------------------------

def step_real_patch(conn: BlenderConnection, tree_name: str, node_name: str) -> bool:
    _section(f"Passo 5 — Patch real + restauração ('{node_name}')")

    # Primeiro lemos o nó para saber se tem um input numérico simples
    inspect = conn.get_node_context(tree_name, node_name, radius=0)
    if inspect.get("status") != "success":
        _skip("patch real", f"get_node_context falhou: {inspect.get('error')}")
        return True  # skip não é falha

    nodes = inspect.get("result", {}).get("nodes", [])
    target = next((n for n in nodes if n.get("is_target")), None)
    if not target:
        _skip("patch real", "nó alvo não encontrado na resposta")
        return True

    inputs = target.get("inputs", [])
    # Procura primeiro input com default_value numérico simples (float ou int)
    float_input = None
    float_index = None
    for i, inp in enumerate(inputs):
        val = inp.get("default_value")
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            float_input = inp
            float_index = i
            break

    if float_input is None:
        _skip("patch real", f"nó '{node_name}' não tem input numérico simples — escolha outro nó")
        return True

    original_val = float_input["default_value"]
    # Preserva o tipo do socket: int socket → incremento int, float → float
    if isinstance(original_val, int):
        test_val = original_val + 1
    else:
        test_val = round(original_val + 1.0, 4)
    input_name = float_input["name"]

    _ok(f"  alvo: input '{input_name}' (índice {float_index}), valor atual = {original_val}")
    _ok(f"  vai alterar para {test_val}, depois restaurar para {original_val}")

    code = textwrap.dedent(f"""\
        # PATCH: alterar e restaurar input numérico (smoke test)
        # ALVO: {tree_name!r} / {node_name!r} / input[{float_index}] ({input_name!r})
        # RISCO: baixo (restaura o valor original na mesma execução)
        import bpy
        TREE_NAME = {tree_name!r}
        NODE_NAME = {node_name!r}
        INPUT_INDEX = {float_index}
        ORIGINAL_VALUE = {original_val!r}
        TEST_VALUE = {test_val!r}

        tree = bpy.data.node_groups.get(TREE_NAME)
        assert tree is not None, f"FAIL: arvore {{TREE_NAME!r}} nao encontrada"
        node = tree.nodes.get(NODE_NAME)
        assert node is not None, f"FAIL: no {{NODE_NAME!r}} nao encontrado"
        assert INPUT_INDEX < len(node.inputs), f"FAIL: input index {{INPUT_INDEX}} fora do range"

        antes = node.inputs[INPUT_INDEX].default_value
        print(f"ANTES: {{antes}}")

        node.inputs[INPUT_INDEX].default_value = TEST_VALUE
        depois = node.inputs[INPUT_INDEX].default_value
        print(f"DEPOIS: {{depois}}")
        assert abs(float(depois) - TEST_VALUE) < 0.001, f"FAIL: esperado {{TEST_VALUE}}, obtido {{depois}}"
        print("PATCH_OK: valor alterado com sucesso")

        node.inputs[INPUT_INDEX].default_value = ORIGINAL_VALUE
        restaurado = node.inputs[INPUT_INDEX].default_value
        print(f"RESTAURADO: {{restaurado}}")
        assert abs(float(restaurado) - ORIGINAL_VALUE) < 0.001, f"FAIL: restauracao falhou, obtido {{restaurado}}"
        print("RESTORE_OK: valor restaurado com sucesso")
    """)

    result = conn.execute_code(code)

    if result.get("status") != "success":
        _fail("patch real", f"execute_code erro: {result.get('error')}")
        traceback = result.get("traceback", "")
        if traceback:
            print(f"       {traceback[:600]}")
        return False

    stdout = result.get("stdout", "").strip()
    for line in stdout.splitlines():
        print(f"       {line}")

    if "PATCH_OK" not in stdout or "RESTORE_OK" not in stdout:
        _fail("patch real", "stdout não confirma PATCH_OK + RESTORE_OK")
        return False

    _ok("patch real", "alteração e restauração confirmadas via stdout")

    # Verificação extra: re-leitura via bridge confirma valor restaurado
    verify = conn.get_node_context(tree_name, node_name, radius=0)
    if verify.get("status") == "success":
        vnodes = verify.get("result", {}).get("nodes", [])
        vtarget = next((n for n in vnodes if n.get("is_target")), None)
        if vtarget:
            vinputs = vtarget.get("inputs", [])
            if float_index < len(vinputs):
                live_val = vinputs[float_index].get("default_value")
                if isinstance(live_val, (int, float)) and abs(float(live_val) - float(original_val)) < 0.001:
                    _ok("re-leitura via bridge", f"valor confirmado = {live_val}")
                else:
                    _fail("re-leitura via bridge", f"esperado {original_val}, lido {live_val}")
                    return False

    return True


# ---------------------------------------------------------------------------
# Orquestrador
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test: bridge Claude Code → Blender")
    parser.add_argument("--tree", default="Biomodelo", help="Nome da árvore GN a testar (default: Biomodelo)")
    parser.add_argument("--node", default="", help="Nome do nó a inspecionar/patchear (default: primeiro nó não-frame)")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=65432)
    args = parser.parse_args()

    conn = BlenderConnection(host=args.host, port=args.port)

    print(f"\nSmoke test: Claude Code → socket bridge → Blender")
    print(f"  target: {args.host}:{args.port}  tree: {args.tree}")

    passed = 0
    failed = 0

    # Passo 1 — Ping
    scene = step_ping(conn)
    if scene is None:
        print("\nNão foi possível conectar ao Blender. Encerrando.")
        return 1
    passed += 1

    # capture_scene não garante listar node_group_names — list_tree_nodes é a fonte certa

    # Passo 2 — Inventário
    nodes = step_list_nodes(conn, args.tree)
    if nodes is None:
        failed += 1
    else:
        passed += 1

    # Resolve nó alvo
    node_name = args.node
    if not node_name and nodes:
        # Primeiro nó não-frame com algum conteúdo
        for n in nodes:
            if n.get("bl_idname") != "NodeFrame":
                node_name = n["name"]
                break

    if not node_name:
        _skip("passos 3-5", "nenhum nó disponível para inspecionar")
        print(f"\nResultado: {passed} ok, {failed} falhas, 3 pulados")
        return 1 if failed else 0

    # Passo 3 — Inspeção
    node_ctx = step_inspect_node(conn, args.tree, node_name)
    if node_ctx is None:
        failed += 1
    else:
        passed += 1

    # Passo 4 — Patch inofensivo
    if step_noop_patch(conn, args.tree):
        passed += 1
    else:
        failed += 1

    # Passo 5 — Patch real + restauração
    if step_real_patch(conn, args.tree, node_name):
        passed += 1
    else:
        failed += 1

    # Sumário
    total = passed + failed
    print(f"\n{'═' * 60}")
    status = "PASSOU" if failed == 0 else "FALHOU"
    print(f"  {status}   {passed}/{total} passos ok")
    print(f"{'═' * 60}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
