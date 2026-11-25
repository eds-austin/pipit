"""Stored queries ("saved reports") kept in the list's preferences, as Scythebill keeps them.

The list's preferences are one JSON object (Gson, pretty-printed), keyed by preference
class. Stored queries are ``StoredReportSetQueriesPreferences.storedQueries``: a string
holding a compact JSON array of ``{"name", "json", "type"}``.

- ``read`` is ``StoredQueries.restoreFromPreferences``: a missing type is REPORTS unless
  the JSON starts ``COUNTRY/``, ``STATE/`` or ``COUNTY/`` (early total-ticks queries); an
  unknown type is REPORTS too; each query's JSON is canonicalized (a legacy top-level
  "type" pushed down to each field's "bool").
- ``write`` is ``StoredQueries.updatePreferences`` then ``ReportPreferencesManager.save``:
  the array (name, json, type) replaces only ``storedQueries``, in place; everything else
  in the preferences is written back as Gson writes what it parsed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pipit.domain import gson

PREFERENCES_CLASS = "com.scythebill.birdlist.ui.panels.reports.StoredReportSetQueriesPreferences"
REPORTS = "REPORTS"
TOTAL_TICKS = "TOTAL_TICKS"
TYPES = (REPORTS, TOTAL_TICKS)
_BOOLEAN_OPERATIONS = ("ALL", "ANY", "NEVER", "NEVER_ALL")
_EARLY_TICKS = ("COUNTRY/", "STATE/", "COUNTY/")


@dataclass(frozen=True, slots=True)
class StoredQuery:
    name: str
    #: The persisted query: the query JSON, or for total ticks "COUNTRY/" + JSON.
    persisted: str
    type: str = REPORTS

    @property
    def query_json(self) -> str:
        """``StoredQuery.queryJson``: the query part alone."""
        if self.type == TOTAL_TICKS:
            slash = self.persisted.find("/")
            if slash < 0:
                raise ValueError(f"no ticks type in {self.persisted!r}")
            return self.persisted[slash + 1 :]
        return self.persisted

    @property
    def ticks_type(self) -> str | None:
        if self.type != TOTAL_TICKS:
            return None
        slash = self.persisted.find("/")
        return self.persisted[:slash] if slash >= 0 else None


def make(name: str, persisted: str, query_type: str = REPORTS) -> StoredQuery:
    """``new StoredQuery(name, json, type)``: the persisted query canonicalized."""
    return StoredQuery(name, canonicalize(persisted, query_type), query_type)


def canonicalize(persisted: str, query_type: str) -> str:
    """``canonicalizePersistedQuery``."""
    if query_type == TOTAL_TICKS:
        slash = persisted.find("/")
        if slash < 0:
            return persisted
        return persisted[:slash] + "/" + canonicalize_query_json(persisted[slash + 1 :])
    if query_type == REPORTS:
        return canonicalize_query_json(persisted)
    return persisted


def canonicalize_query_json(text: str) -> str:
    """``canonicalizeQueryJson``: anything malformed is left alone."""
    try:
        query = gson.parse(text)
    except ValueError:
        return text
    if not isinstance(query, dict):
        return text
    legacy = None
    if "type" in query:
        legacy = _string(query["type"])
        if legacy not in _BOOLEAN_OPERATIONS:
            return text
    if "fields" not in query:
        return text
    fields = query["fields"]
    if not isinstance(fields, list):
        return text
    canonical = []
    for field in fields:
        if not isinstance(field, dict):
            return text
        operation = legacy
        if "bool" in field:
            operation = _string(field["bool"])
            if operation not in _BOOLEAN_OPERATIONS:
                return text
        if "type" not in field:
            return text  # Java: a NullPointerException, caught by restore's caller
        canonical.append({"type": _string(field["type"]), "value": field.get("value"),
                          "bool": operation or "ALL"})  # fmt: skip
    return gson.dumps({"fields": canonical})


def _string(value: Any) -> str:
    """``JsonElement.getAsString`` for a primitive."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return str(value)
    raise ValueError(f"not a string: {value!r}")


def read(preferences_json: str | None) -> list[StoredQuery]:
    """The list's stored queries, in order (``restoreFromPreferences``); none if unreadable."""
    stored = _stored_text(preferences_json)
    if not stored:
        return []
    try:
        array = gson.parse(stored)
    except ValueError:
        return []
    queries: list[StoredQuery] = []
    for item in array:
        name = _string(item["name"])
        persisted = _string(item["json"])
        query_type = REPORTS
        if "type" in item:
            if _string(item["type"]) in TYPES:
                query_type = _string(item["type"])
        elif persisted.startswith(_EARLY_TICKS):
            query_type = TOTAL_TICKS
        queries.append(make(name, persisted, query_type))
    return queries


def _stored_text(preferences_json: str | None) -> str | None:
    if not preferences_json:
        return None
    try:
        preferences = json.loads(preferences_json)
    except ValueError:
        return None
    if not isinstance(preferences, dict):
        return None
    own = preferences.get(PREFERENCES_CLASS)
    if not isinstance(own, dict):
        return None
    text = own.get("storedQueries")
    return text if isinstance(text, str) else None


def write(preferences_json: str | None, queries: list[StoredQuery]) -> str:
    """The preferences with these stored queries (``updatePreferences`` and ``save``)."""
    preferences: dict[str, Any] = {}
    if preferences_json:
        try:
            parsed = gson.parse(preferences_json)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            preferences = parsed
    array = [{"name": query.name, "json": query.persisted, "type": query.type}
             for query in queries]  # fmt: skip
    own = preferences.get(PREFERENCES_CLASS)
    if not isinstance(own, dict):
        own = {}
    own["storedQueries"] = gson.dumps(array)
    preferences[PREFERENCES_CLASS] = own
    return gson.dumps(preferences, pretty=True)


# ------------------------------------------------------------ edits (StoredQueries' own)


def add(queries: list[StoredQuery], name: str, persisted: str,
        query_type: str = REPORTS) -> list[StoredQuery]:  # fmt: skip
    """``addQuery``: a query of the same name is replaced in place; otherwise appended."""
    new = make(name, persisted, query_type)
    result = list(queries)
    for i, query in enumerate(result):
        if query.name == name:
            result[i] = new
            return result
    result.append(new)
    return result


def remove(queries: list[StoredQuery], name: str) -> list[StoredQuery]:
    """``removeQuery``: queries are equal by name, and ``List.remove`` drops the first."""
    result = list(queries)
    for i, query in enumerate(result):
        if query.name == name:
            del result[i]
            break
    return result


def rename(queries: list[StoredQuery], name: str, new_name: str) -> list[StoredQuery]:
    """``renameQuery``: same place, same query."""
    result = list(queries)
    for i, query in enumerate(result):
        if query.name == name:
            result[i] = make(new_name, query.persisted, query.type)
            break
    return result


def move(queries: list[StoredQuery], from_index: int, to_index: int) -> list[StoredQuery]:
    """``moveQuery``."""
    size = len(queries)
    if not (0 <= from_index < size and 0 <= to_index < size) or from_index == to_index:
        return list(queries)
    result = list(queries)
    result.insert(to_index, result.pop(from_index))
    return result
