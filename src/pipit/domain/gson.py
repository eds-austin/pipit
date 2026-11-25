"""JSON exactly as Gson writes it, for text Scythebill reads back or compares.

- ``parse`` keeps what Gson's ``JsonParser`` keeps: object member order, and each number as
  its own text (Gson's ``LazilyParsedNumber`` writes back what it read).
- ``dumps`` is ``Gson.toJson`` with Gson's defaults: HTML-safe escaping (``<``, ``>``,
  ``&``, ``=`` and ``'`` as ``\\u003c`` and so on), U+2028 and U+2029 escaped, control
  characters as ``\\uXXXX`` except the short escapes, and null object members left out
  (``serializeNulls`` is off). ``pretty=True`` is ``setPrettyPrinting()``: two-space
  indents and ``": "`` after names.
"""

from __future__ import annotations

import json
from typing import Any


class Number(str):
    """A JSON number kept as the text it was read from."""

    __slots__ = ()


_SHORT = {'"': '\\"', "\\": "\\\\", "\t": "\\t", "\b": "\\b", "\n": "\\n", "\r": "\\r",
          "\f": "\\f"}  # fmt: skip
_HTML = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026", "=": "\\u003d", "'": "\\u0027"}
_ESCAPES = {chr(code): f"\\u{code:04x}" for code in range(0x20)}
_ESCAPES.update({chr(0x2028): "\\u2028", chr(0x2029): "\\u2029"})
_ESCAPES.update(_SHORT)
_ESCAPES.update(_HTML)


def parse(text: str) -> Any:
    """``JsonParser.parseString`` (strict JSON): dicts keep member order; numbers stay text."""
    return json.loads(text, parse_int=Number, parse_float=Number,
                      parse_constant=Number)  # fmt: skip


def quote(text: str) -> str:
    return '"' + "".join(_ESCAPES.get(char, char) for char in text) + '"'


def _number(value: float | int) -> str:
    if isinstance(value, bool):
        raise TypeError("bool is not a number")
    if isinstance(value, int):
        return str(value)
    # Java's Double.toString for the values queries hold (no exponent forms needed here).
    text = repr(float(value))
    return text if ("." in text or "e" in text or "n" in text) else text + ".0"


def dumps(value: Any, *, pretty: bool = False) -> str:
    out: list[str] = []
    _write(value, out, pretty, 0)
    return "".join(out)


def _write(value: Any, out: list[str], pretty: bool, depth: int) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, Number):
        out.append(str(value))
    elif isinstance(value, str):
        out.append(quote(value))
    elif isinstance(value, int | float):
        out.append(_number(value))
    elif isinstance(value, dict):
        members = [(key, item) for key, item in value.items() if item is not None]
        if not members:
            out.append("{}")
            return
        out.append("{")
        for i, (key, item) in enumerate(members):
            if i:
                out.append(",")
            if pretty:
                out.append("\n" + "  " * (depth + 1))
            out.append(quote(key))
            out.append(": " if pretty else ":")
            _write(item, out, pretty, depth + 1)
        if pretty:
            out.append("\n" + "  " * depth)
        out.append("}")
    elif isinstance(value, list | tuple):
        if not value:
            out.append("[]")
            return
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            if pretty:
                out.append("\n" + "  " * (depth + 1))
            _write(item, out, pretty, depth + 1)
        if pretty:
            out.append("\n" + "  " * depth)
        out.append("]")
    else:
        raise TypeError(f"not JSON: {type(value).__name__}")
