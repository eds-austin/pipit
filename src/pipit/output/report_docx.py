"""A report as a Word (.docx) document, formatted to match the HTML version.

Ported from Scythebill's ``ui/.../io/DocxReportDocumentWriter.java``, which writes through
Apache POI's XWPF. Pipit writes the same package parts itself, and ``word/document.xml``
exactly as POI serializes it: run properties in the order they're set, other properties in
schema order, attributes in the order POI sets them. So the document is byte-identical to
Scythebill's apart from the package's metadata (creator, time).

Measurements are in twips (1/20 point); border widths in eighths of a point.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime

from pipit.output.report_document import (
    ACCENT_COLOR,
    FAINT_COLOR,
    INK_COLOR,
    LIFER_COLOR,
    MUTED_COLOR,
    RULE_COLOR,
    SANS_FONT,
    SERIF_FONT,
    SHADE_COLOR,
    STRONG_RULE_COLOR,
    THREATENED_COLOR,
    BlockStyle,
    CellStyle,
    RowStyle,
    SpanStyle,
    TableStyle,
)

#: Countries that use US Letter paper; everywhere else gets A4.
LETTER_PAPER_COUNTRIES = frozenset({"US", "CA", "MX", "PR", "PH", "CL", "CO", "VE"})
LETTER_WIDTH = 12240
LETTER_HEIGHT = 15840
A4_WIDTH = 11906
A4_HEIGHT = 16838
PAGE_MARGIN = 1080
#: The narrowest a species-table date column can be with its heading written across it.
COMFORTABLE_DATA_WIDTH = 700
#: The height of a row of column headings run up their columns.
ROTATED_HEADING_HEIGHT = 1200
#: The width the species table leaves for species names, when there are many dates.
NAME_WIDTH = 2600
#: Space for an entry's number in the species list, before its text.
LIST_NUMBER_INDENT = 500
SUB_ENTRY_INDENT = "\u2003"  # an em space stands in for a subspecies line's indent
MARKER_PADDING = "\u2009"  # a thin space inside the box around a checklist marker

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
_SETTINGS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings"

#: Children in schema order (XMLBeans inserts these by the schema); elements not listed
#: keep their children in the order added (run and row properties, which are choices).
_SCHEMA_ORDER = {
    "w:pPr": ("w:keepNext", "w:keepLines", "w:pBdr", "w:tabs", "w:spacing", "w:ind", "w:jc",
              "w:sectPr"),
    "w:pBdr": ("w:top", "w:bottom"),
    "w:tcPr": ("w:tcW", "w:gridSpan", "w:tcBorders", "w:shd", "w:noWrap", "w:tcMar",
               "w:textDirection", "w:vAlign"),
    "w:tcBorders": ("w:top", "w:bottom"),
    "w:tblPr": ("w:tblW", "w:tblLayout", "w:tblCellMar"),
    "w:tbl": ("w:tblPr", "w:tblGrid", "w:tr"),
    "w:tr": ("w:trPr", "w:tc"),
    "w:tc": ("w:tcPr", "w:p"),
    "w:p": ("w:pPr",),
    "w:r": ("w:rPr",),
    "w:sectPr": ("w:pgSz", "w:pgMar"),
}  # fmt: skip


def java_is_whitespace(char: str) -> bool:
    """``Character.isWhitespace``: Unicode spaces except the no-break ones, and controls
    U+0009-U+000D and U+001C-U+001F."""
    code = ord(char)
    if 0x09 <= code <= 0x0D or 0x1C <= code <= 0x1F:
        return True
    if code in (0x00A0, 0x2007, 0x202F):
        return False
    return char in " \u1680\u2028\u2029\u205f\u3000" or 0x2000 <= code <= 0x200A


def _escape(text: str, attribute: bool = False) -> str:
    """As XMLBeans writes text: ``&`` and ``<`` escaped, ``>`` only in ``]]>``."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace("]]>", "]]&gt;")
    if attribute:
        text = text.replace('"', "&quot;")
    return text


class _Element:
    """An XML element as XMLBeans keeps it: attributes in the order set, children in schema
    order or the order added."""

    __slots__ = ("attributes", "children", "tag", "text")

    def __init__(self, tag: str, **attributes: str | int) -> None:
        self.tag = tag
        self.attributes: dict[str, str] = {}
        self.children: list[_Element] = []
        self.text: str | None = None
        for name, value in attributes.items():
            self.set(name, value)

    def set(self, name: str, value: str | int) -> _Element:
        self.attributes[name.replace("__", ":")] = str(value)
        return self

    def add(self, child: _Element) -> _Element:
        if self.tag == "w:body" and self.children and self.children[-1].tag == "w:sectPr":
            # The body's content goes in the order written, before its final section
            self.children.insert(len(self.children) - 1, child)
            return child
        order = _SCHEMA_ORDER.get(self.tag)
        if order is None or child.tag not in order:
            self.children.append(child)
            return child
        rank = order.index(child.tag)
        index = len(self.children)
        while index > 0:
            previous = self.children[index - 1].tag
            if previous in order and order.index(previous) <= rank:
                break
            index -= 1
        self.children.insert(index, child)
        return child

    def get_or_add(self, tag: str) -> _Element:
        for child in self.children:
            if child.tag == tag:
                return child
        return self.add(_Element(tag))

    def find(self, tag: str) -> _Element | None:
        return next((child for child in self.children if child.tag == tag), None)

    def write(self, out: list[str]) -> None:
        out.append("<" + self.tag)
        for name, value in self.attributes.items():
            out.append(f' {name}="{_escape(value, attribute=True)}"')
        if not self.children and self.text is None:
            out.append("/>")
            return
        out.append(">")
        if self.text is not None:
            out.append(_escape(self.text))
        for child in self.children:
            child.write(out)
        out.append(f"</{self.tag}>")


@dataclass
class _RunFormat:
    """How a run of text looks; each span adjusts a copy of its parent's."""

    font: str = SERIF_FONT
    size: float = 11
    bold: bool = False
    italic: bool = False
    color: str = INK_COLOR
    caps: bool = False
    character_spacing: int = 0
    border_color: str | None = None  # a box around the text, in this color

    def sans(self, size: float) -> None:
        self.font = SANS_FONT
        self.size = size

    def label(self, size: float, color: str, spacing: int) -> None:
        """Small, bold, spaced-out capitals, for headings and labels."""
        self.sans(size)
        self.bold = True
        self.caps = True
        self.color = color
        self.character_spacing = spacing

    def plain_case(self) -> None:
        self.bold = False
        self.caps = False
        self.character_spacing = 0


def _hex(css_color: str) -> str:
    return css_color[1:]


def _half_points(size: float) -> str:
    return str(round(size * 2))


class DocxReportDocumentWriter:
    """``DocxReportDocumentWriter``."""

    def __init__(self, *, letter_paper: bool = True) -> None:
        self.page_width = LETTER_WIDTH if letter_paper else A4_WIDTH
        self.page_height = LETTER_HEIGHT if letter_paper else A4_HEIGHT
        self.text_width = self.page_width - 2 * PAGE_MARGIN
        self._body = _Element("w:body")
        self._body.add(self._section(landscape=False))
        self._links: list[str] = []
        self._blocks: list[BlockStyle] = []
        self._spans: list[SpanStyle] = []
        self.title = ""
        self._paragraph: _Element | None = None
        self._last_was_table = False
        self._table_style: TableStyle | None = None
        self._table: _Element | None = None
        self._column_count = 0
        self._widths: list[int] | None = None
        self._in_header = False
        self._landscape_table = False
        self._narrow_data = False
        self._row: _Element | None = None
        self._row_style = RowStyle.PLAIN
        self._column = 0
        self._cell: _Element | None = None
        self._cell_style: CellStyle | None = None
        self._link: str | None = None
        self._in_list_item = False
        self._next_number = 0
        self._bulleted = False
        self.data = b""

    # ------------------------------------------------------------ the package

    def _section(self, *, landscape: bool) -> _Element:
        section = _Element("w:sectPr")
        width, height = self.page_width, self.page_height
        size = section.add(_Element("w:pgSz", w__w=height if landscape else width,
                                    w__h=width if landscape else height))  # fmt: skip
        if landscape:
            size.set("w:orient", "landscape")
        section.add(_Element("w:pgMar", w__top=PAGE_MARGIN, w__bottom=PAGE_MARGIN,
                             w__left=PAGE_MARGIN, w__right=PAGE_MARGIN, w__header=720,
                             w__footer=720, w__gutter=0))  # fmt: skip
        return section

    def document_xml(self) -> bytes:
        out = ['<?xml version="1.0" encoding="UTF-8"?>\n']
        out.append(f'<w:document xmlns:w="{_W}"')
        if self._links:
            out.append(f' xmlns:r="{_R}"')
        out.append(">")
        self._body.write(out)
        out.append("</w:document>")
        return "".join(out).encode("utf-8")

    def _package(self, created: datetime) -> bytes:
        relationships = [f'<Relationship Id="rId1" Target="settings.xml" Type="{_SETTINGS}"/>']
        relationships += [
            f'<Relationship Id="rId{i}" Target="{_escape(uri, attribute=True)}" '
            f'TargetMode="External" Type="{_HYPERLINK}"/>'
            for i, uri in enumerate(self._links, 2)
        ]
        header = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        title = f"<dc:title>{_escape(self.title)}</dc:title>" if self.title else ""
        parts = {
            "[Content_Types].xml": header + _CONTENT_TYPES,
            "_rels/.rels": header + _ROOT_RELATIONSHIPS,
            "docProps/app.xml": ('<?xml version="1.0" encoding="UTF-8"?>\n<Properties xmlns="'
                                 'http://schemas.openxmlformats.org/officeDocument/2006/'
                                 'extended-properties"><Application>Pipit</Application>'
                                 "</Properties>"),
            "docProps/core.xml": (
                header + _CORE_START
                + f'<dcterms:created xsi:type="dcterms:W3CDTF">'
                f"{created.strftime('%Y-%m-%dT%H:%M:%SZ')}</dcterms:created>"
                + "<dc:creator>Pipit</dc:creator>" + title + "</cp:coreProperties>"
            ),
            "word/_rels/document.xml.rels": (
                header + '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
                '2006/relationships">' + "".join(relationships) + "</Relationships>"
            ),
            "word/settings.xml": ('<?xml version="1.0" encoding="UTF-8"?>\n'
                                  f'<w:settings xmlns:w="{_W}"/>'),
        }  # fmt: skip
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in ("[Content_Types].xml", "_rels/.rels", "docProps/app.xml",
                         "docProps/core.xml"):  # fmt: skip
                archive.writestr(name, parts[name])
            archive.writestr("word/document.xml", self.document_xml())
            for name in ("word/_rels/document.xml.rels", "word/settings.xml"):
                archive.writestr(name, parts[name])
        return buffer.getvalue()

    # ------------------------------------------------------------ the document

    def start_document(self) -> None:
        pass

    def end_document(self) -> None:
        self.data = self._package(datetime.now(UTC))

    def start_block(self, style: BlockStyle) -> None:
        self._blocks.append(style)
        if style is BlockStyle.CONTENT:
            return
        paragraph = self._paragraph = self._new_paragraph()
        if style is BlockStyle.TITLE:
            _spacing(paragraph, 0, 40)
        elif style is BlockStyle.SUBTITLE:
            _spacing(paragraph, 0, 120)
        elif style is BlockStyle.BODY:
            _spacing(paragraph, 0, 160)
        elif style is BlockStyle.SECTION_HEADING:
            _spacing(paragraph, 480, 160)
            _keep_next(paragraph, True)
            _paragraph_border(paragraph, top=False, eighths=12, color=ACCENT_COLOR, space=3)
        elif style is BlockStyle.TRIP_HEADING:
            _spacing(paragraph, 280, 80)
            _keep_next(paragraph, True)
        elif style is BlockStyle.FAMILY_HEADING:
            _spacing(paragraph, 240, 40)
            _keep_next(paragraph, True)
        elif style is BlockStyle.SITE_KEY:
            _spacing(paragraph, 360, 0)
        elif style is BlockStyle.LEGEND:
            _spacing(paragraph, 360, 0)
            _paragraph_border(paragraph, top=True, eighths=6, color=RULE_COLOR, space=6)

    def end_block(self) -> None:
        if self._blocks.pop() is not BlockStyle.CONTENT:
            self._paragraph = None

    def start_span(self, style: SpanStyle) -> None:
        self._spans.append(style)
        if style is SpanStyle.SUB_ENTRY:
            self.text(SUB_ENTRY_INDENT)

    def end_span(self) -> None:
        self._spans.pop()

    def text(self, text: str) -> None:
        if not text:
            return
        if self._paragraph is None:
            self._paragraph = self._new_paragraph()
        if self._current_block() is BlockStyle.TITLE:
            self.title += text
        format_ = self._current_format()
        if format_.border_color is not None:
            text = MARKER_PADDING + text + MARKER_PADDING
        for i, line in enumerate(text.split("\n")):
            if self._link is None:
                run = self._paragraph.add(_Element("w:r"))
            else:
                self._links.append(self._link)
                link = self._paragraph.add(_Element("w:hyperlink"))
                link.set("r:id", f"rId{len(self._links) + 1}")
                run = link.add(_Element("w:r"))
            properties = _apply_format(run, format_)
            if self._link is not None:
                properties.get_or_add("w:color").set("w:val", _hex(ACCENT_COLOR))
                properties.add(_Element("w:u", w__val="single"))
            if i > 0:
                run.add(_Element("w:br"))
            _set_text(run, line)

    def line_break(self) -> None:
        if self._paragraph is None:
            self._paragraph = self._new_paragraph()
        self._paragraph.add(_Element("w:r")).add(_Element("w:br"))

    def start_link(self, uri: str, title: str | None) -> None:
        self._link = uri

    def end_link(self) -> None:
        self._link = None

    # ------------------------------------------------------------ tables

    def start_table(self, style: TableStyle, column_count: int) -> None:
        if self._last_was_table:
            _spacing(self._new_paragraph(), 0, 0)
        # Pages keeps a heading with the whole table after it; better a heading orphaned
        # at the foot of a page
        content = self._body_content()
        if content and content[-1].tag == "w:p":
            _keep_next(content[-1], False)
        self._table_style = style
        self._column_count = column_count
        self._widths = None
        table = self._table = self._body.add(_Element("w:tbl"))
        properties = table.add(_Element("w:tblPr"))
        properties.add(_Element("w:tblW", w__w=0, w__type="auto"))
        margins = properties.add(_Element("w:tblCellMar"))
        for side, twips in (("top", 40), ("left", 100), ("bottom", 40), ("right", 100)):
            margins.add(_Element(f"w:{side}", w__type="dxa", w__w=twips))
        properties.add(_Element("w:tblLayout", w__type="fixed"))
        table.add(_Element("w:tblGrid"))
        self._paragraph = None

    def _lay_out_columns(self, first_span: int) -> None:
        count = self._column_count
        widths = [0] * count
        if self._table_style is TableStyle.SUMMARY:
            widths = [min(1700, self.text_width // count)] * count
        elif self._table_style is TableStyle.ITINERARY:
            if count == 3:
                widths = [2300, self.text_width - 2300 - 2100, 2100]
            else:
                widths = [self.text_width // count] * count
        else:
            names = min(first_span, count)
            data = count - names
            width = self.text_width
            if _data_width(width, names, data) < COMFORTABLE_DATA_WIDTH:
                self._start_landscape_section()  # too many dates: turn the page on its side
                width = self.page_height - 2 * PAGE_MARGIN
            data_width = _data_width(width, names, data)
            self._narrow_data = data_width < COMFORTABLE_DATA_WIDTH
            name_width = max(1440, _java_divide(width - data_width * data, names))
            widths = [name_width if i < names else data_width for i in range(count)]
        self._widths = widths
        assert self._table is not None
        grid = self._table.get_or_add("w:tblGrid")
        grid.children = [_Element("w:gridCol", w__w=width) for width in widths]
        table_width = self._table.get_or_add("w:tblPr").get_or_add("w:tblW")
        table_width.set("w:type", "dxa")
        table_width.set("w:w", sum(widths))

    def _start_landscape_section(self) -> None:
        """Ends the section before the table (and its heading) with an upright section
        break, so the table gets landscape pages of its own."""
        assert self._table is not None
        children = self._body.children
        index = children.index(self._table)
        previous = children[index - 1] if index > 0 else None
        at = index - 1 if previous is not None and previous.tag == "w:p" else index
        section_break = _Element("w:p")
        children.insert(at, section_break)
        _spacing(section_break, 0, 0)
        section_break.get_or_add("w:pPr").add(self._section(landscape=False))
        self._landscape_table = True

    def end_table(self) -> None:
        if self._landscape_table:
            section_break = self._new_paragraph()
            _spacing(section_break, 0, 0)
            section_break.get_or_add("w:pPr").add(self._section(landscape=True))
            self._landscape_table = False
        self._narrow_data = False
        self._table = None
        self._table_style = None
        self._row = None
        self._last_was_table = self._body_content()[-1].tag == "w:tbl"

    def start_table_header(self) -> None:
        self._in_header = True

    def end_table_header(self) -> None:
        self._in_header = False

    def start_table_body(self) -> None:
        pass

    def end_table_body(self) -> None:
        pass

    def start_table_footer(self) -> None:
        pass

    def end_table_footer(self) -> None:
        pass

    def start_row(self, style: RowStyle) -> None:
        assert self._table is not None
        row = self._row = self._table.add(_Element("w:tr"))
        properties = row.add(_Element("w:trPr"))
        properties.add(_Element("w:cantSplit", w__val="on"))
        if self._in_header:
            properties.add(_Element("w:tblHeader", w__val="on"))
        self._row_style = style
        self._column = 0

    def end_row(self) -> None:
        self._row = None

    def start_cell(self, style: CellStyle, column_span: int) -> None:
        if self._widths is None:
            self._lay_out_columns(column_span if style is CellStyle.SPECIES_HEADER else 1)
        assert self._row is not None and self._widths is not None
        cell = self._cell = self._row.add(_Element("w:tc"))
        self._cell_style = style
        paragraph = self._paragraph = cell.add(_Element("w:p"))
        _spacing(paragraph, 0, 0)
        properties = cell.add(_Element("w:tcPr"))
        end = min(self._column + column_span, len(self._widths))
        width = sum(self._widths[self._column : end])
        self._column += column_span
        properties.add(_Element("w:tcW", w__type="dxa", w__w=width))
        if column_span > 1:
            properties.add(_Element("w:gridSpan", w__val=column_span))
        self._format_cell(style, properties, paragraph)

    def _format_cell(self, style: CellStyle, properties: _Element, paragraph: _Element) -> None:
        if style in (CellStyle.SUMMARY_NUMBER, CellStyle.SUMMARY_LABEL):
            number = style is CellStyle.SUMMARY_NUMBER
            _cell_margins(properties, 120 if number else 40, 0, 0 if number else 120, 360)
            _cell_border(properties, top=number, eighths=8, color=RULE_COLOR)
        elif style.name.startswith("ITINERARY_"):
            self._format_itinerary_cell(style, properties, paragraph)
        elif style in (CellStyle.SPECIES_HEADER, CellStyle.COLUMN_HEADER):
            self._format_header_cell(style, properties, paragraph)
        elif style is CellStyle.FAMILY:
            _cell_margins(properties, 160, 100, 40, 100)
            _cell_border(properties, top=False, eighths=6, color=STRONG_RULE_COLOR)
            _keep_next(paragraph, True)  # keep a family's name with its first species
        elif style in (CellStyle.SPECIES_NAME, CellStyle.LIFER_SPECIES_NAME, CellStyle.DATA,
                       CellStyle.FAINT_DATA):  # fmt: skip
            _cell_border(properties, top=False, eighths=6, color=RULE_COLOR)
            if self._row_style is RowStyle.SPECIES_SHADED:
                properties.add(_Element("w:shd", w__color="auto", w__val="clear",
                                        w__fill=_hex(SHADE_COLOR)))  # fmt: skip
            if style in (CellStyle.DATA, CellStyle.FAINT_DATA):
                self._format_data_cell(properties, paragraph)
        elif style in (CellStyle.TOTAL_LABEL, CellStyle.TOTAL):
            if self._row_style is RowStyle.TOTALS:
                _cell_border(properties, top=True, eighths=12, color=STRONG_RULE_COLOR)
            if style is CellStyle.TOTAL:
                self._format_data_cell(properties, paragraph)

    def _format_itinerary_cell(self, style: CellStyle, properties: _Element,
                               paragraph: _Element) -> None:  # fmt: skip
        row_style = self._row_style
        if style in (CellStyle.ITINERARY_DATE, CellStyle.ITINERARY_SITES,
                     CellStyle.ITINERARY_COUNTS):  # fmt: skip
            properties.add(_Element("w:vAlign", w__val="top"))
            day = row_style in (RowStyle.ITINERARY_FIRST_DAY, RowStyle.ITINERARY_DAY)
            _cell_margins(properties, 80 if day else 0, 100, 40, 100)
            if row_style is RowStyle.ITINERARY_DAY:
                _cell_border(properties, top=True, eighths=6, color=RULE_COLOR)
            if style is not CellStyle.ITINERARY_SITES:
                properties.add(_Element("w:noWrap"))
            if style is CellStyle.ITINERARY_COUNTS:
                _align(paragraph, "right")
        elif style is CellStyle.ITINERARY_DAY_TOTALS:
            _cell_margins(properties, 0, 100, 40, 100)
            properties.add(_Element("w:vAlign", w__val="top"))
            properties.add(_Element("w:noWrap"))
        else:  # spacer, parts, comments
            _cell_margins(properties, 0, 100, 40, 100)

    def _format_header_cell(self, style: CellStyle, properties: _Element,
                            paragraph: _Element) -> None:  # fmt: skip
        properties.add(_Element("w:vAlign", w__val="bottom"))
        _cell_border(properties, top=False, eighths=12, color=STRONG_RULE_COLOR)
        if style is not CellStyle.COLUMN_HEADER:
            return
        if not self._narrow_data:
            _align(paragraph, "center")
            return
        # Run the heading up the column, as there's no room for it across
        properties.add(_Element("w:textDirection", w__val="btLr"))
        properties.add(_Element("w:noWrap"))
        assert self._row is not None
        height = self._row.get_or_add("w:trPr").get_or_add("w:trHeight")
        height.set("w:val", ROTATED_HEADING_HEIGHT)
        height.set("w:hRule", "atLeast")
        # POI adds a second vAlign rather than changing the first
        properties.add(_Element("w:vAlign", w__val="center"))
        _cell_margins(properties, 60, 20, 60, 20)

    def _format_data_cell(self, properties: _Element, paragraph: _Element) -> None:
        _align(paragraph, "center")
        if self._narrow_data:
            _cell_margins(properties, 40, 20, 40, 20)

    def end_cell(self) -> None:
        self._cell = None
        self._cell_style = None
        self._paragraph = None

    # ------------------------------------------------------------ lists

    def start_numbered_list(self, start: int) -> None:
        self._next_number = start
        self._bulleted = False

    def end_numbered_list(self) -> None:
        pass

    def start_bulleted_list(self) -> None:
        self._bulleted = True

    def end_bulleted_list(self) -> None:
        self._bulleted = False

    def start_list_item(self) -> None:
        """A paragraph with its number written out and a hanging indent, not a Word list, so
        the numbering runs on across families."""
        self._in_list_item = True
        paragraph = self._paragraph = self._new_paragraph()
        _spacing(paragraph, 0, 60)
        properties = paragraph.get_or_add("w:pPr")
        properties.add(_Element("w:ind", w__left=LIST_NUMBER_INDENT,
                                w__hanging=LIST_NUMBER_INDENT))  # fmt: skip
        properties.add(_Element("w:keepLines"))
        tabs = properties.add(_Element("w:tabs"))
        tabs.add(_Element("w:tab", w__val="left", w__pos=LIST_NUMBER_INDENT))
        if self._bulleted:
            self.text("•\t")
        else:
            self.text(f"{self._next_number}.\t")
            self._next_number += 1

    def end_list_item(self) -> None:
        self._in_list_item = False
        self._paragraph = None

    # ------------------------------------------------------------ formats

    def _body_content(self) -> list[_Element]:
        """``getBodyElements``: paragraphs and tables, not the final section."""
        return [child for child in self._body.children if child.tag != "w:sectPr"]

    def _new_paragraph(self) -> _Element:
        self._last_was_table = False
        if self._cell is not None:
            return self._cell.add(_Element("w:p"))
        return self._body.add(_Element("w:p"))

    def _current_block(self) -> BlockStyle | None:
        for style in reversed(self._blocks):
            if style is not BlockStyle.CONTENT:
                return style
        return None

    def _current_format(self) -> _RunFormat:
        format_ = _RunFormat()
        if self._cell_style is not None:
            self._apply_cell_style(format_)
        elif not self._in_list_item:
            block = self._current_block()
            if block is not None:
                _apply_block_style(format_, block)
        for span in self._spans:
            _apply_span_style(format_, span)
        return format_

    def _apply_cell_style(self, format_: _RunFormat) -> None:
        if self._table_style is TableStyle.SPECIES:
            format_.sans(9.5)
        style = self._cell_style
        if style is CellStyle.SUMMARY_NUMBER:
            format_.size = 18
            format_.bold = True
        elif style is CellStyle.SUMMARY_LABEL:
            format_.label(8, MUTED_COLOR, 16)
        elif style is CellStyle.ITINERARY_DATE:
            format_.font = SANS_FONT
            format_.bold = True
        elif style in (CellStyle.ITINERARY_COUNTS, CellStyle.ITINERARY_PARTS,
                       CellStyle.ITINERARY_DAY_TOTALS):  # fmt: skip
            format_.sans(10)
            format_.color = MUTED_COLOR
        elif style is CellStyle.ITINERARY_COMMENTS:
            format_.italic = True
        elif style in (CellStyle.SPECIES_HEADER, CellStyle.COLUMN_HEADER,
                       CellStyle.LIFER_SPECIES_NAME):  # fmt: skip
            format_.bold = True
        elif style is CellStyle.FAMILY:
            format_.label(8, ACCENT_COLOR, 16)
        elif style is CellStyle.FAINT_DATA:
            format_.color = FAINT_COLOR
        elif style in (CellStyle.TOTAL_LABEL, CellStyle.TOTAL):
            if self._row_style is RowStyle.NEW_TOTALS:
                format_.color = MUTED_COLOR
            else:
                format_.bold = True


def _apply_block_style(format_: _RunFormat, style: BlockStyle) -> None:
    if style is BlockStyle.TITLE:
        format_.size = 22
        format_.bold = True
    elif style is BlockStyle.SUBTITLE:
        format_.sans(11)
        format_.color = MUTED_COLOR
    elif style is BlockStyle.SECTION_HEADING:
        format_.label(10, ACCENT_COLOR, 20)
    elif style is BlockStyle.TRIP_HEADING:
        format_.size = 12
        format_.bold = True
    elif style is BlockStyle.FAMILY_HEADING:
        format_.label(8.5, MUTED_COLOR, 16)
    elif style in (BlockStyle.SITE_KEY, BlockStyle.LEGEND):
        format_.sans(10)
        format_.color = MUTED_COLOR


def _apply_span_style(format_: _RunFormat, style: SpanStyle) -> None:
    if style is SpanStyle.BOLD:
        format_.bold = True
    elif style in (SpanStyle.ITALIC, SpanStyle.NOTE):
        format_.italic = True
    elif style is SpanStyle.SCIENTIFIC_NAME:
        format_.italic = True
        format_.color = MUTED_COLOR
    elif style is SpanStyle.SECONDARY_NAME:
        format_.color = MUTED_COLOR
    elif style is SpanStyle.SECONDARY:
        format_.sans(10)
        format_.color = MUTED_COLOR
    elif style in (SpanStyle.SITE_CODE, SpanStyle.NOTE_SITE_CODE):
        format_.sans(9)
        format_.bold = True
        format_.color = ACCENT_COLOR
        if style is SpanStyle.NOTE_SITE_CODE:
            format_.italic = False
    elif style is SpanStyle.COUNT:
        format_.color = INK_COLOR
    elif style is SpanStyle.LIFER_MARKER:
        format_.color = LIFER_COLOR
    elif style in (SpanStyle.ENDEMIC_MARKER, SpanStyle.INTRODUCED_MARKER):
        format_.sans(7)
        format_.bold = True
        format_.color = ACCENT_COLOR if style is SpanStyle.ENDEMIC_MARKER else MUTED_COLOR
        format_.border_color = format_.color
    elif style in (SpanStyle.STATUS, SpanStyle.THREATENED_STATUS):
        format_.sans(9.5)
        format_.italic = True
        format_.color = THREATENED_COLOR if style is SpanStyle.THREATENED_STATUS else MUTED_COLOR
    elif style is SpanStyle.HEADING_ASIDE:
        format_.plain_case()
        format_.color = MUTED_COLOR
    elif style is SpanStyle.FAMILY_SECONDARY_NAME:
        format_.plain_case()
        format_.italic = True


def _apply_format(run: _Element, format_: _RunFormat) -> _Element:
    properties = run.add(_Element("w:rPr"))
    properties.add(_Element("w:rFonts", w__ascii=format_.font, w__hAnsi=format_.font,
                            w__cs=format_.font, w__eastAsia=format_.font))  # fmt: skip
    properties.add(_Element("w:sz", w__val=_half_points(format_.size)))
    properties.add(_Element("w:color", w__val=_hex(format_.color)))
    if format_.bold:
        properties.add(_Element("w:b", w__val="on"))
    if format_.italic:
        properties.add(_Element("w:i", w__val="on"))
    if format_.caps:
        properties.add(_Element("w:caps", w__val="on"))
    if format_.character_spacing:
        properties.add(_Element("w:spacing", w__val=format_.character_spacing))
    if format_.border_color is not None:
        properties.add(_Element("w:bdr", w__val="single", w__sz=6, w__space=0,
                                w__color=_hex(format_.border_color)))  # fmt: skip
    return properties


def _set_text(run: _Element, text: str) -> None:
    element = run.add(_Element("w:t"))
    element.text = text
    if text and (java_is_whitespace(text[0]) or java_is_whitespace(text[-1])):
        element.set("xml:space", "preserve")


def _spacing(paragraph: _Element, before: int, after: int) -> None:
    spacing = paragraph.get_or_add("w:pPr").get_or_add("w:spacing")
    spacing.set("w:before", before)
    spacing.set("w:after", after)


def _keep_next(paragraph: _Element, keep: bool) -> None:
    paragraph.get_or_add("w:pPr").get_or_add("w:keepNext").set("w:val", "on" if keep else "off")


def _align(paragraph: _Element, alignment: str) -> None:
    paragraph.get_or_add("w:pPr").get_or_add("w:jc").set("w:val", alignment)


def _paragraph_border(paragraph: _Element, *, top: bool, eighths: int, color: str,
                      space: int) -> None:  # fmt: skip
    borders = paragraph.get_or_add("w:pPr").get_or_add("w:pBdr")
    borders.add(_border("w:top" if top else "w:bottom", eighths, color, space))


def _cell_border(properties: _Element, *, top: bool, eighths: int, color: str) -> None:
    borders = properties.get_or_add("w:tcBorders")
    borders.add(_border("w:top" if top else "w:bottom", eighths, color, 0))


def _border(tag: str, eighths: int, color: str, space: int) -> _Element:
    return _Element(tag, w__val="single", w__sz=eighths, w__space=space, w__color=_hex(color))


def _cell_margins(properties: _Element, top: int, left: int, bottom: int, right: int) -> None:
    margins = properties.add(_Element("w:tcMar"))
    for side, twips in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        margins.add(_Element(f"w:{side}", w__type="dxa", w__w=twips))


def _java_divide(dividend: int, divisor: int) -> int:
    """Java's ``/`` on ints: rounds toward zero."""
    quotient = abs(dividend) // abs(divisor)
    return quotient if (dividend >= 0) == (divisor > 0) else -quotient


def _data_width(table_width: int, name_columns: int, data_columns: int) -> int:
    if data_columns == 0:
        return 0
    width = _java_divide(table_width - NAME_WIDTH * name_columns, data_columns)
    return max(300, min(800, width))


_CONTENT_TYPES = (
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default ContentType="application/vnd.openxmlformats-package.relationships+xml" '
    'Extension="rels"/><Default ContentType="application/xml" Extension="xml"/>'
    '<Override ContentType="application/vnd.openxmlformats-officedocument.extended-'
    'properties+xml" PartName="/docProps/app.xml"/><Override ContentType="application/'
    'vnd.openxmlformats-package.core-properties+xml" PartName="/docProps/core.xml"/>'
    '<Override ContentType="application/vnd.openxmlformats-officedocument.'
    'wordprocessingml.document.main+xml" PartName="/word/document.xml"/><Override '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.'
    'settings+xml" PartName="/word/settings.xml"/></Types>'
)
_ROOT_RELATIONSHIPS = (
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Target="word/document.xml" Type="http://schemas.'
    'openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>'
    '<Relationship Id="rId2" Target="docProps/app.xml" Type="http://schemas.'
    'openxmlformats.org/officeDocument/2006/relationships/extended-properties"/>'
    '<Relationship Id="rId3" Target="docProps/core.xml" Type="http://schemas.'
    'openxmlformats.org/package/2006/relationships/metadata/core-properties"/>'
    "</Relationships>"
)
_CORE_START = (
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/'
    'core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://'
    'purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
)
