"""Write the type-ahead query corpus used to compare Pipit with Scythebill.

    python -I tools/oracle/make_corpus.py <scythebill checkout> <out.txt>

Deterministic (fixed seed): abbreviations, prefixes, two-word queries, scientific names and
alternate names sampled from both taxonomies, plus hand-picked edge cases.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from pipit.packbuild.build import load_taxonomies
from pipit.packbuild.sources import ScythebillSources
from pipit.search.normalize import split_words
from pipit.taxa.model import full_name

EDGE_CASES = [
    "",
    " ",
    "  ",
    "h",
    "H",
    "'",
    "(",
    "-",
    "wiwa",
    "wiwa ",
    " wiwa",
    "wi wa",
    "WilWa",
    "wilwa",
    "wils",
    "wilsons",
    "wilson's",
    "Wilson's Warbler",
    "wil s",
    "blskim",
    "he gu",
    "he-gu",
    "he/gu",
    "he.gu",
    "he,gu",
    "amro",
    "comost",
    "grbheron",
    "anas pla",
    "anapla",
    "ñandu",
    "Ñandú",
    "nandu",
    "Ægithalos",
    "aegithalos",
    "ð",
    "æ",
    "ß",
    "İ",
    "ı",
    "Ș",
    "ə",
    "Δ",
    "ελ",
    "ʻiʻiwi",
    "iiwi",
    "ō",
    "o'o",
    "oo",
    "Sterna(",
    "(Eurasian)",
    "zz",
    "qq",
    "x",
    "aaaaaaaaaaaaaaaaaaaa",
    "wilsonswarblerxyz",
    "abcdefghijklmnop",
    "greatblueheronx",
    "greatblueheron",
    "a b c d e",
    "a b c d e f",
    "a b c d e f g",
    "1",
    "2026",
    "sp.",
    "x y",
    "grey",
    "gray",
    "colour",
    "eurasian",
    "common ",
    "bird-of-paradise",
    "birdofparadise",
]


def abbreviation(words: list[str], letters: int) -> str:
    return "".join(word[:letters] for word in words)


def main() -> int:
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    taxonomies = load_taxonomies(ScythebillSources(root))
    rng = random.Random(2026)
    common: list[str] = []
    scientific: list[str] = []
    alternates: list[str] = []
    for taxonomy in (taxonomies.base, taxonomies.avilist):
        for taxon in taxonomy.walk():
            if not taxon.type.is_species_like:
                continue
            if taxon.common_name:
                common.append(taxon.common_name)
            scientific.append(full_name(taxon))
            alternates += taxon.alternate_common_names + taxon.alternate_names
    common.sort()
    scientific.sort()
    alternates.sort()

    queries: list[str] = list(EDGE_CASES)
    for name in rng.sample(common, 150):
        words = split_words(name)
        queries.append(abbreviation(words[:2], 2) if len(words) > 1 else words[0][:4])
    for name in rng.sample(common, 60):
        queries.append(abbreviation(split_words(name)[:3], 1))
    for name in rng.sample(common, 100):
        queries.append(split_words(name)[0][: rng.randint(2, 6)])
    for name in rng.sample(common, 80):
        words = split_words(name)
        if len(words) > 1:
            queries.append(f"{words[0][:3]} {words[-1][:3]}")
    for name in rng.sample(scientific, 80):
        words = name.split()
        queries.append(f"{words[0][:3]} {words[1][:3]}" if rng.random() < 0.5
                       else abbreviation(words[:2], 3))  # fmt: skip
    for name in rng.sample(alternates, 60):
        queries.append(abbreviation(split_words(name)[:2], 2))
    accented = [name for name in common if not name.isascii()]
    for name in rng.sample(accented, min(30, len(accented))):
        queries.append(name[: rng.randint(3, len(name))])
    letters = "abcdefghijklmnopqrstuvwxyz"
    for _ in range(50):
        queries.append("".join(rng.choice(letters) for _ in range(rng.randint(1, 3))))
    for name in rng.sample(common, 20):
        queries.append(name.upper())

    unique = list(dict.fromkeys(query for query in queries if "\n" not in query))
    out.write_text("\n".join(unique) + "\n", encoding="utf-8")
    print(f"{len(unique)} queries -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
