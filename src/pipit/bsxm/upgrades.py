"""The upgrades Scythebill applies when it opens a file, and which of them Pipit can apply.

Scythebill runs, after parsing (``ReportSetLoader``, ``FrameRegistry``):

1. one-time upgraders not yet listed in the file (``OneTimeUpgradeProcessor``); each name
   is recorded whether or not it changed anything;
2. versioned upgraders newer than the file's version (``UpgraderProcessing``): location
   fixes up to 18.1.0, plus ``ReassignNewBuiltInLocations`` on every load;
3. predefined-location population (in memory only; unused ones are not saved).

Pipit ports what current files need: ``moveImageTripLinksToPhotos``. A file that still
needs any other upgrader, or the taxonomy upgrade, is refused with a message to open it
in Scythebill first. ``ReassignNewBuiltInLocations`` (replacing a user location with a
newer built-in one of the same name) needs the predefined-location tables, which Pipit
interprets later; skipping it never loses data, and Scythebill applies it on next open.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from pipit.domain.report import Link, Photo, ReportSet
from pipit.domain.values import uri_scheme

from .reader import compare_versions

#: Scythebill's one-time upgraders, in the order it runs them (UpgraderModule).
ONE_TIME_UPGRADERS = (
    "TaxonFixesForIoc101",
    "CountryNames2019",
    "CountryNames2023",
    "CountryNames2024",
    "CountryNames2025",
    "VinBreastedAmazonIoc",
    "IocCentralisAfricanGreyWoodpecker",
    "EBird2026States",
    "moveImageTripLinksToPhotos",
)
PORTED_ONE_TIME_UPGRADERS = frozenset({"moveImageTripLinksToPhotos"})
#: The newest versioned upgrader Pipit does not port (besides the always-run reassignment).
NEWEST_VERSIONED_UPGRADER = "18.1.0"


class UpgradeRefusedError(ValueError):
    """The file needs an upgrade only Scythebill can do today."""


def check_upgradable(report: ReportSet, base_taxonomy_id: str) -> None:
    open_in_scythebill = "Open and save it in Scythebill 21.x, then import it again."
    if report.taxonomy_id != base_taxonomy_id:
        raise UpgradeRefusedError(
            f"This list uses the {report.taxonomy_id} taxonomy; Pipit's data pack is "
            f"{base_taxonomy_id}. Taxonomy upgrades come in a later version. {open_in_scythebill}"
        )
    version = report.loaded_version
    if version is None or compare_versions(version, NEWEST_VERSIONED_UPGRADER) < 0:
        raise UpgradeRefusedError(
            f"This list was saved by an old Scythebill (format {version}). {open_in_scythebill}"
        )
    missing = [
        name
        for name in ONE_TIME_UPGRADERS
        if name not in report.one_time_upgrades and name not in PORTED_ONE_TIME_UPGRADERS
    ]
    if missing:
        raise UpgradeRefusedError(
            f"This list still needs Scythebill's upgrades {', '.join(missing)}. "
            f"{open_in_scythebill}"
        )


def apply_upgrades(report: ReportSet) -> list[str]:
    """Run the ported one-time upgraders the file hasn't had; returns their names."""
    applied = []
    for name in ONE_TIME_UPGRADERS:
        if name in report.one_time_upgrades:
            continue
        report.one_time_upgrades.append(name)
        if name == "moveImageTripLinksToPhotos":
            move_image_trip_links_to_photos(report)
        applied.append(name)
    return applied


# ------------------------------------------------------------------ MoveImageTripLinksToPhotos

_WEB_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".heic", ".webp", ".tif", ".tiff")
_EXCLUDED_DOMAINS = (
    "ebird.org", "instagram.com", "facebook.com", "fb.com", "dropbox.com",
    "dropboxusercontent.com", "onedrive.live.com", "1drv.ms", "wikimedia.org",
)  # fmt: skip
_SINGLE_PHOTO_PAGES = (
    ("macaulaylibrary.org", re.compile(r"/(asset|photo)/\d+(/.*)?")),
    ("cdn.download.ams.birds.cornell.edu", re.compile(r"/.*/asset/\d+(/.*)?")),
    ("inaturalist.org", re.compile(r"/photos/\d+(/.*)?")),
    ("flickr.com", re.compile(r"/photos/[^/]+/\d+(/.*)?")),
    ("flic.kr", re.compile(r"/p/[A-Za-z0-9]+/?")),
    ("photos.google.com", re.compile(r"(/share/[^/]+)?/photo/[^/]+/?")),
    ("500px.com", re.compile(r"/photo/\d+(/.*)?")),
    ("smugmug.com", re.compile(r"(/.*)?/i-[A-Za-z0-9]+(/.*)?")),
)
#: PhotoFileKind extensions (JPEG, PNG, TIFF, HEIF, RAW).
_PHOTO_FILE_EXTENSIONS = frozenset({
    "jpg", "jpeg", "jpe", "png", "tif", "tiff", "heic", "heif", "cr2", "cr3", "crw", "nef",
    "nrw", "arw", "srf", "sr2", "orf", "rw2", "raf", "dng", "pef", "srw", "3fr", "iiq", "x3f",
    "erf", "mrw",
})  # fmt: skip


def _extension(file_name: str) -> str | None:
    dot = file_name.rfind(".")
    if dot <= 0 or dot == len(file_name) - 1:
        return None
    return file_name[dot + 1 :].lower()


def _is_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def is_photo_link(link: Link) -> bool:
    """``MoveImageTripLinksToPhotos.isPhotoLink``: image files, or single-photo pages on
    known photo sites (never pages on sites like eBird or Instagram)."""
    try:
        parts = urlsplit(link.uri)
    except ValueError:
        return False
    path = parts.path
    if uri_scheme(link.uri) == "file":
        file_name = path[path.rfind("/") + 1 :]
        extension = _extension(file_name)
        return extension is not None and extension != "xmp" and extension in _PHOTO_FILE_EXTENSIONS
    host = parts.hostname
    if not host or not path:
        return False
    host = host.lower()
    if any(_is_domain(host, domain) for domain in _EXCLUDED_DOMAINS):
        return False
    if path.lower().endswith(_WEB_IMAGE_EXTENSIONS):
        return True
    return any(
        _is_domain(host, domain) and pattern.fullmatch(path)
        for domain, pattern in _SINGLE_PHOTO_PAGES
    )


def move_image_trip_links_to_photos(report: ReportSet) -> bool:
    changed = False
    for trip in report.trips:
        kept = [link for link in trip.links if not is_photo_link(link)]
        if len(kept) != len(trip.links):
            trip.photos.extend(
                Photo(link.uri, link.name) for link in trip.links if is_photo_link(link)
            )
            trip.links = kept
            changed = True
    return changed
