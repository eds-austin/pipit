"""Type-ahead search: Scythebill's normalization, splitting and matching rules."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from reference_indexer import ReferenceIndexer

from pipit.search.indexer import Indexer, bits_of
from pipit.search.normalize import drop_characters, normalize, split_words
from pipit.search.word_separator import MAX_LENGTH_TO_SPLIT, boundaries


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ñandú", "nandu"),
        ("ÀÉÎÕÜ", "aeiou"),
        ("Łódź", "lodz"),
        ("ð", "o"),  # Scythebill's table quirk: eth maps to "o"
        ("æß", "æß"),  # not decomposed
        ("İ", "i"),  # Java lowercases dotted capital I to plain i
        ("ı", "i"),
        ("Șș", "ss"),
        ("ə", "e"),
        ("ΔΣ", "ΔΣ"),  # above U+017F nothing is lowercased
        ("Wilson's", "wilson's"),
    ],
)
def test_normalize_matches_scythebill(text: str, expected: str) -> None:
    assert normalize(text) == expected


def test_word_splitting_uses_ascii_whitespace_only() -> None:
    assert split_words("he gu-ab.cd,ef/gh") == ["he", "gu", "ab", "cd", "ef", "gh"]
    assert split_words("a b") == ["a b"]  # Java's \s does not match NBSP
    assert split_words("  ") == []
    assert drop_characters("Wilson's (Gray)") == "Wilsons Gray"


def test_boundaries_match_scythebill_documentation() -> None:
    # WordSeparator.kt: getBoundaries(3, 3) = {3}, {2, 3}, {1, 3}, {1, 2, 3}
    assert boundaries(3, 3) == ((3,), (2, 3), (1, 3), (1, 2, 3))
    assert boundaries(0) == ()
    assert all(split[-1] == MAX_LENGTH_TO_SPLIT for split in boundaries(20))
    assert all(len(split) <= 5 for split in boundaries(12))


def _random_names(rng: random.Random, count: int) -> list[str]:
    syllables = ["wi", "wa", "son", "ler", "gu", "he", "al", "ma", "ro", "bin", "tit", "ée"]
    names = []
    for _ in range(count):
        words = [
            "".join(rng.choice(syllables) for _ in range(rng.randint(1, 3)))
            for _ in range(rng.randint(1, 6))
        ]
        separator = rng.choice([" ", " ", "-", "'s ", " ("])
        names.append(separator.join(words).capitalize())
    return names


def _random_query(rng: random.Random, names: list[str]) -> str:
    name = rng.choice(names)
    words = split_words(name)
    style = rng.randint(0, 4)
    if style == 0:
        return "".join(word[: rng.randint(1, 3)] for word in words[: rng.randint(1, 3)])
    if style == 1:
        return " ".join(word[: rng.randint(1, 3)] for word in words[: rng.randint(2, 4)])
    if style == 2:
        return name[: rng.randint(1, len(name))]
    if style == 3:
        return "".join(rng.choice("abehilmnorstuwé '-") for _ in range(rng.randint(1, 18)))
    return name.upper() + rng.choice(["", " ", "x"])


def test_fast_indexer_equals_literal_port() -> None:
    rng = random.Random(1)
    names = _random_names(rng, 400)
    fast = Indexer()
    reference = ReferenceIndexer()
    for name in names:
        fast.add(name)
        reference.add(name)
    fast.freeze()
    for _ in range(1500):
        query = _random_query(rng, names)
        assert set(bits_of(fast.find(query))) == reference.find(query), query


def test_initial_capital_matches() -> None:
    # IndexerTest.findOfInitialCapital
    indexer = Indexer()
    indexer.add("Jamaica")
    indexer.freeze()
    assert indexer.find("J") == indexer.find("j") == 1


def test_alternate_words_are_indexed_at_the_same_position() -> None:
    indexer = Indexer()
    grey = indexer.add("Grey Heron", alternates={"grey": ["gray"]})
    indexer.freeze()
    assert set(bits_of(indexer.find("gray he"))) == {grey}
    assert indexer.find("he gray") == 0


def test_frozen_rules() -> None:
    indexer = Indexer()
    with pytest.raises(RuntimeError):
        indexer.find("a")
    indexer.freeze()
    with pytest.raises(RuntimeError):
        indexer.add("late")
    assert indexer.find("") == 0


@pytest.mark.scythebill
def test_scythebill_indexer_test_cases(scythebill: Path) -> None:
    """IndexerTest.find, on Scythebill's own test taxonomy (as sets: Pipit ranks itself)."""
    from pipit.taxa.model import TaxonType
    from pipit.taxa.xml_reader import read_taxonomy

    taxonomy = read_taxonomy(scythebill / "model/src/test/resources/fullTaxonomy.xml")
    common = Indexer()
    scientific = Indexer()
    common_names: list[str] = []
    scientific_names: list[str] = []
    for taxon in taxonomy.walk():
        if taxon.type is TaxonType.SPECIES:
            assert taxon.common_name is not None and taxon.parent is not None
            common.add(taxon.common_name)
            common_names.append(taxon.common_name)
            scientific_name = f"{taxon.parent.name} {taxon.name}"
            scientific.add(scientific_name)
            scientific_names.append(scientific_name)
    common.freeze()
    scientific.freeze()

    def find(query: str) -> set[str]:
        return {common_names[i] for i in bits_of(common.find(query))}

    willow = {"Willow Warbler", "Wilson's Warbler", "Willie-wagtail"}
    assert find("wilwa") == willow
    assert find("WilWa") == willow
    wilsons = {
        "Wilson's Storm-Petrel", "Wilson's Plover", "Wilson's Snipe", "Wilson's Phalarope",
        "Wilson's Bird-of-paradise", "Wilson's Warbler",
    }  # fmt: skip
    assert find("wils") == wilsons | {"Williamson's Sapsucker", "Willard's Sooty Boubou"}
    assert find("wilsons") == wilsons
    assert find("wil s") == {
        "Wilson's Storm-Petrel", "Wilson's Snipe", "Williamson's Sapsucker",
        "Willard's Sooty Boubou",
    }  # fmt: skip
    assert len(list(bits_of(scientific.find("h")))) == 688
    assert find("blskim") == {"Black Skimmer"}
