"""A minimal TOML writer for our own config files (reading uses :mod:`tomllib`).

Supports nested tables, strings, ints, floats, bools, arrays of scalars and arrays
of inline tables — enough for settings and drive profiles without a dependency.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any

_BARE = re.compile(r"^[A-Za-z0-9_-]+$")


def _key(k: str) -> str:
    return k if _BARE.match(k) else json.dumps(k, ensure_ascii=False)


def _value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError(f"{v} cannot be stored")
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, Mapping):
        return "{ " + ", ".join(f"{_key(k)} = {_value(x)}" for k, x in v.items()) + " }"
    if isinstance(v, list | tuple):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    raise TypeError(f"cannot store {type(v).__name__} in TOML")


def dumps(data: Mapping[str, Any]) -> str:
    lines: list[str] = []

    def table(path: list[str], d: Mapping[str, Any]) -> None:
        scalars = {k: v for k, v in d.items() if not isinstance(v, Mapping) and v is not None}
        subs = {k: v for k, v in d.items() if isinstance(v, Mapping)}
        if path and (scalars or not subs):
            lines.append(f"[{'.'.join(_key(p) for p in path)}]")
        for k, v in scalars.items():
            lines.append(f"{_key(k)} = {_value(v)}")
        if scalars:
            lines.append("")
        for k, v in subs.items():
            table([*path, k], v)

    table([], data)
    return "\n".join(lines).rstrip() + "\n"
