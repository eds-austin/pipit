"""Writing a report as a document by what each piece of text *is* (a title, a scientific name,
a site code), with each kind of document deciding how that looks.

Ported from Scythebill's ``ui/.../io/ReportDocumentWriter.java`` (the styles and calls),
``ReportPalette.java`` (colors, fonts, CSS), ``HtmlReportDocumentWriter.java`` (HTML with
inline styles, written by ``HtmlResponseWriter`` without indenting) and
``TeeToPlainTextResponseWriter.java`` (a plain-text copy collected as the HTML is written:
blocks end with a blank line, lists are numbered with tabs, tables become space-aligned
columns, links get their address in parentheses). The Word writer is in ``report_docx``.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Protocol

from pipit.output.html_writer import HtmlWriter


class BlockStyle(Enum):
    CONTENT = auto()  # a container for other blocks, with no formatting of its own
    TITLE = auto()
    SUBTITLE = auto()
    BODY = auto()  # a plain paragraph, e.g. trip notes
    SECTION_HEADING = auto()
    TRIP_HEADING = auto()
    FAMILY_HEADING = auto()
    SITE_KEY = auto()  # the key from site codes to site names
    LEGEND = auto()


class SpanStyle(Enum):
    BOLD = auto()
    ITALIC = auto()
    SCIENTIFIC_NAME = auto()  # beside a common name
    SECONDARY_NAME = auto()  # a common name beside a scientific name
    SECONDARY = auto()  # smaller, quieter text: times, and the list of sites
    SITE_CODE = auto()
    NOTE_SITE_CODE = auto()  # a site code at the start of a note
    COUNT = auto()
    NOTE = auto()
    LIFER_MARKER = auto()
    ENDEMIC_MARKER = auto()
    INTRODUCED_MARKER = auto()
    STATUS = auto()
    THREATENED_STATUS = auto()
    HEADING_ASIDE = auto()  # the part of a section heading after the heading itself
    FAMILY_SECONDARY_NAME = auto()  # the second name in a family heading
    SUB_ENTRY = auto()  # a subspecies or group line under its species


class TableStyle(Enum):
    SUMMARY = auto()  # the row of totals under the title
    ITINERARY = auto()
    SPECIES = auto()


class RowStyle(Enum):
    PLAIN = auto()
    ITINERARY_FIRST_DAY = auto()  # the first row of a day, first in its table
    ITINERARY_DAY = auto()  # the first row of a day
    ITINERARY_CONTINUATION = auto()  # a later visit on the same day
    ITINERARY_COMMENTS = auto()
    FAMILY = auto()
    SPECIES = auto()
    SPECIES_SHADED = auto()
    TOTALS = auto()
    NEW_TOTALS = auto()


class CellStyle(Enum):
    SUMMARY_NUMBER = auto()
    SUMMARY_LABEL = auto()
    ITINERARY_DATE = auto()
    ITINERARY_SITES = auto()
    ITINERARY_COUNTS = auto()
    ITINERARY_SPACER = auto()  # the empty cell under the date, beside a visit's comments
    ITINERARY_DAY_TOTALS = auto()  # a day's total time and distance, under its date
    ITINERARY_PARTS = auto()  # the parts of a stop visited, e.g. a park's trails
    ITINERARY_COMMENTS = auto()
    SPECIES_HEADER = auto()  # the header above the species names
    COLUMN_HEADER = auto()  # the header above a date or trip column
    FAMILY = auto()
    SPECIES_NAME = auto()
    LIFER_SPECIES_NAME = auto()
    DATA = auto()
    FAINT_DATA = auto()  # a plain "X" (seen, with no number), shown faintly
    TOTAL_LABEL = auto()
    TOTAL = auto()


class ReportDocumentWriter(Protocol):
    """``ReportDocumentWriter``: blocks hold spans and text; tables hold sections, rows and
    cells; lists hold items. ``line_break`` starts a new line in an item or cell."""

    def start_document(self) -> None: ...
    def end_document(self) -> None: ...
    def start_block(self, style: BlockStyle) -> None: ...
    def end_block(self) -> None: ...
    def start_span(self, style: SpanStyle) -> None: ...
    def end_span(self) -> None: ...
    def text(self, text: str) -> None: ...
    def line_break(self) -> None: ...
    def start_link(self, uri: str, title: str | None) -> None: ...
    def end_link(self) -> None: ...
    def start_table(self, style: TableStyle, column_count: int) -> None: ...
    def end_table(self) -> None: ...
    def start_table_header(self) -> None: ...
    def end_table_header(self) -> None: ...
    def start_table_body(self) -> None: ...
    def end_table_body(self) -> None: ...
    def start_table_footer(self) -> None: ...
    def end_table_footer(self) -> None: ...
    def start_row(self, style: RowStyle) -> None: ...
    def end_row(self) -> None: ...
    def start_cell(self, style: CellStyle, column_span: int) -> None: ...
    def end_cell(self) -> None: ...
    def start_numbered_list(self, start: int) -> None: ...
    def end_numbered_list(self) -> None: ...
    def start_bulleted_list(self) -> None: ...
    def end_bulleted_list(self) -> None: ...
    def start_list_item(self) -> None: ...
    def end_list_item(self) -> None: ...


# ------------------------------------------------------------------ ReportPalette

INK_COLOR = "#1d2320"
MUTED_COLOR = "#67716b"
FAINT_COLOR = "#9aa39e"
RULE_COLOR = "#dde2de"
STRONG_RULE_COLOR = "#b9c2bc"
SHADE_COLOR = "#f4f6f3"
ACCENT_COLOR = "#2c6447"
LIFER_COLOR = "#b07a12"
THREATENED_COLOR = "#a0412d"

SERIF_FONT = "Georgia"
SANS_FONT = "Calibri"
SERIF_FONTS = SERIF_FONT + ", Cambria, 'Times New Roman', serif"
SANS_FONTS = SANS_FONT + ", 'Segoe UI', Helvetica, Arial, sans-serif"
BODY_POINT_SIZE = 11

BODY_STYLE = f"font-family: {SERIF_FONTS}; color: {INK_COLOR}; font-size: {BODY_POINT_SIZE}pt"
TITLE_STYLE = (f"font-family: {SERIF_FONTS}; font-size: 22pt; font-weight: bold;"
               " margin-bottom: 2pt")  # fmt: skip
SUBTITLE_STYLE = f"font-family: {SANS_FONTS}; font-size: 11pt; color: {MUTED_COLOR}; margin-top: 0"
SECTION_HEADING_STYLE = (
    f"font-family: {SANS_FONTS}; font-size: 10pt; font-weight: bold; letter-spacing: 1pt;"
    f" text-transform: uppercase; color: {ACCENT_COLOR}; margin-top: 24pt;"
    f" margin-bottom: 8pt; padding-bottom: 3pt; border-bottom: 1.5pt solid {ACCENT_COLOR}"
)
SECTION_HEADING_ASIDE_STYLE = ("font-weight: normal; letter-spacing: 0; text-transform: none;"
                               f" color: {MUTED_COLOR}")  # fmt: skip
FAMILY_HEADING_STYLE = (
    f"font-family: {SANS_FONTS}; font-size: 8.5pt; font-weight: bold; letter-spacing: 0.8pt;"
    f" text-transform: uppercase; color: {MUTED_COLOR}; margin-top: 12pt;"
    " margin-bottom: 2pt"
)
FAMILY_SECONDARY_NAME_STYLE = ("font-weight: normal; letter-spacing: 0; text-transform: none;"
                               " font-style: italic")  # fmt: skip
SUMMARY_NUMBER_STYLE = (f"font-family: {SERIF_FONTS}; font-size: 18pt; font-weight: bold;"
                        f" padding: 6pt 18pt 0 0; border-top: 1pt solid {RULE_COLOR}")  # fmt: skip
SUMMARY_LABEL_STYLE = (
    f"font-family: {SANS_FONTS}; font-size: 8pt; font-weight: bold; letter-spacing: 0.8pt;"
    f" text-transform: uppercase; color: {MUTED_COLOR}; padding: 2pt 18pt 6pt 0;"
    f" border-bottom: 1pt solid {RULE_COLOR}"
)
CODE_STYLE = f"font-family: {SANS_FONTS}; font-size: 9pt; font-weight: bold; color: {ACCENT_COLOR}"
SECONDARY_STYLE = f"font-family: {SANS_FONTS}; font-size: 10pt; color: {MUTED_COLOR}"
SCIENTIFIC_NAME_STYLE = f"font-style: italic; color: {MUTED_COLOR}"
NOTE_STYLE = "font-style: italic"
MARKER_STYLE_FORMAT = (f"font-family: {SANS_FONTS}; font-size: 7pt; font-weight: bold;"
                       " color: %s; border: 0.75pt solid %s; padding: 0 2pt")  # fmt: skip
STATUS_TEXT_STYLE_FORMAT = (f"font-family: {SANS_FONTS}; font-size: 9.5pt; font-style: italic;"
                            " color: %s")  # fmt: skip
LIFER_MARKER_STYLE = f"color: {LIFER_COLOR}"
LINK_STYLE = f"color: {ACCENT_COLOR}"
TABLE_STYLE = f"border-collapse: collapse; font-family: {SANS_FONTS}; font-size: 9.5pt"
CELL_STYLE = f"padding: 2pt 5pt; border-bottom: 0.75pt solid {RULE_COLOR}"
ITINERARY_CONTINUATION_STYLE = "padding: 0 5pt 2pt 5pt"


# ------------------------------------------------------------------ plain text


def java_length(text: str) -> int:
    """``String.length``: UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


class PlainTextTee:
    """``TeeToPlainTextResponseWriter`` over an ``HtmlWriter``: everything written goes to
    the HTML, and a plain-text version of it is collected (``plain_text``)."""

    _UNORDERED = object()

    def __init__(self, inner: HtmlWriter) -> None:
        self.inner = inner
        self._plain: list[str] = []
        self._lists: list[object] = []  # top last: an item count, or _UNORDERED
        self._line_indent = ""
        self._table: list[list[list[str]]] | None = None
        self._last_started: str | None = None
        self._link_addresses: list[str] = []

    def plain_text(self) -> str:
        return "".join(self._plain)

    def start_document(self) -> None:
        self.inner.start_document()

    def attribute(self, name: str, value: object) -> None:
        self.inner.attribute(name, value)
        if name == "start" and self._last_started == "ol" and isinstance(self._lists[-1], int):
            self._lists[-1] = int(str(value)) - 1
        if name == "href" and self._last_started == "a":
            self._link_addresses.append(str(value))

    def write_text(self, text: str) -> None:
        self.inner.write_text(text)
        self._buffer(text)

    def start(self, name: str) -> None:
        self.inner.start(name)
        self._last_started = name
        if name == "br":
            self._new_line()
        elif name in ("ul", "ol"):
            self._lists.append(self._UNORDERED if name == "ul" else 0)
            self._update_indent()
            self._new_line()
        elif name == "li":
            top = self._lists[-1]
            if top is self._UNORDERED:
                self._buffer("\t")
            else:
                assert isinstance(top, int)
                self._lists[-1] = top + 1
                self._buffer(f"{top + 1}\t")
        elif name in ("th", "td"):
            if self._table is None or not self._table:
                raise ValueError("a cell outside a table row")
            self._table[-1].append([])
        elif name == "tr":
            if self._table is None:
                raise ValueError("a row outside a table")
            self._table.append([])
        elif name == "table":
            self._table = []

    def end(self, name: str) -> None:
        self.inner.end(name)
        if name == "a":
            if self._link_addresses:
                self._buffer(f" ({self._link_addresses.pop()})")
        elif name in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._buffer("\n\n")
        elif name in ("ul", "ol"):
            self._buffer("\n")
            self._lists.pop()
            self._update_indent()
        elif name == "li":
            self._new_line()
        elif name == "table":
            self._end_table()

    def _end_table(self) -> None:
        table = self._table
        assert table is not None
        if table:
            self._table = None
            rows = [["".join(cell) for cell in row] for row in table]
            column_count = max(len(row) for row in rows)
            if column_count > 0:
                widths = [0] * column_count
                for row in rows:
                    for i, cell in enumerate(row):
                        # A short row's last cell spans the rest, so it widens nothing
                        if len(row) < column_count and i == len(row) - 1:
                            continue
                        widths[i] = max(widths[i], java_length(cell))
                for row in rows:
                    self._new_line()
                    for i, cell in enumerate(row):
                        self._buffer(cell)
                        if i < len(row) - 1:
                            self._buffer(" " * (2 + widths[i] - java_length(cell)))
        self._buffer("\n\n")

    def _update_indent(self) -> None:
        self._line_indent = "  " * len(self._lists)

    def _new_line(self) -> None:
        self._buffer("\n")
        self._buffer(self._line_indent)

    def _buffer(self, text: str) -> None:
        if self._table and self._table[-1]:
            self._table[-1][-1].append(text)
            return
        self._plain.append(text)


# ------------------------------------------------------------------ HTML


class HtmlReportDocumentWriter:
    """``HtmlReportDocumentWriter``: simple elements with inline ``style`` attributes."""

    def __init__(self, out: PlainTextTee) -> None:
        self.out = out
        self._open: list[str] = []
        self._in_table_header = False
        self._row_style = RowStyle.PLAIN

    def start_document(self) -> None:
        self.out.start_document()
        self.out.start("html")
        self.out.start("body")
        self.out.attribute("style", BODY_STYLE)

    def end_document(self) -> None:
        self.out.end("body")
        self.out.end("html")

    def start_block(self, style: BlockStyle) -> None:
        element = {BlockStyle.CONTENT: "div", BlockStyle.TITLE: "h1",
                   BlockStyle.SECTION_HEADING: "h2", BlockStyle.TRIP_HEADING: "h3"}.get(
            style, "p")  # fmt: skip
        css = {
            BlockStyle.TITLE: TITLE_STYLE,
            BlockStyle.SUBTITLE: SUBTITLE_STYLE,
            BlockStyle.SECTION_HEADING: SECTION_HEADING_STYLE,
            BlockStyle.TRIP_HEADING: "font-size: 12pt; margin-top: 14pt; margin-bottom: 4pt",
            BlockStyle.FAMILY_HEADING: FAMILY_HEADING_STYLE,
            BlockStyle.SITE_KEY: SECONDARY_STYLE + "; margin-top: 18pt",
            BlockStyle.LEGEND: (SECONDARY_STYLE + "; margin-top: 18pt; padding-top: 6pt;"
                                f" border-top: 0.75pt solid {RULE_COLOR}"),
        }.get(style)  # fmt: skip
        self._start(element, css)

    def end_block(self) -> None:
        self.out.end(self._open.pop())

    def start_span(self, style: SpanStyle) -> None:
        spans: dict[SpanStyle, tuple[str, str | None]] = {
            SpanStyle.BOLD: ("b", None),
            SpanStyle.ITALIC: ("i", None),
            SpanStyle.SCIENTIFIC_NAME: ("i", SCIENTIFIC_NAME_STYLE),
            SpanStyle.SECONDARY_NAME: ("span", f"color: {MUTED_COLOR}"),
            SpanStyle.SECONDARY: ("span", SECONDARY_STYLE),
            SpanStyle.SITE_CODE: ("span", CODE_STYLE),
            SpanStyle.NOTE_SITE_CODE: ("span", CODE_STYLE + "; font-style: normal"),
            SpanStyle.COUNT: ("span", f"color: {INK_COLOR}"),
            SpanStyle.NOTE: ("span", NOTE_STYLE),
            SpanStyle.LIFER_MARKER: ("span", LIFER_MARKER_STYLE),
            SpanStyle.ENDEMIC_MARKER: ("span", MARKER_STYLE_FORMAT % (ACCENT_COLOR,
                                                                      ACCENT_COLOR)),
            SpanStyle.INTRODUCED_MARKER: ("span", MARKER_STYLE_FORMAT % (MUTED_COLOR,
                                                                         MUTED_COLOR)),
            SpanStyle.STATUS: ("span", STATUS_TEXT_STYLE_FORMAT % MUTED_COLOR),
            SpanStyle.THREATENED_STATUS: ("span", STATUS_TEXT_STYLE_FORMAT % THREATENED_COLOR),
            SpanStyle.HEADING_ASIDE: ("span", SECTION_HEADING_ASIDE_STYLE),
            SpanStyle.FAMILY_SECONDARY_NAME: ("span", FAMILY_SECONDARY_NAME_STYLE),
            SpanStyle.SUB_ENTRY: ("span", "margin-left: 12pt"),
        }  # fmt: skip
        element, css = spans[style]
        self._start(element, css)

    def end_span(self) -> None:
        self.out.end(self._open.pop())

    def text(self, text: str) -> None:
        self.out.write_text(text)

    def line_break(self) -> None:
        self.out.start("br")
        self.out.end("br")

    def start_link(self, uri: str, title: str | None) -> None:
        self._start("a", LINK_STYLE)
        self.out.attribute("href", uri)
        if title is not None:
            self.out.attribute("title", title)

    def end_link(self) -> None:
        self.out.end(self._open.pop())

    def start_table(self, style: TableStyle, column_count: int) -> None:
        self.out.start("table")
        self.out.attribute("cellspacing", 0)
        self.out.attribute("style", {
            TableStyle.SUMMARY: "border-collapse: collapse; margin-top: 12pt",
            TableStyle.ITINERARY: "border-collapse: collapse; width: 100%",
            TableStyle.SPECIES: TABLE_STYLE,
        }[style])  # fmt: skip

    def end_table(self) -> None:
        self.out.end("table")

    def start_table_header(self) -> None:
        self.out.start("thead")
        self._in_table_header = True

    def end_table_header(self) -> None:
        self.out.end("thead")
        self._in_table_header = False

    def start_table_body(self) -> None:
        self.out.start("tbody")

    def end_table_body(self) -> None:
        self.out.end("tbody")

    def start_table_footer(self) -> None:
        self.out.start("tfoot")

    def end_table_footer(self) -> None:
        self.out.end("tfoot")

    def start_row(self, style: RowStyle) -> None:
        self.out.start("tr")
        self._row_style = style

    def end_row(self) -> None:
        self.out.end("tr")

    def start_cell(self, style: CellStyle, column_span: int) -> None:
        element = "th" if self._in_table_header else "td"
        self.out.start(element)
        self._open.append(element)
        if column_span > 1:
            self.out.attribute("colspan", column_span)
        self.out.attribute("style", self._cell_style(style))

    def _cell_style(self, style: CellStyle) -> str:
        row = self._row_style
        if row is RowStyle.ITINERARY_FIRST_DAY:
            itinerary = "padding: 4pt 5pt 2pt 5pt; vertical-align: top"
        elif row is RowStyle.ITINERARY_DAY:
            itinerary = (f"padding: 4pt 5pt 2pt 5pt; border-top: 0.75pt solid {RULE_COLOR};"
                         " vertical-align: top")  # fmt: skip
        else:
            itinerary = ITINERARY_CONTINUATION_STYLE + "; vertical-align: top"
        species_row = CELL_STYLE + (f"; background-color: {SHADE_COLOR}"
                                    if row is RowStyle.SPECIES_SHADED else "")  # fmt: skip
        totals = "padding: 2pt 5pt; " + (
            f"color: {MUTED_COLOR}" if row is RowStyle.NEW_TOTALS
            else f"font-weight: bold; border-top: 1.5pt solid {STRONG_RULE_COLOR}"
        )  # fmt: skip
        header = ("padding: 2pt 5pt; vertical-align: bottom; border-bottom: 1.5pt solid "
                  + STRONG_RULE_COLOR)  # fmt: skip
        return {
            CellStyle.SUMMARY_NUMBER: SUMMARY_NUMBER_STYLE,
            CellStyle.SUMMARY_LABEL: SUMMARY_LABEL_STYLE,
            CellStyle.ITINERARY_DATE: (itinerary + "; white-space: nowrap; font-family: "
                                       + SANS_FONTS + "; font-weight: bold"),
            CellStyle.ITINERARY_SITES: itinerary,
            CellStyle.ITINERARY_COUNTS: (itinerary + "; white-space: nowrap; text-align: right; "
                                         + SECONDARY_STYLE),
            CellStyle.ITINERARY_SPACER: ITINERARY_CONTINUATION_STYLE,
            CellStyle.ITINERARY_DAY_TOTALS: (ITINERARY_CONTINUATION_STYLE
                                             + "; vertical-align: top; white-space: nowrap; "
                                             + SECONDARY_STYLE),
            CellStyle.ITINERARY_COMMENTS: ITINERARY_CONTINUATION_STYLE + "; " + NOTE_STYLE,
            CellStyle.ITINERARY_PARTS: ITINERARY_CONTINUATION_STYLE + "; " + SECONDARY_STYLE,
            CellStyle.SPECIES_HEADER: header + "; text-align: left",
            CellStyle.COLUMN_HEADER: header + "; text-align: center; width: 40pt",
            CellStyle.FAMILY: ("padding: 8pt 5pt 2pt 5pt; font-size: 8pt; font-weight: bold;"
                               " letter-spacing: 0.8pt; text-transform: uppercase; color: "
                               + ACCENT_COLOR + "; border-bottom: 0.75pt solid "
                               + STRONG_RULE_COLOR),
            CellStyle.SPECIES_NAME: species_row + "; text-align: left; font-weight: normal",
            CellStyle.LIFER_SPECIES_NAME: species_row + "; text-align: left; font-weight: bold",
            CellStyle.DATA: species_row + "; text-align: center",
            CellStyle.FAINT_DATA: species_row + f"; text-align: center; color: {FAINT_COLOR}",
            CellStyle.TOTAL_LABEL: totals,
            CellStyle.TOTAL: totals + "; text-align: center",
        }[style]  # fmt: skip

    def end_cell(self) -> None:
        self.out.end(self._open.pop())

    def start_numbered_list(self, start: int) -> None:
        self.out.start("ol")
        self.out.attribute("start", start)
        self.out.attribute("style", "margin-top: 0; margin-bottom: 0")

    def end_numbered_list(self) -> None:
        self.out.end("ol")

    def start_bulleted_list(self) -> None:
        self.out.start("ul")
        self.out.attribute("style", "margin-top: 0; margin-bottom: 0")

    def end_bulleted_list(self) -> None:
        self.out.end("ul")

    def start_list_item(self) -> None:
        self.out.start("li")
        self.out.attribute("style", "margin-bottom: 3pt")

    def end_list_item(self) -> None:
        self.out.end("li")

    def _start(self, element: str, css: str | None) -> None:
        self.out.start(element)
        self._open.append(element)
        if css is not None:
            self.out.attribute("style", css)
