"""A report as a spreadsheet (.xlsx), as Scythebill's Save as spreadsheet writes it.

Ported from Scythebill's ``ui/.../io/ReportXlsOutput.java`` and ``SaveAsXlsAction.java``
(with ``ReportSpreadsheetPreferences`` for the options). The content matches Scythebill's
cell for cell: values, bold and italic, date formats, merged family rows and column widths
(checked with tools/oracle/PrintOracle.java's xlsx mode). The file itself is openpyxl's, not
Apache POI's, so it is not byte-identical.

One sheet, named after the taxonomy: a header row, then the species in taxonomic order
with family rows (a blank row before each family), or, sorted other than taxonomically, a
row per sighting (numbered for the two date sorts). Each species row has its names, and
each sighting its place, date, lifer marks, status and, optionally, notes and observers.
Totals follow after a blank row.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date as calendar_date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from pipit.domain.partial_date import PartialDate, PartialField
from pipit.output.names import (
    PlaceNames,
    resolved_common_name,
    resolved_full_name,
    resolved_status,
)
from pipit.output.print_html import (
    COMMON_FIRST,
    COMMON_ONLY,
    SCIENTIFIC_FIRST,
    SCIENTIFIC_ONLY,
    count_children,
    run_report_query,
    short_date,
)
from pipit.query.checklists import Checklists
from pipit.query.engine import EngineContext
from pipit.query.model import QSighting
from pipit.query.results import QueryResults
from pipit.query.sorting import NUMBERED_SORTS, SORT_TYPES, sorted_rows
from pipit.taxa.model import Taxon, TaxonType, parent_of_type_or_none
from pipit.taxa.sighting_taxon import Resolved, SightingTaxonType

#: ``DateFormatConverter.convert(Locale.US, DateFormat.SHORT)``
DATE_FORMAT = "[$-0409]M/d/yy;@"
#: ``ReportXlsOutput``'s name columns (and place and date) are 30 characters wide.
NAME_COLUMN_WIDTH = 30
#: Lower-case ``Messages.getText(SightingStatus)``.
_STATUS_TEXT = {"notAccepted": "not accepted", "intro": "introduced",
                "provisional": "provisional", "notEstablished": "not established",
                "bvd": "better view desired", "unsatisfactoryViews": "unsatisfactory views",
                "dead": "dead", "notByMe": "not by me", "domestic": "domestic",
                "idUncertain": "uncertain id", "signs": "signs only",
                "restrained": "restrained"}  # fmt: skip
_BOLD = Font(name="Calibri", sz=11, b=True)
_ITALIC = Font(name="Calibri", sz=11, i=True)
#: Autosized "#" column: POI measures with the font's metrics. A bold "#" is 2.07
#: characters wide, and each digit one character, plus 0.91 for padding.
_NUMBER_HEADER_WIDTH = 2.06640625
_DIGITS_PADDING = 0.9140625


@dataclass(frozen=True)
class SpreadsheetOptions:
    """``ReportSpreadsheetPreferences``, with Scythebill's defaults (other taxonomies'
    sheets are left out: Pipit has no custom taxonomies yet)."""

    include_scientific: bool = True
    show_families: bool = True
    show_status: bool = True
    show_notes: bool = False
    only_countable: bool = False
    omit_sp_and_hybrid: bool = False
    maximum_sightings: int = 1
    sort_type: str = "DEFAULT"  # species
    sort_sightings_type: str = "DEFAULT"
    user_output: str = "NONE"  # NONE, USER_NAMES, USER_ABBREVIATIONS or BOTH
    subspecies_in_separate_column: bool = False


def names_order(preference: str, options: SpreadsheetOptions) -> str:
    """``ReportXlsDialog.getScientificOrCommonFromConfiguration``."""
    if options.include_scientific:
        return COMMON_FIRST if preference == COMMON_ONLY else preference
    return COMMON_ONLY


def safe_sheet_name(name: str) -> str:
    """``WorkbookUtil.createSafeSheetName``."""
    if not name:
        return "empty"
    short = list(name[:31])
    for i, character in enumerate(short):
        if character in "\x00\x03:/\\*?[]" or (character == "'" and i in (0, len(short) - 1)):
            short[i] = " "
    return "".join(short)


def _has_common_name(resolved: Resolved) -> bool:
    return all(taxon.common_name is not None for taxon in resolved.taxa)


def _is_child_of(resolved: Resolved, parent: Taxon) -> bool:
    """``Resolved.isChildOf``: every taxon is below ``parent``."""
    for taxon in resolved.taxa:
        current = taxon.parent
        while current is not None and current is not parent:
            current = current.parent
        if current is None:
            return False
    return True


def _full_date(date: PartialDate) -> calendar_date | None:
    day, month, year = (date.get(PartialField.DAY), date.get(PartialField.MONTH),
                        date.get(PartialField.YEAR))  # fmt: skip
    if day is None or month is None or year is None:
        return None
    return calendar_date(year, month, day)


class _Sheet:
    """Cells by Scythebill's zero-based row and column numbers."""

    def __init__(self, sheet: Worksheet) -> None:
        self.sheet = sheet

    def set(self, row: int, column: int, value: str | calendar_date, font: Font | None = None,
            number_format: str | None = None) -> None:  # fmt: skip
        cell = self.sheet.cell(row=row + 1, column=column + 1, value=value)
        if font is not None:
            cell.font = font
        if number_format is not None:
            cell.number_format = number_format


@dataclass
class SpreadsheetReport:
    """``ReportXlsOutput`` as ``SaveAsXlsAction`` sets it up."""

    results: QueryResults
    places: PlaceNames
    root: str | None
    users: dict[str, tuple[str | None, str | None]]  # xml_id -> (name, abbreviation)
    options: SpreadsheetOptions
    names_order: str
    show_family_totals: bool
    subspecies_in_separate_column: bool

    def __post_init__(self) -> None:
        self._numbered = self.options.sort_type in NUMBERED_SORTS
        self._sightings_count = self.options.maximum_sightings
        self._lifers: set[Resolved] = set()
        self._group_lifers: set[Resolved] = set()
        self._subspecies_lifers: set[Resolved] = set()
        self._show_species_lifers = False
        self._show_group_lifers = False
        self._show_subspecies_lifers = False

    # ------------------------------------------------------------ the workbook

    def write(self, path: Path) -> None:
        path.write_bytes(self.xlsx())

    def xlsx(self) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        assert sheet is not None
        sheet.title = safe_sheet_name(self.results.taxonomy.name)
        self._write_taxa(_Sheet(sheet))
        buffer = io.BytesIO()
        workbook.save(buffer)
        return _bare_bold(buffer.getvalue())

    def _write_taxa(self, sheet: _Sheet) -> None:
        results = self.results
        taxa = results.taxa
        show_lifers = "lifer" in results.annotations.values()
        if show_lifers:
            self._lifers = results.taxa_with_annotation_at("lifer", TaxonType.SPECIES)
            self._show_species_lifers = bool(self._lifers)
            if results.smallest_type is not TaxonType.SPECIES:
                self._group_lifers = results.taxa_with_annotation_at("lifer", TaxonType.GROUP)
                self._show_group_lifers = len(self._group_lifers) != len(self._lifers)
                if results.smallest_type is TaxonType.SUBSPECIES:
                    self._subspecies_lifers = results.taxa_with_annotation_at(
                        "lifer", TaxonType.SUBSPECIES
                    )
                    self._show_subspecies_lifers = len(self._group_lifers) != len(
                        self._subspecies_lifers
                    )
        self._write_header(sheet)
        row = 1
        if self.options.sort_type != "DEFAULT":
            for sorted_row in sorted_rows(results, taxa, self.options.sort_type,
                                          self._sightings_count, self._omitted):  # fmt: skip
                row = self._write_taxon(sheet, row, sorted_row.taxon, [sorted_row.sighting],
                                        sorted_row.number)  # fmt: skip
        else:
            ordering = SORT_TYPES[self.options.sort_sightings_type]
            for i, taxon in enumerate(taxa):
                if self._omitted(taxon):
                    continue
                is_family = taxon.smallest_type is TaxonType.FAMILY
                if is_family and not self.options.show_families:
                    continue
                if is_family and row > 1:
                    row += 1
                if is_family:
                    sheet.set(row, 0, self._family_title(taxon, taxa[i + 1 :]), _BOLD)
                    sheet.sheet.merge_cells(start_row=row + 1, start_column=1,
                                            end_row=row + 1, end_column=2)  # fmt: skip
                    row += 1
                else:
                    sightings = []
                    if self._sightings_count > 0:
                        sightings = results.best_sightings(taxon, ordering,
                                                           self._sightings_count)  # fmt: skip
                    row = self._write_taxon(sheet, row, taxon, sightings, 0)
        self._write_totals(sheet, row + 1, show_lifers)
        self._set_widths(sheet, row)

    def _omitted(self, taxon: Resolved) -> bool:
        return self.options.omit_sp_and_hybrid and taxon.type in (
            SightingTaxonType.HYBRID,
            SightingTaxonType.SP,
        )

    # ------------------------------------------------------------ the header

    def _write_header(self, sheet: _Sheet) -> None:
        headers: list[str] = []
        if self._numbered:
            headers.append("#")
        headers.extend({COMMON_FIRST: ["Common name", "Scientific name"],
                        COMMON_ONLY: ["Common name"],
                        SCIENTIFIC_FIRST: ["Scientific name", "Common name"],
                        SCIENTIFIC_ONLY: ["Scientific name"]}[self.names_order])  # fmt: skip
        if self.subspecies_in_separate_column:
            headers.append("Subspecies")
        lifers = []
        if self._show_species_lifers:
            lifers.append("Lifer")
        if self._show_group_lifers:
            lifers.append("Group Lifer")
        if self._show_subspecies_lifers:
            lifers.append("Ssp. Lifer")
        if self._sightings_count > 0:
            headers.extend(["Location", "Date", *lifers, "Sighting"])
            if self.options.show_notes:
                headers.extend(["Notes", "Number", "Heard only", "Adult", "Immature", "Female",
                                "Male"])  # fmt: skip
            if self.options.user_output in ("USER_ABBREVIATIONS", "BOTH"):
                headers.append("Observers")
            if self.options.user_output in ("USER_NAMES", "BOTH"):
                headers.append("Observer Names")
        else:
            headers.extend(lifers)
        for column, text in enumerate(headers):
            sheet.set(0, column, text, _BOLD)

    # ------------------------------------------------------------ a taxon

    def _write_taxon(self, sheet: _Sheet, row: int, taxon: Resolved,
                     sightings: list[QSighting], number: int) -> int:  # fmt: skip
        """``writeTaxonAndSightings``: returns the next row."""
        column = 0
        if self._numbered:
            if number > 0:
                sheet.set(row, column, str(number))
            column += 1
        first, second, subspecies_name = self._names(taxon)
        sheet.set(row, column, first)
        column += 1
        if second is not None:
            sheet.set(row, column, second, _ITALIC)
            column += 1
        if self.subspecies_in_separate_column:
            if subspecies_name is not None:
                sheet.set(row, column, subspecies_name, _ITALIC)
            column += 1
        if self._sightings_count > 0:
            for i, sighting in enumerate(sightings):
                self._write_sighting(sheet, row, column, taxon, sighting)
                if i < len(sightings) - 1:
                    row += 1
        else:
            taxonomy = self.results.taxonomy
            lifers = {TaxonType.SPECIES: self._lifers, TaxonType.GROUP: self._group_lifers,
                      TaxonType.SUBSPECIES: self._subspecies_lifers}  # fmt: skip
            self._lifer_marks(sheet, row, column, lambda level: taxon.parent_of_at_least_type(
                level).resolve_internal(taxonomy) in lifers[level])  # fmt: skip
        return row + 1

    def _names(self, taxon: Resolved) -> tuple[str, str | None, str | None]:
        """The first name (with " (Endemic)" and the IUCN status), the second (if both are
        shown) and the subspecies (if in its own column)."""
        results = self.results
        name_taxon = taxon
        subspecies_name = None
        if self.subspecies_in_separate_column:
            species = _single_species_parent(taxon)
            if species is not None:
                name_taxon = species
                subspecies_name = _subspecies_name(taxon, species)
        has_common_name = _has_common_name(name_taxon)
        if not has_common_name and name_taxon.largest_type is not TaxonType.SPECIES:
            species_parent = name_taxon.parent_of_at_least_type(TaxonType.SPECIES)
            has_common_name = _has_common_name(species_parent.resolve_internal(results.taxonomy))
        order = self.names_order
        if order == COMMON_FIRST:
            first = _common_name_at_least_at_group(name_taxon) if has_common_name else ""
        elif order == COMMON_ONLY:
            first = (resolved_common_name(name_taxon) if has_common_name
                     else resolved_full_name(name_taxon))  # fmt: skip
        else:
            first = resolved_full_name(name_taxon)
        checklist = results.checklist
        if checklist is not None and checklist.status(taxon.sighting_taxon) == "ENDEMIC":
            first += " (Endemic)"
        if self.options.show_status:
            iucn = resolved_status(taxon)
            if iucn not in ("LC", "NT"):
                first += f" - {iucn}"
        second = None
        if order == COMMON_FIRST:
            second = resolved_full_name(name_taxon)
        elif order == SCIENTIFIC_FIRST:
            second = (_common_name_at_least_at_group(name_taxon)
                      if _has_common_name(name_taxon) else "")  # fmt: skip
        return first, second, subspecies_name

    def _lifer_marks(self, sheet: _Sheet, row: int, column: int,
                     is_lifer: Callable[[TaxonType], bool]) -> int:  # fmt: skip
        """ "Y" in the first lifer column (species, group, subspecies) that applies; returns
        the column after them."""
        marked = False
        for shown, level in ((self._show_species_lifers, TaxonType.SPECIES),
                             (self._show_group_lifers, TaxonType.GROUP),
                             (self._show_subspecies_lifers, TaxonType.SUBSPECIES)):  # fmt: skip
            if shown:
                if not marked and is_lifer(level):
                    sheet.set(row, column, "Y")
                    marked = True
                column += 1
        return column

    def _write_sighting(self, sheet: _Sheet, row: int, column: int, taxon: Resolved,
                        sighting: QSighting) -> None:  # fmt: skip
        results = self.results
        if sighting.location_xml_id is not None:
            sheet.set(row, column, self.places.path_name(sighting.location_xml_id, self.root))
        column += 1
        date = sighting.single_date
        if date is not None:
            full = _full_date(date)
            if full is not None:
                sheet.set(row, column, full, number_format=DATE_FORMAT)
            else:
                sheet.set(row, column, short_date(date))
        elif sighting.trip is not None:
            trip = sighting.trip
            sheet.set(row, column, f"{short_date(trip.start)}-{short_date(trip.end)}")
        column += 1
        annotate = results.annotate
        assert annotate is not None
        column = self._lifer_marks(sheet, row, column, lambda level: annotate(
            sighting, taxon.parent_of_at_least_type(level)) == "lifer")  # fmt: skip
        text = _STATUS_TEXT.get(sighting.status)
        if not self.options.show_notes and sighting.heard_only:
            text = "heard only" if text is None else f"{text} (H)"
        if text is not None:
            sheet.set(row, column, text)
            column += 1
        elif self.options.show_notes:
            column += 1
        if self.options.show_notes:
            column = self._write_notes(sheet, row, column, sighting)
        self._write_observers(sheet, row, column, sighting)

    def _write_notes(self, sheet: _Sheet, row: int, column: int, sighting: QSighting) -> int:
        """Notes, number, then "Y" for heard only, adult, immature, female and male; returns
        the male column (as Scythebill does)."""
        if sighting.description:
            sheet.set(row, column, sighting.description)
        column += 1
        if sighting.count is not None:
            sheet.set(row, column, sighting.count)
        for flag in (sighting.heard_only, sighting.adult, sighting.immature, sighting.female,
                     sighting.male):  # fmt: skip
            column += 1
            if flag:
                sheet.set(row, column, "Y")
        return column

    def _write_observers(self, sheet: _Sheet, row: int, column: int, sighting: QSighting) -> None:
        """As Scythebill does: without notes, the observer columns start one column further on
        when the sighting has a status (or was heard only), and are one early otherwise."""
        users = [self.users[u] for u in sighting.user_order if u in self.users]
        if self.options.user_output in ("USER_ABBREVIATIONS", "BOTH"):
            column += 1
            if sighting.user_order:
                sheet.set(row, column, ",".join(a for _n, a in users if a is not None))
        if self.options.user_output in ("USER_NAMES", "BOTH"):
            column += 1
            if sighting.user_order:
                sheet.set(row, column, "\n".join(n for n, _a in users if n is not None))

    # ------------------------------------------------------------ families and totals

    def _family_title(self, family_taxon: Resolved, following: list[Resolved]) -> str:
        """``getFamilyTitle``."""
        family = family_taxon.taxon
        order = self.names_order
        common = family.common_name
        if order == COMMON_FIRST:
            text = f"{common} ({family.name})" if common is not None else family.name
        elif order == SCIENTIFIC_FIRST:
            text = f"{family.name} ({common})" if common is not None else family.name
        elif order == SCIENTIFIC_ONLY:
            text = family.name
        else:
            text = common if common is not None else family.name
        if self.show_family_totals:
            species_ids: set[str] = set()
            for member in following:
                if not _is_child_of(member, family):
                    break
                if self.results.is_countable(member):
                    parent = member.parent_of_at_least_type(TaxonType.SPECIES)
                    if parent.type is SightingTaxonType.SINGLE:
                        species_ids.add(parent.ids[0])
            possible = count_children(family, TaxonType.SPECIES, self.results.checklist)
            text += f" - {len(species_ids)} / {possible}"
        return text

    def _write_totals(self, sheet: _Sheet, row: int, show_lifers: bool) -> None:
        results = self.results
        taxonomy = results.taxonomy
        column = 1 if self._numbered else 0
        lines: list[str] = []
        species_ids = results.countable_species_ids()
        families = set()
        for species_id in species_ids:
            family = parent_of_type_or_none(taxonomy.get(species_id), TaxonType.FAMILY)
            if family is not None:
                families.add(family.id)
        lines.append(f"Species: {len(species_ids):,d}")
        if results.smallest_type is not TaxonType.SPECIES:
            groups = results.countable_groups_size(False)
            if groups != len(species_ids):
                lines.append(f"Groups: {groups:,d}")
            if results.smallest_type is TaxonType.SUBSPECIES:
                subspecies = results.countable_subspecies_size(False)
                if subspecies != groups:
                    lines.append(f"Subspecies: {subspecies:,d}")
        if families:
            lines.append(f"Families: {len(families):,d}")
        if show_lifers:
            if self._lifers:
                lines.append(f"Lifers: {len(self._lifers):,d}")
            if results.smallest_type is not TaxonType.SPECIES:
                lifer_groups = len(results.taxa_with_annotation_at("lifer", TaxonType.GROUP))
                if lifer_groups != len(self._lifers):
                    lines.append(f"Lifer groups: {lifer_groups:,d}")
                if results.smallest_type is TaxonType.SUBSPECIES:
                    lifer_subspecies = len(
                        results.taxa_with_annotation_at("lifer", TaxonType.SUBSPECIES)
                    )
                    if lifer_subspecies != lifer_groups:
                        lines.append(f"Lifer subspecies: {lifer_subspecies:,d}")
        lines.append(f"Total sightings: {results.sightings_count():,d}")
        for line in lines:
            sheet.set(row, column, line, _BOLD)
            row += 1
        if results.taxa:
            sheet.set(row, column, taxonomy.name)

    def _set_widths(self, sheet: _Sheet, last_row: int) -> None:
        dimensions = sheet.sheet.column_dimensions
        if self._numbered:
            numbers = [len(str(cell.value)) for (cell,) in sheet.sheet.iter_rows(
                min_row=2, max_row=last_row, max_col=1) if cell.value is not None]  # fmt: skip
            width = max([_NUMBER_HEADER_WIDTH] + [n + _DIGITS_PADDING for n in numbers])
            dimensions["A"].width = width
            dimensions["A"].bestFit = True
        both_names = self.names_order in (COMMON_FIRST, SCIENTIFIC_FIRST)
        name_columns = (2 if both_names else 1) + (1 if self.subspecies_in_separate_column else 0)
        offset = 1 if self._numbered else 0
        for column in range(name_columns + (2 if self._sightings_count > 0 else 0)):
            dimensions[get_column_letter(column + offset + 1)].width = NAME_COLUMN_WIDTH


def _common_name_at_least_at_group(taxon: Resolved) -> str:
    """``getCommonNameAtLeastAtGroup``: a subspecies by its group's (or species') name."""
    if taxon.smallest_type is not TaxonType.SUBSPECIES:
        return resolved_common_name(taxon)
    parent = taxon.parent_of_at_least_type(TaxonType.GROUP)
    return resolved_common_name(parent.resolve_internal(taxon.taxa[0].taxonomy))


def _single_species_parent(taxon: Resolved) -> Resolved | None:
    """``getSingleSpeciesParent``: the one species of a taxon below species level."""
    if taxon.largest_type > TaxonType.GROUP:
        return None
    species = taxon.parent_of_at_least_type(TaxonType.SPECIES)
    if species.type is not SightingTaxonType.SINGLE:
        return None
    return species.resolve_internal(taxon.taxa[0].taxonomy)


def _subspecies_name(taxon: Resolved, species: Resolved) -> str:
    full = resolved_full_name(taxon)
    species_name = resolved_full_name(species)
    if full.startswith(species_name):
        return full[len(species_name) :].strip()
    return full


def _bare_bold(data: bytes) -> bytes:
    """Write bold as ``<b/>``, as Scythebill's ``SpreadsheetFonts`` does: macOS Numbers
    ignores ``<b val="1"/>``."""
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == "xl/styles.xml":
                content = content.replace(b'<b val="1"/>', b"<b/>")
            target.writestr(item, content)
    return out.getvalue()


# ------------------------------------------------------------------ SaveAsXlsAction


def report_spreadsheet(*, context: EngineContext, checklists: Checklists, query_json: str,
                       users: dict[str, tuple[str | None, str | None]],
                       options: SpreadsheetOptions, names_preference: str = COMMON_FIRST
                       ) -> SpreadsheetReport:  # fmt: skip
    """``SaveAsXlsAction.actionPerformed`` on the Reports screen's query."""
    query, results, root = run_report_query(context, checklists, query_json, users,
                                            only_countable=options.only_countable)  # fmt: skip
    has_subspecies = context.depth is not TaxonType.SPECIES
    if not users:  # a list with no observers has no observer columns
        options = replace(options, user_output="NONE")
    status_restricted = any(v.type == "SPECIES_STATUS" and not v.is_no_op
                            for v, _op in query.fields)  # fmt: skip
    return SpreadsheetReport(
        results=results, places=PlaceNames(context.query_list.places), root=root,
        users=users, options=options, names_order=names_order(names_preference, options),
        show_family_totals=not status_restricted,
        subspecies_in_separate_column=has_subspecies and options.subspecies_in_separate_column,
    )  # fmt: skip
