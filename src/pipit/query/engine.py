"""Running a stored query the way Scythebill's Reports screen does.

Ported from Scythebill:
- ``StoredQueries.restore``: the stored-query JSON (``{"fields": [{"type", "value",
  "bool"}]}``, with a legacy top-level "type") parsed field by field
  (``QueryFieldType.parseValue``);
- ``CompositeQueryDefinition``: ALL fields must match, at least one ANY field must match,
  a NEVER field excludes every taxon it ever matches, NEVER_ALL fields together exclude the
  taxa they all match at once;
- the taxon fields (family, species status, sp. or hybrid, subspecies allocated), the
  observer field, first sightings (lifers) and times sighted;
- ``QueryPreferences``: which sightings count (overridden by a query's own status or
  heard-only field), with Scythebill's defaults;
- ``QueryProcessor.runQuery``: preprocess, then every sighting through the predicate,
  grouped at the query's depth, then postprocess.
"""

from __future__ import annotations

import json as json_module
from collections.abc import Callable, Collection
from dataclasses import dataclass
from functools import cmp_to_key
from typing import Any

from pipit.domain.partial_date import compare_partial_dates
from pipit.query.definition import Predicate, QueryContext, QueryDefinition
from pipit.query.fields_place_time import (
    UnsupportedQueryError,
    parse_date,
    parse_location,
)
from pipit.query.fields_simple import (
    FieldValue,
    QueryJsonError,
    parse_breeding,
    parse_heard_only,
    parse_photographed,
    parse_sex_age,
    parse_sighting_status,
    parse_text,
)
from pipit.query.model import NEVER_COUNTABLE, QSighting, QueryList
from pipit.query.results import QueryResults, ResultsBuilder
from pipit.query.synthetic import regions_for
from pipit.taxa.mapped import MappedTaxonomy
from pipit.taxa.model import IUCN_STATUSES, Taxon, Taxonomy, TaxonType
from pipit.taxa.sighting_taxon import Resolved, SightingTaxon, SightingTaxonType

OPERATIONS = ("ALL", "ANY", "NEVER", "NEVER_ALL")
_MISSING = object()

# ------------------------------------------------------------------ resolution


class Resolver:
    """``SightingTaxon.resolve(taxonomy)`` for base sightings, cached."""

    def __init__(self, taxonomy: Taxonomy) -> None:
        self.taxonomy = taxonomy
        self._cache: dict[SightingTaxon, Resolved | None] = {}
        self._by_row: dict[int, object] = {}
        self._at_depth: dict[tuple[int, TaxonType], object] = {}

    def __call__(self, taxon: SightingTaxon) -> Resolved | None:
        if taxon not in self._cache:
            try:
                if isinstance(self.taxonomy, MappedTaxonomy):
                    resolved = self.taxonomy.resolve_into(taxon)
                else:
                    resolved = taxon.resolve_internal(self.taxonomy)
            except (KeyError, ValueError):
                resolved = None
            self._cache[taxon] = resolved
        return self._cache[taxon]

    def to_depth(self, taxon: SightingTaxon, depth: TaxonType) -> SightingTaxon | None:
        resolved = self(taxon)
        return None if resolved is None else resolved.parent_of_at_least_type(depth)

    def sighting(self, sighting: QSighting) -> Resolved | None:
        """The sighting's taxon resolved, cached by sighting (cheaper than by taxon)."""
        found = self._by_row.get(sighting.row, _MISSING)
        if found is _MISSING:
            found = self._by_row[sighting.row] = self(sighting.taxon)
        return found  # type: ignore[return-value]

    def sighting_at(self, sighting: QSighting, depth: TaxonType) -> SightingTaxon | None:
        """The sighting's taxon at ``depth`` (``getParentOfAtLeastType``), cached."""
        key = (sighting.row, depth)
        found = self._at_depth.get(key, _MISSING)
        if found is _MISSING:
            resolved = self.sighting(sighting)
            found = self._at_depth[key] = (
                None if resolved is None else resolved.parent_of_at_least_type(depth)
            )
        return found  # type: ignore[return-value]


@dataclass
class EngineContext(QueryContext):
    resolver: Resolver | None = None
    users: frozenset[str] = frozenset()
    default_user: str | None = None  # Scythebill's DefaultUserStore (none by default)

    def __post_init__(self) -> None:
        if self.resolver is None:
            self.resolver = Resolver(self.taxonomy)

    def undescribed(self) -> Callable[[QSighting], bool]:
        """``UndescribedTaxa`` for this taxonomy, computed once."""
        cached = self.__dict__.get("_undescribed")
        if cached is None:
            cached = self.__dict__["_undescribed"] = _undescribed(self)
        return cached

    @property
    def resolve(self) -> Resolver:
        assert self.resolver is not None
        return self.resolver


def _compatible(sighting: QSighting) -> bool:
    return sighting.taxonomy_id is None  # only bird (base) taxonomies are queried here


# ------------------------------------------------------------------ taxon fields


def _is_child_of(parent: Taxon, child: Taxon) -> bool:
    """``TaxonUtils.isChildOf``: strictly below."""
    current = child
    while current.type < parent.type:
        assert current.parent is not None
        current = current.parent
        if current is parent:
            return True
    return False


@dataclass(frozen=True)
class FamilyValue(FieldValue):
    query: str  # IS_IN, IS_NOT_IN
    taxon_id: str | None

    @property
    def is_no_op(self) -> bool:
        return self.taxon_id is None

    def definition(self, context: QueryContext) -> QueryDefinition:
        assert isinstance(context, EngineContext)
        if self.taxon_id is None:
            return QueryDefinition()
        group = context.taxonomy.get(self.taxon_id)
        if group is None:
            return QueryDefinition(lambda _s: False)
        not_in = self.query == "IS_NOT_IN"
        resolver = context.resolve

        def predicate(sighting: QSighting) -> bool:
            if not _compatible(sighting):
                return False
            resolved = resolver.sighting(sighting)
            if resolved is None:
                return False
            inside = any(_is_child_of(group, taxon) for taxon in resolved.taxa)
            return inside != not_in

        return QueryDefinition(predicate)


def _taxon_status(taxon: Taxon) -> int:
    """``TaxonUtils.getTaxonStatus``: the worst status of the taxon and its parents up to
    its species (as an index in Scythebill's ``Species.Status`` order)."""
    status = 0
    current: Taxon | None = taxon
    while True:
        assert current is not None
        status = max(status, IUCN_STATUSES.index(current.status))
        current = current.parent
        if current is None or current.type > TaxonType.SPECIES:
            return status


def _resolved_status(resolved: Resolved) -> int:
    """``Resolved.getTaxonStatus``; a sp. or hybrid takes the least severe of its taxa."""
    return min(_taxon_status(taxon) for taxon in resolved.taxa)


_NEVER_STATUS = {IUCN_STATUSES.index(code) for code in ("IN", "DO", "UN")}


@dataclass(frozen=True)
class SpeciesStatusValue(FieldValue):
    query: str  # IS, IS_NOT, IS_OR_WORSE
    status: str

    def definition(self, context: QueryContext) -> QueryDefinition:
        assert isinstance(context, EngineContext)
        wanted = IUCN_STATUSES.index(self.status)
        or_worse = self.query == "IS_OR_WORSE"
        resolver, depth, taxonomy = context.resolve, context.depth, context.taxonomy

        def matches(sighting: QSighting) -> bool:
            if not _compatible(sighting):
                return False
            resolved = resolver.sighting(sighting)
            if resolved is None:
                return False
            if resolved.smallest_type < depth:
                resolved = resolved.parent_of_at_least_type(depth).resolve_internal(taxonomy)
            status = _resolved_status(resolved)
            if status in _NEVER_STATUS:
                return False
            return status >= wanted if or_worse else status == wanted

        if self.query == "IS_NOT":
            return QueryDefinition(lambda s: not matches(s))
        return QueryDefinition(matches)


@dataclass(frozen=True)
class SpOrHybridValue(FieldValue):
    query: str  # IS, IS_NOT
    status_type: str  # SP, HYBRID, NEITHER

    def definition(self, context: QueryContext) -> QueryDefinition:
        assert isinstance(context, EngineContext)
        wanted = {"SP": SightingTaxonType.SP, "HYBRID": SightingTaxonType.HYBRID,
                  "NEITHER": SightingTaxonType.SINGLE}[self.status_type]  # fmt: skip
        resolver, depth = context.resolve, context.depth

        def matches(sighting: QSighting) -> bool:
            if not _compatible(sighting):
                return False
            parent = resolver.sighting_at(sighting, depth)
            if parent is None:
                return False
            kind = parent.type
            if kind is SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES:
                kind = SightingTaxonType.SINGLE
            return kind is wanted

        if self.query == "IS_NOT":
            return QueryDefinition(lambda s: not matches(s))
        return QueryDefinition(matches)


@dataclass(frozen=True)
class SubspeciesAllocatedValue(FieldValue):
    query: str  # IS, IS_NOT

    def definition(self, context: QueryContext) -> QueryDefinition:
        assert isinstance(context, EngineContext)
        allocated = self.query == "IS"
        resolver = context.resolve

        def matches(sighting: QSighting) -> bool:
            if not _compatible(sighting):
                return False
            resolved = resolver.sighting(sighting)
            if resolved is None or resolved.type in (SightingTaxonType.SP,
                                                      SightingTaxonType.HYBRID):  # fmt: skip
                return False
            taxon = resolved.taxon
            if allocated:
                return not taxon.children and taxon.type is not TaxonType.SPECIES
            return any(child.status not in ("IN", "DO") for child in taxon.children)

        return QueryDefinition(matches)


@dataclass(frozen=True)
class UserValue(FieldValue):
    query: str  # INCLUDES, DOES_NOT_INCLUDE, IS_ONLY, ARE_EMPTY
    user: str | None

    @property
    def is_no_op(self) -> bool:
        return self.user is None

    def definition(self, context: QueryContext) -> QueryDefinition:
        if self.query == "ARE_EMPTY":
            return QueryDefinition(lambda s: not s.users)
        user = self.user
        if user is None:
            return QueryDefinition()
        if self.query == "INCLUDES":
            return QueryDefinition(lambda s: user in s.users)
        if self.query == "DOES_NOT_INCLUDE":
            return QueryDefinition(lambda s: user not in s.users)
        return QueryDefinition(lambda s: s.users == frozenset({user}))


# ------------------------------------------------------------------ times sighted


@dataclass(frozen=True)
class TimesSightedValue(FieldValue):
    query: str  # EXACTLY, AT_MOST, AT_LEAST, LESS_THAN, MORE_THAN
    count: int

    def definition(self, context: QueryContext) -> QueryDefinition:
        return QueryDefinition(postprocessor=_TimesSighted(self.query, self.count))


@dataclass(frozen=True)
class _TimesSighted:
    query: str
    count: int

    def accept_taxon(
        self, taxon: SightingTaxon, sightings: Collection[QSighting], countable: Predicate | None
    ) -> bool:
        size = len(sightings) if countable is None else sum(1 for s in sightings if countable(s))
        return {
            "EXACTLY": size == self.count, "AT_MOST": size <= self.count,
            "AT_LEAST": size >= self.count, "LESS_THAN": size < self.count,
            "MORE_THAN": size > self.count,
        }[self.query]  # fmt: skip


# ------------------------------------------------------------------ first sightings


def _more_recent(a: QSighting, b: QSighting) -> int:
    """``SightingComparators.MoreRecentComparator``: by start date (none first), then by
    stored time (none first)."""
    a_date, b_date = a.start_date, b.start_date
    if a_date is None:
        return 0 if b_date is None else -1
    if b_date is None:
        return 1
    compared = compare_partial_dates(a_date, b_date)
    if compared:
        return compared
    if a.time is None:
        return 0 if b.time is None else -1
    if b.time is None:
        return 1
    return (a.time.hour - b.time.hour) or (a.time.minute - b.time.minute)


class _FirstSightings:
    """``FirstSightingsQueryDefinition``: the first countable sighting (``preferEarlier``)
    of each taxon that passes the nested query; HIGHLIGHTED marks them as lifers,
    INCLUDED keeps only them."""

    def __init__(self, nested: Predicate, context: EngineContext, included: bool) -> None:
        self._nested = nested
        self._resolver = context.resolve
        self._depth = context.depth
        self._included = included
        self._first: dict[SightingTaxon, QSighting] = {}

    def reset(self) -> None:
        self._first.clear()

    def preprocess(self, sighting: QSighting, countable: Predicate) -> None:
        if countable is not None and not countable(sighting):
            return
        if not self._nested(sighting):
            return
        resolver = self._resolver
        resolved = resolver.sighting(sighting)
        if resolved is None:
            return
        if self._included:
            self._offer(resolver.sighting_at(sighting, self._depth), sighting)
            return
        # At subspecies level, the resolved taxon is itself (cached, unlike sighting_taxon).
        taxon = resolver.sighting_at(sighting, TaxonType.SUBSPECIES)
        group = resolver.sighting_at(sighting, TaxonType.GROUP)
        species = resolver.sighting_at(sighting, TaxonType.SPECIES)
        self._offer(species, sighting)
        if group != species:
            self._offer(group, sighting)
        if taxon != group:
            self._offer(taxon, sighting)

    def _offer(self, taxon: SightingTaxon | None, sighting: QSighting) -> None:
        if taxon is None or taxon.type not in (SightingTaxonType.SINGLE,
                              SightingTaxonType.SINGLE_WITH_SECONDARY_SUBSPECIES):  # fmt: skip
            return
        existing = self._first.get(taxon)
        # preferEarlier: keep the existing one unless the new one is strictly earlier
        if existing is not None and sighting.recency >= existing.recency:
            return
        self._first[taxon] = sighting

    def test(self, sighting: QSighting) -> bool:
        if not _compatible(sighting):
            return False
        taxon = self._resolver.sighting_at(sighting, self._depth)
        return taxon is not None and self._first.get(taxon) is sighting

    def annotate(self, sighting: QSighting, taxon: SightingTaxon) -> str | None:
        if self._included:
            return None
        return "lifer" if self._first.get(taxon) is sighting else None


@dataclass(frozen=True)
class FirstSightingsValue(FieldValue):
    query: str  # HIGHLIGHTED, INCLUDED
    nested: tuple[tuple[FieldValue, str], ...]  # (field, operation)

    def definition(self, context: QueryContext) -> QueryDefinition:
        assert isinstance(context, EngineContext)
        fields = list(self.nested)
        default_user = context.default_user
        if default_user and not any(f.type == "USER" for f, _ in fields):
            fields.append((UserValue("USER", "INCLUDES", default_user), "ALL"))
        nested = composite(fields, context)
        first = _FirstSightings(nested.predicate, context, self.query == "INCLUDED")
        return QueryDefinition(
            predicate=first.test if self.query == "INCLUDED" else (lambda _s: True),
            preprocessor=first,
            annotator=first.annotate,
        )


# ------------------------------------------------------------------ combining fields


class _Never:
    """``NeverQueryDefinition``: excludes every taxon (at the depth) that some sighting
    matching all the wrapped definitions has; the countable predicate is ignored."""

    def __init__(self, definitions: list[QueryDefinition], context: EngineContext) -> None:
        self._definitions = definitions
        self._resolver = context.resolve
        self._depth = context.depth
        self._excluded: set[SightingTaxon | None] = set()

    def _key(self, sighting: QSighting) -> SightingTaxon | None:
        if self._depth is TaxonType.SUBSPECIES:
            return sighting.taxon
        return self._resolver.sighting_at(sighting, self._depth)

    def _matches_all(self, sighting: QSighting) -> bool:
        return all(definition.predicate(sighting) for definition in self._definitions)

    def reset(self) -> None:
        self._excluded.clear()

    def preprocess(self, sighting: QSighting, countable: Predicate) -> None:
        if _compatible(sighting) and self._matches_all(sighting):
            self._excluded.add(self._key(sighting))

    def test(self, sighting: QSighting) -> bool:
        if not _compatible(sighting) or self._key(sighting) in self._excluded:
            return False
        return not self._matches_all(sighting)

    def annotate(self, sighting: QSighting, taxon: SightingTaxon) -> str | None:
        for definition in self._definitions:
            found = definition.annotate(sighting, taxon)
            if found is not None:
                return found
        return None


def _never(definitions: list[QueryDefinition], context: EngineContext) -> QueryDefinition:
    never = _Never(definitions, context)
    return QueryDefinition(never.test, never, None, never.annotate)


class _Preprocessors:
    def __init__(self, preprocessors: list[Any]) -> None:
        self._all = preprocessors

    def reset(self) -> None:
        for preprocessor in self._all:
            preprocessor.reset()

    def preprocess(self, sighting: QSighting, countable: Predicate) -> None:
        for preprocessor in self._all:
            preprocessor.preprocess(sighting, countable)


class _PostProcessors:
    def __init__(self, postprocessors: list[Any]) -> None:
        self._all = postprocessors

    def accept_taxon(
        self, taxon: SightingTaxon, sightings: Collection[QSighting], countable: Predicate | None
    ) -> bool:
        return all(p.accept_taxon(taxon, sightings, countable) for p in self._all)


def _all(predicates: list[Predicate]) -> Predicate:
    """All of ``predicates``, without a generator for the common short cases."""
    if not predicates:
        return lambda _s: True
    if len(predicates) == 1:
        return predicates[0]
    if len(predicates) == 2:
        first, second = predicates
        return lambda s: first(s) and second(s)
    return lambda s: all(p(s) for p in predicates)


def composite(fields: list[tuple[FieldValue, str]], context: EngineContext) -> QueryDefinition:
    """``CompositeQueryDefinition``."""
    ands: list[Predicate] = []
    ors: list[Predicate] = []
    never_all: list[QueryDefinition] = []
    definitions: list[QueryDefinition] = []
    for value, operation in fields:
        definition = value.definition(context)
        if operation == "NEVER_ALL":
            never_all.append(definition)
            continue
        joined = operation
        if operation == "NEVER":
            definition = _never([definition], context)
            joined = "ALL"
        (ands if joined == "ALL" else ors).append(definition.predicate)
        definitions.append(definition)
    if never_all:
        combined = _never(never_all, context)
        definitions.append(combined)
        ands.append(combined.predicate)
    if ors:
        any_of = list(ors)
        ands.append(any_of[0] if len(any_of) == 1 else lambda s: any(p(s) for p in any_of))
    all_of = list(ands)
    preprocessors = [d.preprocessor for d in definitions if d.preprocessor is not None]
    postprocessors = [d.postprocessor for d in definitions if d.postprocessor is not None]

    def annotate(sighting: QSighting, taxon: SightingTaxon) -> str | None:
        for definition in definitions:
            found = definition.annotate(sighting, taxon)
            if found is not None:
                return found
        return None

    return QueryDefinition(
        predicate=_all(all_of),
        preprocessor=_Preprocessors(preprocessors) if preprocessors else None,
        postprocessor=(None if not postprocessors else postprocessors[0]
                       if len(postprocessors) == 1 else _PostProcessors(postprocessors)),
        annotator=annotate,
    )  # fmt: skip


# ------------------------------------------------------------------ parsing


@dataclass(frozen=True)
class StoredQuery:
    fields: tuple[tuple[FieldValue, str], ...]

    def has(self, field_type: str) -> bool:
        return any(value.type == field_type for value, _ in self.fields)


def parse_query(text: str | dict[str, Any], query_list: QueryList, users: Collection[str] = ()
                ) -> StoredQuery:  # fmt: skip
    """``StoredQueries.restore``: refuses what Scythebill refuses (QueryJsonError)."""
    data = json_module.loads(text) if isinstance(text, str) else text
    if not isinstance(data, dict) or not isinstance(data.get("fields"), list):
        raise QueryJsonError("a stored query needs a list of fields")
    legacy = data.get("type")
    if legacy is not None and legacy not in OPERATIONS:
        raise QueryJsonError(f"Unknown operation {legacy}")
    parsed = []
    for item in data["fields"]:
        if not isinstance(item, dict):
            raise QueryJsonError(f"expected a field object, got {item!r}")
        operation = item.get("bool", legacy) or "ALL"
        if operation not in OPERATIONS:
            raise QueryJsonError(f"Unknown operation {operation}")
        parsed.append((parse_field(item.get("type"), item.get("value"), query_list, users),
                       operation))  # fmt: skip
    return StoredQuery(tuple(parsed))


def parse_field(field_type: Any, value: Any, query_list: QueryList, users: Collection[str]
                ) -> FieldValue:  # fmt: skip
    def known_place(xml_id: str) -> bool:
        return xml_id in query_list.parent or xml_id in regions_for(query_list)

    def object_of(json: Any) -> dict[str, Any]:
        if not isinstance(json, dict):
            raise QueryJsonError(f"expected an object, got {json!r}")
        return json

    match field_type:
        case "LOCATION":
            return parse_location(value, known_place)
        case "DATE":
            return parse_date(value)
        case "ALLOW_HEARD_ONLY":
            return parse_heard_only(value)
        case "PHOTOGRAPHED":
            return parse_photographed(value)
        case "SIGHTING_STATUS":
            return parse_sighting_status(value)
        case "SEX_AGE":
            return parse_sex_age(value)
        case "BREEDING_CODE":
            return parse_breeding(value)
        case "SIGHTING_NOTES" | "VISIT_COMMENTS":
            return parse_text(field_type, value)
        case "FAMILY":
            data = object_of(value)
            return FamilyValue("FAMILY", data.get("type") or "IS_IN", data.get("id"))
        case "SPECIES_STATUS":
            data = object_of(value)
            if data.get("statusId") not in IUCN_STATUSES:
                raise QueryJsonError(f"Invalid species status: {data.get('statusId')}")
            return SpeciesStatusValue("SPECIES_STATUS", data.get("type") or "IS",
                                      data["statusId"])  # fmt: skip
        case "SP_OR_HYBRID":
            data = object_of(value)
            return SpOrHybridValue("SP_OR_HYBRID", data.get("type") or "IS",
                                   data.get("statusType") or "SP")  # fmt: skip
        case "SUBSPECIES_ALLOCATED":
            return SubspeciesAllocatedValue("SUBSPECIES_ALLOCATED",
                                            object_of(value).get("type") or "IS")  # fmt: skip
        case "USER":
            data = object_of(value)
            user = data.get("id")
            if user is not None and user not in users:
                raise QueryJsonError(f"User {user} not found")
            return UserValue("USER", data.get("type") or "INCLUDES", user)
        case "TIMES_SIGHTED":
            data = object_of(value)
            return TimesSightedValue("TIMES_SIGHTED", data.get("type") or "AT_LEAST",
                                     int(data.get("count") or 0))  # fmt: skip
        case "FIRST_SIGHTINGS":
            data = object_of(value)
            nested: list[tuple[FieldValue, str]] = []
            if data.get("id") is not None:
                if not known_place(data["id"]):
                    raise QueryJsonError(f"Unknown ID: {data['id']}")
                nested = [(parse_location({"type": "IN", "id": data["id"]}, known_place), "ALL")]
            if data.get("query"):
                nested = list(parse_query(data["query"], query_list, users).fields)
            return FirstSightingsValue("FIRST_SIGHTINGS", data.get("type") or "HIGHLIGHTED",
                                       tuple(nested))  # fmt: skip
    raise QueryJsonError(f"Unknown field type {field_type}")


# ------------------------------------------------------------------ countability


@dataclass(frozen=True)
class CountingPreferences:
    """``QueryPreferences``, with Scythebill's defaults."""

    count_introduced: bool = True
    count_provisional: bool = True
    count_heard_only: bool = True
    count_undescribed: bool = False
    count_restrained: bool = False

    def countable(self, query: StoredQuery, undescribed: Callable[[QSighting], bool]) -> Predicate:
        """``RestoredQuery.countablePredicate`` then ``getCountablePredicate``."""
        skip_status = query.has("SIGHTING_STATUS")
        heard: bool | str | None = "preference"
        for value, operation in query.fields:
            if value.type == "ALLOW_HEARD_ONLY":
                wanted = value.boolean_value
                if wanted is not None and operation in ("NEVER", "NEVER_ALL"):
                    wanted = not wanted
                heard = wanted  # None: any
        excluded: set[str] = set()
        if not skip_status:
            excluded = set(NEVER_COUNTABLE)
            if not self.count_restrained:
                excluded.add("restrained")
            if not self.count_introduced:
                excluded.add("intro")
            if not (self.count_introduced and self.count_provisional):
                excluded.add("provisional")
        if heard == "preference":
            heard = None if self.count_heard_only else False
        exclude_undescribed = not self.count_undescribed
        frozen = frozenset(excluded)

        def predicate(sighting: QSighting) -> bool:
            if sighting.status in frozen:
                return False
            if heard is not None and sighting.heard_only != heard:
                return False
            return not (exclude_undescribed and undescribed(sighting))

        return predicate


# ------------------------------------------------------------------ running


def run_query(
    query: StoredQuery,
    context: EngineContext,
    preferences: CountingPreferences | None = None,
    include_families: bool = True,
    only_countable: bool = False,
    *,
    include_incompatible: bool = False,
) -> QueryResults:
    """``QueryProcessor.runQuery`` as the Reports screen calls it (``only_countable``:
    ``onlyIncludeCountableSightings``, as Print and Save as may ask;
    ``include_incompatible``: ``includingIncompatibleSightings``, keeping the matching
    sightings of other taxonomies apart, as trip reports ask, for their visits)."""
    preferences = preferences or CountingPreferences()
    definition = composite(list(query.fields), context)
    undescribed = context.undescribed()
    countable = preferences.countable(query, undescribed)
    sightings = context.query_list.sightings
    if definition.preprocessor is not None:
        definition.preprocessor.reset()
        for sighting in sightings:
            if _compatible(sighting):
                definition.preprocessor.preprocess(sighting, countable)
    depth = context.depth
    resolve_all = depth is not TaxonType.SUBSPECIES or isinstance(context.taxonomy,
                                                                   MappedTaxonomy)  # fmt: skip
    builder = ResultsBuilder()
    predicate = definition.predicate
    if only_countable:
        query_predicate = predicate

        def predicate(sighting: QSighting) -> bool:
            return query_predicate(sighting) and countable(sighting)

    for sighting in sightings:
        if not predicate(sighting):
            continue
        if not _compatible(sighting):
            if include_incompatible:
                builder.incompatible.append(sighting)
            continue
        taxon: SightingTaxon | None = sighting.taxon
        if resolve_all:
            taxon = context.resolve.sighting_at(sighting, depth)
            if taxon is None:
                continue
        assert taxon is not None
        builder.add(sighting, taxon, definition.annotate(sighting, taxon))
    if definition.postprocessor is not None:
        builder.post_process(definition.postprocessor, countable)
    results = QueryResults(context.taxonomy, builder, depth, countable, include_families)
    results.resolve = context.resolve
    results.annotate = definition.annotate
    return results


def _undescribed(context: EngineContext) -> Callable[[QSighting], bool]:
    """``UndescribedTaxa``: sightings whose taxon is undescribed ("UN") in the display
    taxonomy (in AviList, its exact base mapping)."""
    taxonomy = context.taxonomy
    taxa: set[SightingTaxon] = set()
    for taxon in taxonomy.walk():
        if taxon.status != "UN":
            continue
        if isinstance(taxonomy, MappedTaxonomy):
            mapping = taxonomy.exact_mapping(taxon)
            if mapping is not None:
                taxa.add(mapping)
        else:
            taxa.add(SightingTaxon.single(taxon.id))
    frozen = frozenset(taxa)
    return lambda sighting: sighting.taxon in frozen


__all__ = ["UnsupportedQueryError", "cmp_to_key"]
