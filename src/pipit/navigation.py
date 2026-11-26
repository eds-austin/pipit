"""Screens, commands and navigation history for the app shell (no Qt).

The command palette matches the way Scythebill's type-ahead does: each query token
is consumed by prefixes of one or more words, in order, so "ensi", "en si" and
"enter" all find "Enter sightings". Diacritics and case are ignored.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import cache

_WORD_SPLIT = re.compile(r"[\s\-./,]+")
_DROPPED = str.maketrans("", "", "'()\u2019")  # \u2019 = typographic apostrophe


@dataclass(frozen=True, slots=True)
class Screen:
    key: str
    title: str
    icon: str  # Lucide icon name
    shortcut: str  # Qt key sequence
    description: str


SCREENS: tuple[Screen, ...] = (
    Screen("home", "Home", "house", "Ctrl+1", "Your lists at a glance."),
    Screen("enter", "Enter sightings", "notebook-pen", "Ctrl+2", "Record a day in the field."),
    Screen("species", "Species", "bird", "Ctrl+3", "Browse sightings by species."),
    Screen("locations", "Locations", "map-pin", "Ctrl+4", "Browse places and checklists."),
    Screen("trips", "Trips", "route", "Ctrl+5", "Trips and trip reports."),
    Screen("reports", "Reports", "chart-column", "Ctrl+6", "Lists, totals and exports."),
    Screen("special", "Special reports", "sparkles", "Ctrl+7", "Timelines, maps and more."),
    Screen("taxonomies", "Taxonomies", "list-tree", "Ctrl+8", "AviList, Clements, mammals."),
    Screen("settings", "Settings", "settings", "Ctrl+,", "Preferences for Pipit."),
)
SCREEN_KEYS: tuple[str, ...] = tuple(screen.key for screen in SCREENS)


@dataclass(frozen=True, slots=True)
class Command:
    key: str  # "go.home", "app.toggle-sidebar", ...
    title: str
    category: str
    shortcut: str = ""
    keywords: tuple[str, ...] = ()


def _screen_commands() -> tuple[Command, ...]:
    return tuple(
        Command(f"go.{screen.key}", screen.title, "Go to", screen.shortcut) for screen in SCREENS
    )


COMMANDS: tuple[Command, ...] = (
    *_screen_commands(),
    Command("go.back", "Back", "Go to", "Alt+Left", ("previous",)),
    Command("app.new-entry", "New sightings entry", "Sightings", "Ctrl+N", ("add", "record")),
    Command("app.undo", "Undo", "Edit", "Ctrl+Z"),
    Command("app.redo", "Redo", "Edit", "Ctrl+Shift+Z"),
    Command("app.open-list", "Open list…", "List", "Ctrl+O", ("file",)),
    Command("app.import-scythebill", "Import Scythebill list…", "List", "", ("bsxm", "file")),
    Command(
        "app.import-ebird",
        "Import from eBird…",
        "List",
        "",
        ("ebird", "my data", "record format", "csv", "zip", "import"),
    ),
    Command("app.toggle-sidebar", "Toggle sidebar", "View", "Ctrl+B", ("collapse", "expand")),
    Command("app.keyboard", "Keyboard shortcuts", "Help", "F1", ("keys", "help")),
    Command("app.quit", "Quit Pipit", "App", "Ctrl+Q", ("exit", "close")),
)


def normalize(text: str) -> str:
    """Lowercase, strip diacritics and drop apostrophes and parentheses."""
    decomposed = unicodedata.normalize("NFKD", text.translate(_DROPPED))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def words_of(text: str) -> tuple[str, ...]:
    return tuple(word for word in _WORD_SPLIT.split(normalize(text)) if word)


def _common_prefix_length(first: str, second: str) -> int:
    length = 0
    for a, b in zip(first, second, strict=False):
        if a != b:
            break
        length += 1
    return length


def first_match_position(query: str, text: str) -> int | None:
    """Index of the first word used by a word-prefix match of ``query``, or None.

    Every query token must be consumed, in order, by prefixes of words of ``text``
    at increasing positions; one token may span several words ("ensi").
    """
    tokens = words_of(query)
    words = words_of(text)
    if not tokens:
        return 0

    @cache
    def match(token_index: int, offset: int, next_word: int) -> bool:
        if token_index == len(tokens):
            return True
        token = tokens[token_index]
        if offset == len(token):
            return match(token_index + 1, 0, next_word)
        for word_index in range(next_word, len(words)):
            longest = _common_prefix_length(token[offset:], words[word_index])
            for length in range(longest, 0, -1):
                if match(token_index, offset + length, word_index + 1):
                    return True
        return False

    for start in range(len(words)):
        token = tokens[0]
        longest = _common_prefix_length(token, words[start])
        for length in range(longest, 0, -1):
            if match(0, length, start + 1):
                return start
    return None


def filter_commands(query: str, commands: tuple[Command, ...] = COMMANDS) -> list[Command]:
    """Commands matching ``query`` by title or keyword, best first.

    Title matches that start at the first word rank first; the original order
    (navigation before actions) breaks ties. An empty query returns everything.
    """
    if not words_of(query):
        return list(commands)
    ranked: list[tuple[int, int, Command]] = []
    for order, command in enumerate(commands):
        position = first_match_position(query, command.title)
        if position is None:
            keyword_hits = [first_match_position(query, k) for k in command.keywords]
            if all(hit is None for hit in keyword_hits):
                continue
            position = len(words_of(command.title)) + 1  # keyword hits rank after titles
        ranked.append((position, order, command))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [command for _, _, command in ranked]


class Navigator:
    """Current screen plus a bounded back-history."""

    HISTORY_LIMIT = 50

    def __init__(self, start: str = "home") -> None:
        if start not in SCREEN_KEYS:
            raise ValueError(f"unknown screen {start!r}")
        self._current = start
        self._history: list[str] = []

    @property
    def current(self) -> str:
        return self._current

    @property
    def current_index(self) -> int:
        return SCREEN_KEYS.index(self._current)

    @property
    def can_go_back(self) -> bool:
        return bool(self._history)

    def go(self, key: str) -> bool:
        """Switch to ``key``; returns True if the screen changed."""
        if key not in SCREEN_KEYS:
            raise ValueError(f"unknown screen {key!r}")
        if key == self._current:
            return False
        self._history.append(self._current)
        del self._history[: -self.HISTORY_LIMIT]
        self._current = key
        return True

    def back(self) -> bool:
        if not self._history:
            return False
        self._current = self._history.pop()
        return True
