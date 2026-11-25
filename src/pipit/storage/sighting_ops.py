"""Changing one sighting from the browse screens (each call runs inside the caller's
``ListDatabase.action``, so it is one undo step).

The details are Scythebill's ``SightingInfo``: count (an ``ApproximateNumber`` such as "12"
or "~20"; empty means present), the six flags, status, breeding code and notes. Its place,
date and taxon change through Enter sightings (editing the visit), as in Scythebill.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pipit.domain.report import BREEDING_CODES, SIGHTING_STATUSES
from pipit.domain.values import ApproximateNumber

FLAGS = ("heard_only", "male", "female", "adult", "immature", "photographed")


class SightingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SightingDetails:
    count: str = ""
    heard_only: bool = False
    male: bool = False
    female: bool = False
    adult: bool = False
    immature: bool = False
    photographed: bool = False
    status: str = "none"
    breeding: str = ""
    notes: str = ""


def read_details(connection: sqlite3.Connection, sighting_id: int) -> SightingDetails:
    found = connection.execute(
        "SELECT count, heard_only, male, female, adult, immature, photographed, status, "
        "breeding, description FROM sightings WHERE id = ?",
        (sighting_id,),
    ).fetchone()
    if found is None:
        raise SightingError("That sighting no longer exists.")
    count, heard_only, male, female, adult, immature, photographed, status, breeding, notes = found
    return SightingDetails(
        count=count or "", heard_only=bool(heard_only), male=bool(male), female=bool(female),
        adult=bool(adult), immature=bool(immature), photographed=bool(photographed),
        status=status, breeding=breeding, notes=notes or "",
    )  # fmt: skip


def update_details(
    connection: sqlite3.Connection, sighting_id: int, details: SightingDetails
) -> None:
    text = details.count.strip()
    count = None
    if text and text.lower() != "x":
        parsed = ApproximateNumber.parse(text)
        if parsed is None:
            raise SightingError(f"“{text}” isn't a count (try 12, ~20 or >100).")
        count = str(parsed)
    if details.status not in SIGHTING_STATUSES:
        raise SightingError(f"Unknown status {details.status}.")
    if details.breeding not in BREEDING_CODES:
        raise SightingError(f"Unknown breeding code {details.breeding}.")
    cursor = connection.execute(
        "UPDATE sightings SET count = ?, heard_only = ?, male = ?, female = ?, adult = ?, "
        "immature = ?, photographed = ?, status = ?, breeding = ?, description = ? "
        "WHERE id = ?",
        (count, *(int(getattr(details, flag)) for flag in FLAGS), details.status,
         details.breeding, details.notes.rstrip() or None, sighting_id),
    )  # fmt: skip
    if cursor.rowcount == 0:
        raise SightingError("That sighting no longer exists.")


def delete_sighting(connection: sqlite3.Connection, sighting_id: int) -> None:
    """Its sp. parts, observers and photos go with it (foreign keys cascade)."""
    cursor = connection.execute("DELETE FROM sightings WHERE id = ?", (sighting_id,))
    if cursor.rowcount == 0:
        raise SightingError("That sighting no longer exists.")
