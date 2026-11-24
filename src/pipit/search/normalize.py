"""Text normalization and word splitting for type-ahead search.

An exact port of Scythebill's rules, not general Unicode folding, so that the same keys
find the same names:

- ``Trie.normalizeChar`` (``model/src/commonMain/kotlin/.../util/Trie.kt``): characters up
  to U+017E are lowercased (Java's simple case mapping) and Latin-1 / Latin Extended-A
  diacritics are removed with a hand-made table (including its quirks, such as "ð" -> "o"
  and "æ", "ß" unchanged). Above that only Ș, ș, ɘ and ə are mapped; nothing is lowercased.
- ``Indexer.splitIntoWords`` / ``removeDroppedCharacters`` (``.../util/Indexer.kt``): words
  are separated by ASCII whitespace, "-", ".", "," and "/"; "'", "(" and ")" are dropped.
"""

from __future__ import annotations

import re

#: Unicode table U+0100..U+017F without diacritics (Scythebill's NORMALIZED_100_TABLE).
_TABLE_100 = (
    "aaaaaaccccccccdd"
    "ddeeeeeeeeeegggg"
    "gggghhhhiiiiiiii"
    "iijjjjkkklllllll"
    "lllnnnnnnnnnoooo"
    "oooorrrrrrssssss"
    "ssttttttuuuuuuuu"
    "uuuuwwyyyzzzzzzf"
)
_LATIN1 = {
    **dict.fromkeys(range(224, 230), "a"),
    231: "c",
    **dict.fromkeys(range(232, 236), "e"),
    **dict.fromkeys(range(236, 240), "i"),
    241: "n",
    **dict.fromkeys((240, 242, 243, 244, 245, 246, 248), "o"),
    **dict.fromkeys(range(249, 253), "u"),
    253: "y",
    255: "y",
}
_HIGH = {"Ș": "s", "ș": "s", "ɘ": "e", "ə": "e"}


def _java_lowercase(character: str) -> str:
    """``Character.toLowerCase`` for one char: Python's lower() except where it expands."""
    lowered = character.lower()
    if len(lowered) == 1:
        return lowered
    return "i" if character == "İ" else character  # İ -> i, as Java does


def _normalize_slow(code: int) -> str:
    lowered = _java_lowercase(chr(code))
    lowered_code = ord(lowered)
    if lowered_code in _LATIN1:
        return _LATIN1[lowered_code]
    if 0x100 <= lowered_code <= 0x17F:
        return _TABLE_100[lowered_code - 0x100]
    return lowered


# Scythebill's array covers 0..0x17E; U+017F (long s) would overflow it there, so it is
# mapped through the same table here ("f") instead of failing.
_TRANSLATION = {code: _normalize_slow(code) for code in range(0x180)}
_TRANSLATION.update({ord(source): target for source, target in _HIGH.items()})
_TRANSLATION = {code: value for code, value in _TRANSLATION.items() if chr(code) != value}

_WORD_SEPARATORS = re.compile(r"[ \t\n\x0b\f\r\-.,/]+")  # Java's \s is ASCII-only
_DROPPED = str.maketrans("", "", "'()")


def normalize(text: str) -> str:
    """``Trie.normalizeString``."""
    return text.translate(_TRANSLATION)


def drop_characters(text: str) -> str:
    """``Indexer.removeDroppedCharacters``: remove apostrophes and parentheses."""
    return text.translate(_DROPPED)


def split_words(text: str) -> list[str]:
    """``Indexer.splitIntoWords``."""
    return [word for word in _WORD_SEPARATORS.split(text) if word]


def index_words(name: str, max_words: int) -> list[str]:
    """The normalized words a name is indexed under, one per word position."""
    return [normalize(drop_characters(word)) for word in split_words(name)[:max_words]]


def query_text(query: str) -> str:
    """A query as ``Indexer.find`` sees it before splitting."""
    return drop_characters(normalize(query))
