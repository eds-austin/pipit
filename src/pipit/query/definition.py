"""Query definitions: what one stored-query field (or the whole query) contributes.

``QueryDefinition`` in Scythebill: a sighting predicate, plus optional stages around it:
a preprocessor that sees every sighting first (lifer tracking), a postprocessor that
accepts or rejects whole taxa afterwards, and annotations (such as "lifer") on sightings.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from typing import Protocol

from pipit.query.model import QSighting, QueryList
from pipit.taxa.model import Taxonomy, TaxonType
from pipit.taxa.sighting_taxon import SightingTaxon

Predicate = Callable[[QSighting], bool]


def always(_sighting: QSighting) -> bool:
    return True


class Preprocessor(Protocol):
    def reset(self) -> None: ...

    def preprocess(self, sighting: QSighting, countable: Predicate) -> None: ...


class PostProcessor(Protocol):
    def accept_taxon(
        self, taxon: SightingTaxon, sightings: Collection[QSighting], countable: Predicate | None
    ) -> bool: ...


Annotator = Callable[[QSighting, SightingTaxon], str | None]


@dataclass
class QueryDefinition:
    predicate: Predicate = always
    preprocessor: Preprocessor | None = None
    postprocessor: PostProcessor | None = None
    annotator: Annotator | None = None

    def annotate(self, sighting: QSighting, taxon: SightingTaxon) -> str | None:
        return None if self.annotator is None else self.annotator(sighting, taxon)


@dataclass
class QueryContext:
    """What fields need to build their definitions."""

    query_list: QueryList
    taxonomy: Taxonomy  # the display taxonomy
    depth: TaxonType
    #: Synthetic regions ("ABA Area") by ID -> the places they include
    synthetic: dict[str, frozenset[str]] = field(default_factory=dict)
