"""Leitura/escrita de valores de socket do modifier + presets JSON.

Funções puras (não importam bpy): operam sobre um ``modifier`` já obtido pelo
chamador, via ``modifier[identifier]``. Usado pelo addon (Etapa 3) para aplicar
a antropometria, salvar e carregar presets (incl. o scan de referência).

O formato do preset é o mesmo de ``presets/scan_referencia.json`` (schema 1.0).
"""

from __future__ import annotations

import json

from .source_template import PARAMETERS

# (name, identifier, default, role) → estruturas auxiliares
ALL_IDENTIFIERS: tuple[str, ...] = tuple(ident for (_n, ident, _d, _r) in PARAMETERS)
PARAM_META: dict[str, dict] = {
    ident: {"name": name, "default": default, "role": role}
    for (name, ident, default, role) in PARAMETERS
}

PRESET_SCHEMA_VERSION = "1.0"


def read_socket_values(modifier, identifiers=None) -> dict:
    """Lê valores atuais dos sockets do modifier. ``identifiers`` default = os 31."""
    ids = identifiers if identifiers is not None else ALL_IDENTIFIERS
    out = {}
    for ident in ids:
        try:
            out[ident] = modifier[ident]
        except (KeyError, TypeError):
            out[ident] = None
    return out


def write_socket_values(modifier, values: dict) -> list:
    """Escreve ``{identifier: valor}`` no modifier. Retorna a lista aplicada."""
    applied = []
    for ident, val in values.items():
        if val is None:
            continue
        try:
            modifier[ident] = float(val)
            applied.append(ident)
        except Exception:
            pass
    return applied


def build_preset_dict(modifier, *, name: str = "preset", description: str = "") -> dict:
    """Serializa os valores atuais do modifier (31 sockets) no formato de preset."""
    params = []
    for (pname, ident, _default, role) in PARAMETERS:
        try:
            value = modifier[ident]
        except (KeyError, TypeError):
            value = None
        params.append({"name": pname, "identifier": ident, "role": role, "value": value})
    return {
        "preset_name": name,
        "description": description,
        "schema_version": PRESET_SCHEMA_VERSION,
        "param_count": len(params),
        "parameters": params,
    }


def save_preset_file(path: str, modifier, *, name: str = "preset", description: str = "") -> dict:
    data = build_preset_dict(modifier, name=name, description=description)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return data


def load_preset_file(path: str) -> dict:
    """Lê um preset JSON e retorna ``{identifier: valor}`` (ignora valores nulos)."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    out = {}
    for p in data.get("parameters", []):
        ident = p.get("identifier")
        val = p.get("value")
        if ident and val is not None:
            out[ident] = val
    return out


__all__ = [
    "ALL_IDENTIFIERS", "PARAM_META", "PRESET_SCHEMA_VERSION",
    "read_socket_values", "write_socket_values",
    "build_preset_dict", "save_preset_file", "load_preset_file",
]
