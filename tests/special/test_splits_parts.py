"""Parts of splits and lumps the oracle fixtures don't reach: a bundle that may be a lump or
a split, the fewest species unresolved sp.'s stand for, and the report's sentences."""

from __future__ import annotations

from typing import Any

import pytest

from pipit.special.splits_lumps import (
    OldSpecies,
    SingleResult,
    SplitsAndLumps,
    _Bundle,
    _BundleResult,
    _minimum_hitting_set,
    describe,
    totals,
)


def _bundle_result(current: list[str], known: list[str], possible: list[str]) -> _BundleResult:
    bundle = _Bundle(old_common={name: name.upper() for name in known + possible})
    return _BundleResult(bundle, dict.fromkeys(current), dict.fromkeys(known),
                         dict.fromkeys(possible))  # fmt: skip


def test_lump_or_split() -> None:
    """One current species from two known old names and two possible ones: one lump, or a
    split, depending on which old names the sightings were."""
    found = SplitsAndLumps()
    found.add_bundle(_bundle_result(["spA"], ["Aa b", "Aa c"], ["Aa d", "Aa e"]))
    assert len(found.possible_lump_or_split) == 1
    assert (found.possible_lump_count, found.possible_split_count) == (1, 1)


def test_only_possible_old_names() -> None:
    """With no known old name, one of the possible ones must be: one possible is known."""
    found = SplitsAndLumps()
    found.add_bundle(_bundle_result(["spA", "spB"], [], ["Aa b"]))
    assert [r.old for r in found.splits] == [[OldSpecies("Aa b", "AA B")]]
    assert found.known_split_count == 1


def test_minimum_hitting_set() -> None:
    sets = [frozenset({"a", "b"}), frozenset({"b", "c"}), frozenset({"d"})]
    assert _minimum_hitting_set(sets, set()) == 2  # b and d
    assert _minimum_hitting_set([], set()) == 0


def test_totals() -> None:
    found = SplitsAndLumps(known_split_count=3, possible_lump_count=2,
                           unresolved_sp_minimum=1, unresolved_sp_maximum=4)  # fmt: skip
    assert totals(found) == ("Gained: 3 · Lost: 0 (+2 possible) · 1–4 possible in "
                             "unresolved “sp.” records")  # fmt: skip


@pytest.mark.scythebill
def test_sentences(pack: Any) -> None:
    clements, _avilist = pack.load_base_and_avilist()
    split = SingleResult(["spOxyurjam", "spOxyurfer"], [OldSpecies("Oxyura jamaicensis",
                                                                   "Ruddy Duck")], [])  # fmt: skip
    text = describe(split, clements)
    assert text.startswith("<b>Ruddy Duck</b> (<i>O. jamaicensis</i>) is now <b>Ruddy Duck</b>"
                           " (<i>Oxyura jamaicensis</i>) and <b>")  # fmt: skip
    possible = SingleResult(["spOxyurjam"], [], [OldSpecies("Oxyura a", "A"),
                                                OldSpecies("Oxyura b", "B")])  # fmt: skip
    assert describe(possible, clements).startswith("Some or all of <b>A</b> (<i>O. a</i>) and "
                                                   "<b>B</b> (<i>O. b</i>) are now")  # fmt: skip
    unresolved = SingleResult(["spOxyurjam"], [OldSpecies("Oxyura x", "X")], [],
                              unresolved_sp=True)  # fmt: skip
    assert describe(unresolved, clements).endswith("but you only have an unresolved “sp.” "
                                                   "record for it.")  # fmt: skip
