"""Where each input lives in a Scythebill checkout, and its content hash.

Paths follow the 2026 layout (after Scythebill's Kotlin Multiplatform move). Upgrade
mapping files are discovered from their registration in ``ApplicationModule.java``, so a
new year's files are picked up without changing this module.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_MODEL_RESOURCES = Path("model/src/main/resources/com/scythebill/birdlist/model")
_DATA_FILES = Path("data/src/commonMain/composeResources/files")
_APP_RESOURCES = Path("app/src/main/resources")
_IMPORT_RESOURCES = Path("ui/src/main/resources/com/scythebill/birdlist/ui/imports")
_APPLICATION_MODULE = Path("app/src/main/java/com/scythebill/birdlist/app/ApplicationModule.java")
_MAPPING_LOADER = re.compile(
    r'new\s+TaxonomyMappingLoader\(\s*"(?P<taxonomy>[^"]+)"\s*,'
    r'\s*Resources\.asCharSource\(\s*Resources\.getResource\(\s*"(?P<main>[^"]+)"\s*\)'
    r'(?:[^;]*?Resources\.getResource\(\s*"(?P<ssp>[^"]+)"\s*\))?[^;]*;',
    re.DOTALL,
)


class SourceError(FileNotFoundError):
    pass


@dataclass(frozen=True, slots=True)
class UpgradeSource:
    """Old taxonomy ID and the files mapping it to the current base taxonomy."""

    from_taxonomy: str
    main: Path
    subspecies: Path | None


@dataclass(frozen=True, slots=True)
class ScythebillSources:
    root: Path

    @property
    def base_taxonomy(self) -> Path:
        return self.root / _DATA_FILES / "taxon.xml"

    @property
    def avilist_taxonomy(self) -> Path:
        return self.root / "model/src/main/resources/avilist-taxon.xml"

    @property
    def multilingual_dir(self) -> Path:
        return self.root / _DATA_FILES / "multilingual"

    @property
    def i18n_dir(self) -> Path:
        return self.root / _DATA_FILES / "i18n"

    def checklist_dir(self, flavor: str) -> Path:
        """``clements`` or ``avilist``."""
        return self.root / _MODEL_RESOURCES / "checklist" / flavor

    def transpose_file(self, flavor: str) -> Path:
        return self.root / _MODEL_RESOURCES / "checklist" / f"{flavor}.transpose"

    @property
    def locations_dir(self) -> Path:
        return self.root / _MODEL_RESOURCES / "sighting"

    @property
    def imports_dir(self) -> Path:
        """Tables Scythebill's importers read (place aliases, translated country names)."""
        return self.root / _IMPORT_RESOURCES

    @property
    def split_reports(self) -> list[Path]:
        """The splits-and-lumps reports' tables (``report-<version>.csv``)."""
        return sorted((self.root / _APP_RESOURCES).glob("report-*.csv"))

    @property
    def mapdata_dir(self) -> Path:
        return self.root / _MODEL_RESOURCES / "mapdata"

    def upgrade_sources(self) -> list[UpgradeSource]:
        module = (self.root / _APPLICATION_MODULE).read_text(encoding="utf-8")
        found = []
        for match in _MAPPING_LOADER.finditer(module):
            ssp = match.group("ssp")
            found.append(
                UpgradeSource(
                    match.group("taxonomy"),
                    self.root / _APP_RESOURCES / match.group("main"),
                    self.root / _APP_RESOURCES / ssp if ssp else None,
                )
            )
        if not found:
            raise SourceError(f"no TaxonomyMappingLoader registrations in {_APPLICATION_MODULE}")
        return found

    def required_files(self) -> list[Path]:
        files = [
            self.base_taxonomy,
            self.avilist_taxonomy,
            self.transpose_file("clements"),
            self.transpose_file("avilist"),
            self.root / _APPLICATION_MODULE,
        ]
        for source in self.upgrade_sources():
            files.append(source.main)
            if source.subspecies is not None:
                files.append(source.subspecies)
        return files

    def check(self) -> None:
        missing = [str(path) for path in self.required_files() if not path.is_file()]
        for directory in (
            self.multilingual_dir,
            self.i18n_dir,
            self.checklist_dir("clements"),
            self.checklist_dir("avilist"),
            self.locations_dir,
            self.imports_dir,
            self.mapdata_dir,
        ):
            if not directory.is_dir():
                missing.append(str(directory))
        if missing:
            raise SourceError("missing Scythebill sources:\n  " + "\n  ".join(missing))

    def git_revision(self) -> str:
        """The checkout's commit, with "-dirty" if tracked files changed; "" if unknown."""
        try:
            head = subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True, timeout=30,
            ).stdout.strip()  # fmt: skip
            dirty = subprocess.run(
                ["git", "-C", str(self.root), "status", "--porcelain", "--untracked-files=no"],
                capture_output=True, text=True, check=True, timeout=60,
            ).stdout.strip()  # fmt: skip
        except (OSError, subprocess.SubprocessError):
            return ""
        return head + ("-dirty" if dirty else "")


def sha256_of(root: Path, paths: list[Path]) -> str:
    """One hash over files: each path relative to ``root``, then its contents."""
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()
