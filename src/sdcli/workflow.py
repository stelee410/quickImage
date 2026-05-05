"""Workflow loading + parameter substitution.

Workflow files are JSON with ``${var}`` placeholders (typed: ``${name:int}``,
``${name:float}``).
"""
from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any

PLACEHOLDER = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)(?::(int|float|bool|str))?\}")


def _coerce(value: Any, kind: str) -> Any:
    if value is None:
        return value
    if kind == "int":
        return int(value)
    if kind == "float":
        return float(value)
    if kind == "bool":
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1", "yes", "on")
    return value


def _substitute(node: Any, params: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        return {k: _substitute(v, params) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(x, params) for x in node]
    if isinstance(node, str):
        match = PLACEHOLDER.fullmatch(node)
        if match:
            name = match.group(1)
            kind = match.group(2) or "str"
            if name not in params:
                raise KeyError(f"workflow placeholder ${{{name}}} has no value")
            return _coerce(params[name], kind)
        # Inline substitution (e.g., embedded prompt fragments) — left as string
        def repl(m: re.Match[str]) -> str:
            n = m.group(1)
            if n not in params:
                raise KeyError(f"workflow placeholder ${{{n}}} has no value")
            return str(params[n])
        return PLACEHOLDER.sub(repl, node)
    return node


def load(name: str) -> dict[str, Any]:
    """Load a bundled workflow template by name (without .json)."""
    with resources.files("sdcli.workflows").joinpath(f"{name}.json").open("r", encoding="utf-8") as fh:
        return json.load(fh)


def render(template: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Substitute placeholders in ``template`` using ``params``."""
    return _substitute(template, params)
