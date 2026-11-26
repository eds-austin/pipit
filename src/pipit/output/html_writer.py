"""HTML written exactly as Scythebill's ``IndentingResponseWriter`` over ``HtmlResponseWriter``
writes it (``model/.../io``).

- Text escapes ``<``, ``>`` and ``&``; attributes ``"`` too. Anything outside ASCII becomes a
  hex character reference per UTF-16 unit (so an emoji is two: ``&#xd83d;&#xdc26;``).
- ``<meta>``, ``<br>`` and the other empty elements get no end tag.
- An element starts on a new line, indented two spaces per level (at most 50), except at the
  top level; text after an element that just ended starts a new line too. Without
  ``indent`` (``HtmlResponseWriter`` alone, as trip reports use it), nothing is added.
"""

from __future__ import annotations

_EMPTY = frozenset({"area", "br", "base", "basefont", "col", "frame", "hr", "img", "input",
                    "isindex", "link", "meta", "param"})  # fmt: skip
_MAX_INDENT = 50


def _escape(text: str, attribute: bool) -> str:
    out: list[str] = []
    for char in text:
        code = ord(char)
        if code <= 0x7F:
            if char == ">":
                out.append("&gt;")
            elif char == "<":
                out.append("&lt;")
            elif char == "&":
                out.append("&amp;")
            elif char == '"' and attribute:
                out.append("&quot;")
            else:
                out.append(char)
        elif code > 0xFFFF:
            code -= 0x10000
            out.append(f"&#x{0xD800 + (code >> 10):x};&#x{0xDC00 + (code & 0x3FF):x};")
        else:
            out.append(f"&#x{code:x};")
    return "".join(out)


class HtmlWriter:
    def __init__(self, indent: bool = True) -> None:
        self._indenting = indent
        self._out: list[str] = []
        self._close_start = False
        self._depth = 0
        self._just_ended = False

    def text(self) -> str:
        return "".join(self._out)

    # ------------------------------------------------------------ HtmlResponseWriter

    def _close_start_if_necessary(self) -> None:
        if self._close_start:
            self._out.append(">")
            self._close_start = False

    def _write(self, text: str) -> None:
        self._close_start_if_necessary()
        self._out.append(text)

    def _indent(self, depth: int) -> None:
        if not self._indenting:
            return
        self._write("\n" + " " * min(depth * 2, _MAX_INDENT))

    def _see_if_just_ended(self) -> None:
        if self._just_ended:
            self._just_ended = False
            self._indent(self._depth)

    # ------------------------------------------------------------ the writer's API

    def start_document(self) -> None:
        self._out.append("<!DOCTYPE html>\n")

    def comment(self, comment: str) -> None:
        self._see_if_just_ended()
        self._close_start_if_necessary()
        self._out.append(f"<!-- {comment} -->")
        self._out.append("\n")

    def start(self, name: str) -> None:
        depth = self._depth
        self._depth += 1
        if depth > 0:
            self._indent(depth)
        self._just_ended = False
        self._close_start_if_necessary()
        self._out.append("<" + name)
        self._close_start = True

    def attribute(self, name: str, value: object) -> None:
        if value is None:
            return
        self._out.append(f' {name}="{_escape(str(value), True)}"')

    def end(self, name: str) -> None:
        self._depth -= 1
        self._see_if_just_ended()
        if self._close_start:
            self._out.append(">")
            self._close_start = False
            if name.lower() in _EMPTY:
                self._just_ended = True
                return
        self._out.append(f"</{name}>")
        self._just_ended = True

    def write_text(self, text: str) -> None:
        self._see_if_just_ended()
        self._close_start_if_necessary()
        self._out.append(_escape(text, False))

    def raw(self, text: str) -> None:
        """``writeRawText``: unescaped, and without the indenting writer's new line."""
        self._close_start_if_necessary()
        self._out.append(text)
