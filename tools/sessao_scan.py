"""Registro de sessão ao vivo: scan bruto -> biomodelo ajustado.

Cada "marco" captura o estado vivo do Blender via bridge TCP, compara com o
marco anterior e grava o diff. A narração do operador entra como texto no
mesmo registro, de modo que a intenção declarada fica pareada com a mudança
concreta que ocorreu na cena.

Uso (a partir da raiz do repositório):

    python tools/sessao_scan.py inicio --paciente P01 --nota "equino grave, D"
    python tools/sessao_scan.py marco "alinhei pelo maleolo lateral"
    python tools/sessao_scan.py marco "ajustei largura da palma" --render Biomodelo_v2
    python tools/sessao_scan.py fim

    python tools/sessao_scan.py estado     # onde estamos
    python tools/sessao_scan.py resumo     # imprime a linha do tempo

Protótipo de pesquisa. Não é software médico validado.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import re
import sys
import unicodedata

_RAIZ = pathlib.Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from blender_connection import BlenderConnection, BlenderConnectionError  # noqa: E402

BASE = _RAIZ / "runtime" / "sessoes_scan"
PONTEIRO = BASE / ".sessao_atual"

# Árvores de interesse, em ordem de preferência.
ARVORES = ("Biomodelo_v2", "Biomodelo")


# --------------------------------------------------------------------------
# captura no Blender
# --------------------------------------------------------------------------

CODIGO_CAPTURA = r'''
import bpy, json

ALVOS = %(arvores)s

info = {
    "arquivo": bpy.data.filepath,
    "frame": bpy.context.scene.frame_current,
    "arvores": {},
    "objetos": [],
    "selecionados": [],
    "ativo": None,
    "modo": getattr(bpy.context, "mode", None),
}

def _lista(v):
    try:
        if hasattr(v, "__len__") and not isinstance(v, str):
            return [round(float(x), 6) for x in v]
    except Exception:
        pass
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, (int, bool, str)) or v is None:
        return v
    return repr(v)

def _valor(mod, ident):
    """Le um input de modificador GN.

    Blender 5.2 removeu o acesso por item (mod["Socket_N"] -> TypeError "this
    type doesn't support IDProperties"). O caminho certo e ACESSO POR ATRIBUTO:
    getattr(mod.properties.inputs, ident).value. Cuidado: o subscrito
    mod.properties.inputs[ident] tambem "funciona", mas devolve um
    IDPropertyGroup sem .value -- parece certo e da erro em todo socket.

    NAO usar mod.node_group.interface[...].default_value como fallback: e o
    default da arvore, nao o valor desta instancia (medido: 273.64 na arvore vs
    278.54 no modificador).
    """
    try:
        return _lista(getattr(mod.properties.inputs, ident).value)
    except Exception as novo:
        try:
            return _lista(mod[ident])
        except Exception as antigo:
            return f"<erro: {type(novo).__name__} / {type(antigo).__name__}>"

# Alem das arvores preferidas, rastreia qualquer node group de GN realmente em
# uso na cena -- evita registrar zero parametros so porque o nome mudou.
_alvos = list(ALVOS)
for _obj in bpy.data.objects:
    for _m in _obj.modifiers:
        if _m.type == "NODES" and _m.node_group and _m.node_group.name not in _alvos:
            _alvos.append(_m.node_group.name)

for nome in _alvos:
    tree = bpy.data.node_groups.get(nome)
    if tree is None:
        continue
    entradas = []
    for it in tree.interface.items_tree:
        if getattr(it, "item_type", "") == "SOCKET" and getattr(it, "in_out", "") == "INPUT":
            entradas.append({
                "nome": it.name,
                "id": it.identifier,
                "tipo": it.socket_type,
            })
    usos = []
    for obj in bpy.data.objects:
        for m in obj.modifiers:
            if m.type == "NODES" and m.node_group is tree:
                valores = {}
                for e in entradas:
                    valores[e["id"]] = _valor(m, e["id"])
                usos.append({
                    "objeto": obj.name,
                    "modificador": m.name,
                    "valores": valores,
                })
    info["arvores"][nome] = {
        "n_nos": len(tree.nodes),
        "entradas": entradas,
        "usos": usos,
    }

for obj in bpy.data.objects:
    reg = {
        "nome": obj.name,
        "tipo": obj.type,
        "visivel": not obj.hide_viewport,
        "loc": [round(float(x), 5) for x in obj.location],
        "rot": [round(float(x), 5) for x in obj.rotation_euler],
        "escala": [round(float(x), 5) for x in obj.scale],
        "modificadores": [{"nome": m.name, "tipo": m.type} for m in obj.modifiers],
    }
    if obj.type == "MESH" and obj.data is not None:
        reg["verts"] = len(obj.data.vertices)
        reg["polys"] = len(obj.data.polygons)
    info["objetos"].append(reg)

try:
    info["selecionados"] = [o.name for o in bpy.context.selected_objects]
    if bpy.context.active_object is not None:
        info["ativo"] = bpy.context.active_object.name
except Exception:
    pass

result = info
''' % {"arvores": json.dumps(list(ARVORES))}


def capturar(conn: BlenderConnection) -> dict:
    resp = conn.execute_code(CODIGO_CAPTURA)
    if resp.get("status") != "success":
        raise BlenderConnectionError(f"captura falhou: {resp.get('error', resp)}")
    r = resp.get("result")
    if isinstance(r, dict) and "result" in r and isinstance(r["result"], dict):
        r = r["result"]
    if not isinstance(r, dict):
        raise BlenderConnectionError(f"resposta inesperada do bridge: {type(r)}")
    return r


# --------------------------------------------------------------------------
# diff
# --------------------------------------------------------------------------

def _quase_igual(a, b, tol: float = 1e-5) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(float(a) - float(b)) <= tol
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return all(_quase_igual(x, y, tol) for x, y in zip(a, b))
    return a == b


def diff_estados(antes: dict | None, agora: dict) -> dict:
    """Diferença legível entre dois marcos. Só o que mudou."""
    if antes is None:
        n_par = sum(
            len(u["valores"])
            for t in agora.get("arvores", {}).values()
            for u in t.get("usos", [])
        )
        return {
            "primeiro_marco": True,
            "objetos": len(agora.get("objetos", [])),
            "parametros_rastreados": n_par,
        }

    d: dict = {"parametros": [], "objetos": [], "cena": []}

    # parâmetros de Geometry Nodes
    for arv, ta in agora.get("arvores", {}).items():
        tb = antes.get("arvores", {}).get(arv, {})
        rotulo = {e["id"]: e["nome"] for e in ta.get("entradas", [])}
        antes_usos = {(u["objeto"], u["modificador"]): u["valores"] for u in tb.get("usos", [])}
        for u in ta.get("usos", []):
            va = antes_usos.get((u["objeto"], u["modificador"]), {})
            for ident, valor in u["valores"].items():
                anterior = va.get(ident, "<ausente>")
                if not _quase_igual(anterior, valor):
                    d["parametros"].append({
                        "arvore": arv,
                        "objeto": u["objeto"],
                        "parametro": rotulo.get(ident, ident),
                        "id": ident,
                        "de": anterior,
                        "para": valor,
                    })
        if ta.get("n_nos") != tb.get("n_nos"):
            d["cena"].append(f"{arv}: nós {tb.get('n_nos')} -> {ta.get('n_nos')}")

    # objetos
    ant_obj = {o["nome"]: o for o in antes.get("objetos", [])}
    ago_obj = {o["nome"]: o for o in agora.get("objetos", [])}
    for nome in sorted(set(ago_obj) - set(ant_obj)):
        # Objeto novo carrega o transform como parte da criacao. No fluxo de scan
        # o alinhamento E o transform do objeto importado, entao registrar so
        # "criado" perderia justamente o dado central do marco.
        novo = ago_obj[nome]
        reg = {"nome": nome, "mudanca": "criado", "tipo": novo["tipo"]}
        for campo in ("loc", "rot", "escala", "verts", "polys"):
            if campo in novo:
                reg[campo] = novo[campo]
        d["objetos"].append(reg)
    for nome in sorted(set(ant_obj) - set(ago_obj)):
        d["objetos"].append({"nome": nome, "mudanca": "removido"})
    for nome in sorted(set(ant_obj) & set(ago_obj)):
        a, b = ant_obj[nome], ago_obj[nome]
        campos = []
        for campo in ("loc", "rot", "escala", "visivel", "verts", "polys"):
            if campo in a or campo in b:
                if not _quase_igual(a.get(campo), b.get(campo)):
                    campos.append({"campo": campo, "de": a.get(campo), "para": b.get(campo)})
        ma = [m["nome"] for m in a.get("modificadores", [])]
        mb = [m["nome"] for m in b.get("modificadores", [])]
        if ma != mb:
            campos.append({"campo": "modificadores", "de": ma, "para": mb})
        if campos:
            d["objetos"].append({"nome": nome, "mudanca": "alterado", "campos": campos})

    if antes.get("arquivo") != agora.get("arquivo"):
        d["cena"].append(f"arquivo: {antes.get('arquivo')!r} -> {agora.get('arquivo')!r}")

    d["vazio"] = not (d["parametros"] or d["objetos"] or d["cena"])
    return d


def _graus(rot) -> str:
    """Rotacao em graus. O registro guarda radianos (fiel ao Blender), mas o
    operador raciocina em graus -- ler '70.6 graus' e imediato, '1.2326' nao."""
    import math
    if not isinstance(rot, list):
        return str(rot)
    return "[" + ", ".join(f"{math.degrees(r):.3f}" for r in rot) + "] graus"


def diff_texto(d: dict) -> str:
    if d.get("primeiro_marco"):
        return (f"marco inicial — {d['objetos']} objetos, "
                f"{d['parametros_rastreados']} parâmetros sob rastreio")
    if d.get("vazio"):
        return "nenhuma mudança detectada na cena"
    linhas = []
    for p in d["parametros"]:
        linhas.append(f"  param  {p['objeto']} / {p['parametro']}: {p['de']} -> {p['para']}")
    for o in d["objetos"]:
        if o["mudanca"] == "alterado":
            for c in o["campos"]:
                if c["campo"] == "rot":
                    linhas.append(f"  obj    {o['nome']}.rot: {_graus(c['de'])} -> {_graus(c['para'])}")
                else:
                    linhas.append(f"  obj    {o['nome']}.{c['campo']}: {c['de']} -> {c['para']}")
        elif o["mudanca"] == "criado":
            linhas.append(f"  obj    {o['nome']}: criado ({o.get('tipo')})")
            if "loc" in o:
                linhas.append(f"           loc {o['loc']}  rot {_graus(o.get('rot'))}  escala {o.get('escala')}")
            if o.get("verts") is not None:
                linhas.append(f"           malha {o['verts']} verts / {o.get('polys')} polys")
        else:
            linhas.append(f"  obj    {o['nome']}: {o['mudanca']}")
    for c in d["cena"]:
        linhas.append(f"  cena   {c}")
    return "\n".join(linhas)


# --------------------------------------------------------------------------
# sessão
# --------------------------------------------------------------------------

def _slug(texto: str, limite: int = 40) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "_", t).strip("_").lower()
    return (t[:limite] or "marco")


def _agora() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def sessao_atual() -> pathlib.Path:
    if not PONTEIRO.exists():
        raise SystemExit("nenhuma sessão aberta — rode: python tools/sessao_scan.py inicio --paciente X")
    p = pathlib.Path(PONTEIRO.read_text(encoding="utf-8").strip())
    if not p.exists():
        raise SystemExit(f"sessão apontada não existe mais: {p}")
    return p


def _marcos(dir_sessao: pathlib.Path) -> list[pathlib.Path]:
    return sorted(dir_sessao.glob("[0-9][0-9][0-9]_*.json"))


def cmd_inicio(args) -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    carimbo = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    dir_sessao = BASE / f"{_slug(args.paciente, 24)}_{carimbo}"
    dir_sessao.mkdir()
    meta = {
        "paciente": args.paciente,
        "nota": args.nota or "",
        "escopo": "scan bruto -> biomodelo ajustado",
        "inicio": _agora(),
        "fim": None,
    }
    (dir_sessao / "sessao.json").write_text(
        json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    (dir_sessao / "narrativa.md").write_text(
        f"# Sessão — {args.paciente}\n\n"
        f"- início: {meta['inicio']}\n"
        f"- nota: {meta['nota'] or '—'}\n"
        f"- escopo: {meta['escopo']}\n\n---\n\n", encoding="utf-8")
    PONTEIRO.write_text(str(dir_sessao), encoding="utf-8")
    print(f"sessão aberta: {dir_sessao}")
    print("agora rode um marco a cada passo relevante:")
    print('  python tools/sessao_scan.py marco "o que você acabou de fazer e por quê"')


def cmd_marco(args) -> None:
    dir_sessao = sessao_atual()
    conn = BlenderConnection(port=args.porta) if args.porta else BlenderConnection()

    try:
        estado = capturar(conn)
    except BlenderConnectionError as exc:
        raise SystemExit(f"bridge indisponível: {exc}")

    anteriores = _marcos(dir_sessao)
    n = len(anteriores) + 1
    antes = None
    if anteriores:
        antes = json.loads(anteriores[-1].read_text(encoding="utf-8")).get("estado")

    d = diff_estados(antes, estado)

    render_rel = None
    if args.render:
        alvo = dir_sessao / f"{n:03d}_{_slug(args.narracao)}.png"
        try:
            r = conn.render_viewport(args.render, view=args.vista, path=str(alvo), resolution=900)
            if r.get("status") == "success":
                render_rel = alvo.name
            else:
                print(f"  (render falhou: {r.get('error')})")
        except BlenderConnectionError as exc:
            print(f"  (render falhou: {exc})")

    registro = {
        "n": n,
        "hora": _agora(),
        "narracao": args.narracao,
        "criterio": args.criterio or "",
        "excecao": args.excecao or "",
        "render": render_rel,
        "diff": d,
        "estado": estado,
    }
    caminho = dir_sessao / f"{n:03d}_{_slug(args.narracao)}.json"
    caminho.write_text(json.dumps(registro, indent=1, ensure_ascii=False), encoding="utf-8")

    texto = diff_texto(d)
    with (dir_sessao / "narrativa.md").open("a", encoding="utf-8") as f:
        f.write(f"## {n:03d} — {args.narracao}\n\n")
        f.write(f"*{registro['hora']}*\n\n")
        if args.criterio:
            f.write(f"**Critério:** {args.criterio}\n\n")
        if args.excecao:
            f.write(f"**Exceção:** {args.excecao}\n\n")
        f.write("```\n" + texto + "\n```\n\n")
        if render_rel:
            f.write(f"![marco {n}]({render_rel})\n\n")

    print(f"marco {n:03d} gravado — {caminho.name}")
    print(texto)


def cmd_fim(args) -> None:
    dir_sessao = sessao_atual()
    meta_p = dir_sessao / "sessao.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    meta["fim"] = _agora()
    meta["marcos"] = len(_marcos(dir_sessao))
    meta_p.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    PONTEIRO.unlink(missing_ok=True)
    print(f"sessão encerrada: {dir_sessao} ({meta['marcos']} marcos)")


def cmd_estado(args) -> None:
    if not PONTEIRO.exists():
        print("nenhuma sessão aberta")
        return
    dir_sessao = sessao_atual()
    meta = json.loads((dir_sessao / "sessao.json").read_text(encoding="utf-8"))
    print(f"sessão: {dir_sessao.name}")
    print(f"paciente: {meta['paciente']}  |  marcos: {len(_marcos(dir_sessao))}")
    try:
        ok = BlenderConnection().ping()
    except Exception:
        ok = False
    print(f"bridge: {'ok' if ok else 'sem resposta'}")


def cmd_resumo(args) -> None:
    dir_sessao = sessao_atual() if not args.pasta else pathlib.Path(args.pasta)
    for p in _marcos(dir_sessao):
        r = json.loads(p.read_text(encoding="utf-8"))
        print(f"\n{r['n']:03d} [{r['hora']}] {r['narracao']}")
        if r.get("criterio"):
            print(f"     critério: {r['criterio']}")
        print(diff_texto(r["diff"]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inicio", help="abre uma sessão para um paciente")
    p.add_argument("--paciente", required=True, help="identificador não-nominal, ex.: P01")
    p.add_argument("--nota", default="", help="quadro clínico resumido")
    p.set_defaults(func=cmd_inicio)

    p = sub.add_parser("marco", help="captura o estado atual do Blender")
    p.add_argument("narracao", help="o que você acabou de fazer")
    p.add_argument("--criterio", default="", help="por que você fez assim")
    p.add_argument("--excecao", default="", help="o que faria diferente em outro caso")
    p.add_argument("--render", default="", metavar="OBJETO", help="renderiza a viewport deste objeto")
    p.add_argument("--vista", default="iso", help="iso, front, side, top")
    p.add_argument("--porta", type=int, default=0, help="porta do bridge, se não for a padrão")
    p.set_defaults(func=cmd_marco)

    p = sub.add_parser("fim", help="encerra a sessão")
    p.set_defaults(func=cmd_fim)

    p = sub.add_parser("estado", help="mostra a sessão aberta e testa o bridge")
    p.set_defaults(func=cmd_estado)

    p = sub.add_parser("resumo", help="imprime a linha do tempo da sessão")
    p.add_argument("--pasta", default="", help="pasta de uma sessão específica")
    p.set_defaults(func=cmd_resumo)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
