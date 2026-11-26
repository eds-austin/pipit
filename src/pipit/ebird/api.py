"""eBird's web API, used only when the user has turned it on and given their own API key
(kept in the system keyring): a checklist's place, for importing a checklist downloaded
from eBird.

Ported from Scythebill ``ui/.../imports/EBirdChecklistApi.java``, which goes through
Scythebill's own server; Pipit asks eBird directly (api.ebird.org, with the key in the
``X-eBirdApiToken`` header), the same two requests: ``product/checklist/view/{id}`` for the
state and location ID, then ``ref/hotspot/info/{location}`` for the county (a personal
location answers with nothing). Only the place is used, as in Scythebill (its breeding codes
and photo counts go unused there too).
"""

from __future__ import annotations

import contextlib
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

BASE_URL = "https://api.ebird.org/v2"
KEYRING_SERVICE = "Pipit"
KEYRING_USER = "ebird-api-key"
TIMEOUT_SECONDS = 5

#: Fetches a URL with headers; returns the body, raises ``EBirdApiError``.
Transport = Callable[[str, dict[str, str]], bytes]


class EBirdApiError(RuntimeError):
    """eBird couldn't be asked, or didn't answer usefully."""


@dataclass(slots=True)
class ChecklistPlace:
    """``ChecklistInfo``: where a checklist was, as far as eBird says."""

    country_code: str | None = None
    state_code: str | None = None
    county: str | None = None
    hotspot_id: str | None = None


def http_transport(url: str, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, headers=headers)
    if not url.startswith("https://"):
        raise EBirdApiError(f"refusing a non-https URL: {url}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body: bytes = response.read()
            return body
    except urllib.error.HTTPError as error:
        raise EBirdApiError(f"eBird answered {error.code} for {url}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise EBirdApiError(f"Could not reach eBird: {error}") from error


def _codes(text: str | None) -> tuple[str | None, str | None]:
    """ "US-CA" as ("US", "CA") (``Splitter.on('-').omitEmptyStrings()``)."""
    parts = [part for part in (text or "").split("-") if part]
    return (parts[0] if parts else None, parts[1] if len(parts) >= 2 else None)


class EBirdApi:
    def __init__(self, api_key: str, transport: Transport = http_transport,
                 base_url: str = BASE_URL) -> None:  # fmt: skip
        self._key = api_key
        self._transport = transport
        self._base = base_url

    def _get(self, path: str) -> Any:
        body = self._transport(f"{self._base}/{path}", {"X-eBirdApiToken": self._key})
        if not body.strip():
            return None  # a personal location's hotspot info is empty
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise EBirdApiError(f"eBird's answer for {path} wasn't JSON") from error

    def checklist_place(self, checklist_id: str) -> ChecklistPlace:
        """``resolveChecklist``: the state from the checklist, then (for a hotspot or a
        personal location) its county and state from the location's details, if any."""
        result = self._get(f"product/checklist/view/{checklist_id}")
        if not isinstance(result, dict):
            raise EBirdApiError(f"eBird has no checklist {checklist_id}")
        place = ChecklistPlace()
        if result.get("subnational1Code"):
            place.country_code, place.state_code = _codes(result["subnational1Code"])
        location_id = result.get("locId")
        if location_id:
            place.hotspot_id = location_id
            try:
                hotspot = self._get(f"ref/hotspot/info/{location_id}")
            except EBirdApiError:
                hotspot = None  # optional: the checklist's state is enough
            if isinstance(hotspot, dict):
                if hotspot.get("subnational2Name"):
                    place.county = hotspot["subnational2Name"]
                if hotspot.get("subnational1Code"):
                    country, state = _codes(hotspot["subnational1Code"])
                    if country is not None:
                        place.country_code = country
                        place.state_code = state
        return place


def stored_key() -> str | None:
    """The API key in the system keyring, or None (no key, or no keyring)."""
    try:
        import keyring  # noqa: PLC0415 (only when eBird is used)
        import keyring.errors  # noqa: PLC0415

        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or None
    except Exception:  # any keyring backend failure means no key
        return None


def store_key(api_key: str | None) -> None:
    """Keep (or, with None, forget) the API key in the system keyring."""
    import keyring  # noqa: PLC0415
    import keyring.errors  # noqa: PLC0415

    if api_key:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, api_key)
        return
    with contextlib.suppress(keyring.errors.PasswordDeleteError):
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
