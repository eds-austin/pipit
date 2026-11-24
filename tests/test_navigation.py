"""Screens, palette matching and back history."""

from __future__ import annotations

import pytest

from pipit.navigation import (
    COMMANDS,
    SCREEN_KEYS,
    SCREENS,
    Navigator,
    filter_commands,
    first_match_position,
    normalize,
)


def test_screens_have_unique_keys_and_shortcuts() -> None:
    assert len(set(SCREEN_KEYS)) == len(SCREENS)
    shortcuts = [screen.shortcut for screen in SCREENS]
    assert len(set(shortcuts)) == len(shortcuts)
    assert shortcuts[:8] == [f"Ctrl+{n}" for n in range(1, 9)]


def test_command_keys_are_unique() -> None:
    keys = [command.key for command in COMMANDS]
    assert len(set(keys)) == len(keys)


def test_normalize_drops_case_diacritics_and_apostrophes() -> None:
    assert normalize("Wilson's Phalarope") == "wilsons phalarope"
    assert normalize("Ñandú (Greater)") == "nandu greater"


@pytest.mark.parametrize(
    ("query", "text", "expected"),
    [
        ("enter", "Enter sightings", 0),
        ("ensi", "Enter sightings", 0),  # one token spanning two words
        ("en si", "Enter sightings", 0),
        ("si", "Enter sightings", 1),
        ("sightings enter", "Enter sightings", None),  # order matters
        ("enx", "Enter sightings", None),
        ("spre", "Special reports", 0),
        ("", "Anything", 0),
    ],
)
def test_first_match_position(query: str, text: str, expected: int | None) -> None:
    assert first_match_position(query, text) == expected


def test_filter_ranks_first_word_matches_first() -> None:
    titles = [command.title for command in filter_commands("s")]
    assert titles[0] == "Species"
    assert "Enter sightings" in titles
    assert titles.index("Settings") < titles.index("Enter sightings")


def test_filter_matches_keywords_after_titles() -> None:
    titles = [command.title for command in filter_commands("exit")]
    assert titles == ["Quit Pipit"]


def test_empty_query_returns_everything_in_order() -> None:
    assert filter_commands("  ") == list(COMMANDS)


def test_navigator_history() -> None:
    navigator = Navigator()
    assert navigator.current == "home"
    assert not navigator.can_go_back
    assert navigator.go("species")
    assert not navigator.go("species")  # same screen is not a history step
    assert navigator.go("reports")
    assert navigator.current_index == SCREEN_KEYS.index("reports")
    assert navigator.back()
    assert navigator.current == "species"
    assert navigator.back()
    assert navigator.current == "home"
    assert not navigator.back()


def test_navigator_history_is_bounded() -> None:
    navigator = Navigator()
    for i in range(Navigator.HISTORY_LIMIT * 2):
        navigator.go("species" if i % 2 else "trips")
    steps = 0
    while navigator.back():
        steps += 1
    assert steps == Navigator.HISTORY_LIMIT


def test_navigator_rejects_unknown_screens() -> None:
    with pytest.raises(ValueError, match="unknown screen"):
        Navigator().go("nowhere")
