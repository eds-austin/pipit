"""App-wide settings, stored in ``settings.toml`` in the config directory.

Per-list preferences live in the list database, not here. Unknown keys are ignored
and missing keys take their defaults, so the file survives upgrades both ways.
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

from pipit.config import paths
from pipit.config.tomlw import dumps

MIN_UI_SCALE = 0.9
MAX_UI_SCALE = 1.6


@dataclass(frozen=True, slots=True)
class AppSettings:
    ui_scale: float = 1.15  # 1.15 gives 15px body text (Scythebill's text is too small)
    sidebar_collapsed: bool = False
    last_list: str = ""
    display_taxonomy: str = "avilist"  # "avilist" or "clements"
    # Print (Scythebill's ReportPrintPreferences, with its defaults)
    print_include_scientific: bool = True
    print_show_families: bool = True
    print_show_status: bool = True
    print_maximum_sightings: int = 1
    print_sort_type: str = "DEFAULT"
    print_sort_sightings_type: str = "DEFAULT"
    print_compact: bool = False
    print_only_countable: bool = False
    print_omit_sp_and_hybrid: bool = False
    # Save as spreadsheet (Scythebill's ReportSpreadsheetPreferences, with its defaults)
    xlsx_include_scientific: bool = True
    xlsx_show_families: bool = True
    xlsx_show_status: bool = True
    xlsx_show_notes: bool = False
    xlsx_only_countable: bool = False
    xlsx_omit_sp_and_hybrid: bool = False
    xlsx_maximum_sightings: int = 1
    xlsx_sort_type: str = "DEFAULT"
    xlsx_sort_sightings_type: str = "DEFAULT"
    xlsx_user_output: str = "NONE"
    xlsx_subspecies_in_separate_column: bool = False
    # Trip reports (Scythebill's TripReportPreferences, with its defaults)
    trip_include_scientific: bool = True
    trip_itinerary: bool = True
    trip_species_table: bool = True
    trip_species_list: bool = True
    trip_show_status: bool = True
    trip_lifers_in_bold: bool = True
    #: "km", "mi", or "auto": miles in the US and UK, as Scythebill's VisitInfoPreferences
    distance_unit: str = "auto"
    #: Scythebill CSV with spaces for line breaks (Scythebill's import preference)
    csv_excel_compatible: bool = False
    #: Ask eBird's web service (with the user's API key, in the system keyring) where a
    #: downloaded checklist was. Off until the user turns it on: no network otherwise.
    ebird_online: bool = False

    def validated(self) -> AppSettings:
        """Clamp or replace invalid values (hand-edited files)."""
        return replace(
            self,
            ui_scale=min(MAX_UI_SCALE, max(MIN_UI_SCALE, self.ui_scale)),
            display_taxonomy=self.display_taxonomy
            if self.display_taxonomy in ("avilist", "clements")
            else "avilist",
            print_maximum_sightings=min(100, max(0, self.print_maximum_sightings)),
            print_sort_type=_sort(self.print_sort_type),
            print_sort_sightings_type=_sort(self.print_sort_sightings_type),
            xlsx_maximum_sightings=min(100, max(0, self.xlsx_maximum_sightings)),
            xlsx_sort_type=_sort(self.xlsx_sort_type),
            xlsx_sort_sightings_type=_sort(self.xlsx_sort_sightings_type),
            distance_unit=self.distance_unit if self.distance_unit in ("km", "mi") else "auto",
            xlsx_user_output=self.xlsx_user_output
            if self.xlsx_user_output in USER_OUTPUTS
            else "NONE",
        )


SORT_TYPES = ("DEFAULT", "BY_DATE", "BY_DATE_DESCENDING", "BY_DAY_OF_YEAR",
              "BY_DAY_OF_YEAR_DESCENDING", "BY_SIGHTING_COUNT")  # fmt: skip


#: ``UserOutput``: which observer columns a spreadsheet has.
USER_OUTPUTS = ("NONE", "USER_NAMES", "USER_ABBREVIATIONS", "BOTH")


def _sort(value: str) -> str:
    return value if value in SORT_TYPES else "DEFAULT"


def settings_path() -> Path:
    return paths.config_dir() / "settings.toml"


def _coerce(default: Any, value: Any) -> Any | None:
    """``value`` if it has the default's type (ints accepted for floats), else None."""
    if isinstance(default, bool):
        return value if isinstance(value, bool) else None
    if isinstance(default, float):
        is_number = isinstance(value, int | float) and not isinstance(value, bool)
        return float(value) if is_number else None
    if isinstance(default, int):
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    if isinstance(default, str):
        return value if isinstance(value, str) else None
    return None


def load_settings(path: Path | None = None) -> AppSettings:
    path = path or settings_path()
    if not path.exists():
        return AppSettings()
    try:
        with path.open("rb") as file:
            data: dict[str, Any] = tomllib.load(file).get("settings", {})
    except (OSError, tomllib.TOMLDecodeError):
        return AppSettings()
    defaults = AppSettings()
    values: dict[str, Any] = {}
    for field in fields(AppSettings):
        if field.name in data:
            coerced = _coerce(getattr(defaults, field.name), data[field.name])
            if coerced is not None:
                values[field.name] = coerced
    return AppSettings(**values).validated()


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    """Write atomically: a crash mid-write leaves the previous file intact."""
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        "# Pipit settings (written by the app).\n\n" + dumps({"settings": asdict(settings)}),
        encoding="utf-8",
    )
    temporary.replace(path)
