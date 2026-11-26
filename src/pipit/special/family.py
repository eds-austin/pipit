"""Family report: how many of each order's, family's or genus's species have been seen, of
those possible (on the checklist of the query's places, or in the world).

Ported from Scythebill ``ui/.../panels/reports/FamilyReportComputation.java``,
``FamilyReportTotals.java`` and ``QueryPanel.getTaxonEligibilityPredicate``, with Scythebill's
default preferences: introduced and provisional species count (only escaped ones are left
out of the checklist), undescribed species don't, extinct ones are shown.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pipit.query.checklists import Checklist, Checklists
from pipit.query.engine import (
    EngineContext,
    FamilyValue,
    SpeciesStatusValue,
    StoredQuery,
    run_query,
)
from pipit.query.fields_place_time import LocationValue
from pipit.query.model import QueryList
from pipit.taxa.model import IUCN_STATUSES, Taxon, Taxonomy, TaxonType, visit

TaxonPredicate = Callable[[Taxon], bool]
#: ``QueryPreferences.excludedChecklistStatuses`` with its defaults.
DEFAULT_EXCLUDED = frozenset({"ESCAPED"})
GROUP_TYPES = {"ORDER": TaxonType.ORDER, "FAMILY": TaxonType.FAMILY, "GENUS": TaxonType.GENUS}
_NEVER = ("NEVER", "NEVER_ALL")


@dataclass(frozen=True, slots=True)
class Scope:
    """What the report compares against: a checklist and the places it's named after, or
    the whole world (no checklist, no places)."""

    checklist: Checklist | None
    places: tuple[str, ...]


WORLD = Scope(None, ())


@dataclass(frozen=True, slots=True)
class GroupTotal:
    group: Taxon
    position: int
    seen: int
    total: int

    @property
    def unseen(self) -> int:
        return self.total - self.seen

    @property
    def fraction(self) -> float:
        return self.seen / self.total

    @property
    def percent_seen(self) -> int:
        """Whole percent, rounded down (100% only when every species was seen)."""
        return self.seen * 100 // self.total

    @property
    def percent_text(self) -> str:
        if self.seen > 0 and self.percent_seen == 0:
            return "<1%"
        return f"{self.percent_seen}%"

    @property
    def common_name(self) -> str | None:
        """None for genera and for groups without a name of their own."""
        if self.group.type is TaxonType.GENUS:
            return None
        common = self.group.common_name
        if not common or common == self.group.name:
            return None
        return common


@dataclass(frozen=True, slots=True)
class FamilyTotals:
    group_type: TaxonType
    groups: list[GroupTotal]  # taxonomic order
    seen_species: int
    total_species: int

    @property
    def seen_groups(self) -> int:
        return sum(1 for group in self.groups if group.seen > 0)

    def sorted(self, sort: str, descending: bool) -> list[GroupTotal]:
        """``FamilyReportTotals.sorted``: ties go to the other count, then taxonomic order;
        taxonomic order ignores the direction."""
        keys: dict[str, Callable[[GroupTotal], tuple[float, int]]] = {
            "SPECIES_SEEN": lambda g: (g.seen, g.total),
            "FRACTION_SEEN": lambda g: (g.fraction, g.total),
            "SPECIES_UNSEEN": lambda g: (g.unseen, g.total),
            "TOTAL_SPECIES": lambda g: (g.total, g.seen),
        }
        if sort not in keys:
            return list(self.groups)
        key = keys[sort]
        if descending:
            return sorted(self.groups, key=lambda g: (tuple(-v for v in key(g)), g.position))
        return sorted(self.groups, key=lambda g: (key(g), g.position))


# ------------------------------------------------------------------ eligibility


def eligibility(fields: Sequence[tuple[object, str]], taxonomy: Taxonomy) -> TaxonPredicate:
    """``getTaxonEligibilityPredicate``: the query's family and IUCN rows, at the taxon level.
    Rows of one kind combine with "or" (NEVER rows as exclusions); kinds combine with "and"."""
    included: dict[type, list[TaxonPredicate]] = {}
    excluded: dict[type, list[TaxonPredicate]] = {}
    for value, operation in fields:
        predicate = _taxon_predicate(value, taxonomy)
        if predicate is None:
            continue
        target = excluded if operation in _NEVER else included
        target.setdefault(type(value), []).append(predicate)
    kinds = list(dict.fromkeys([*included, *excluded]))

    def accepts(taxon: Taxon) -> bool:
        for kind in kinds:
            if kind in included and not any(p(taxon) for p in included[kind]):
                return False
            if any(p(taxon) for p in excluded.get(kind, [])):
                return False
        return True

    return accepts


def _taxon_predicate(value: object, taxonomy: Taxonomy) -> TaxonPredicate | None:
    if isinstance(value, FamilyValue):
        if value.taxon_id is None:
            return None
        group = taxonomy.get(value.taxon_id)
        if group is None:
            return lambda _taxon: False
        not_in = value.query == "IS_NOT_IN"
        return lambda taxon: _is_child_of(group, taxon) != not_in
    if isinstance(value, SpeciesStatusValue):
        wanted = IUCN_STATUSES.index(value.status)
        or_worse = value.query == "IS_OR_WORSE"
        never = {IUCN_STATUSES.index(code) for code in ("IN", "DO", "UN")}

        def matches(taxon: Taxon) -> bool:
            status = IUCN_STATUSES.index(taxon.status)
            if status in never:
                return False
            # Scythebill compares Species.Status by enum order, which is this list's
            return status >= wanted if or_worse else status == wanted

        if value.query == "IS_NOT":
            return lambda taxon: not matches(taxon)
        return matches
    return None


def _is_child_of(parent: Taxon, taxon: Taxon) -> bool:
    current = taxon.parent
    while current is not None:
        if current is parent:
            return True
        current = current.parent
    return False


def species_filter(eligible: TaxonPredicate, seen: set[str], *, count_undescribed: bool = False,
                   show_extinct: bool = True) -> TaxonPredicate:  # fmt: skip
    """``speciesFilter``: seen species always; else not undescribed or extinct (unless asked)
    and eligible."""

    def accepts(species: Taxon) -> bool:
        if species.id in seen:
            return True
        if not count_undescribed and species.status == "UN":
            return False
        if not show_extinct and species.status == "EX":
            return False
        return eligible(species)

    return accepts


# ------------------------------------------------------------------ scope


def query_places(fields: Sequence[tuple[object, str]]) -> list[str]:
    """``QueryPanel.getLocations``: every location row's place."""
    found = [value.location_id for value, _operation in fields
             if isinstance(value, LocationValue) and value.location_id]  # fmt: skip
    return list(dict.fromkeys(found))


def resolve_scope(checklists: Checklists, query_list: QueryList, taxonomy: Taxonomy,
                  places: list[str]) -> Scope:  # fmt: skip
    """``resolveScope``: the places' checklist (one place's, or several merged), else the
    nearest built-in checklist of their common ancestor (named for its place), else the
    world."""
    if not places:
        return WORLD
    checklist = _checklist_of(checklists, query_list, taxonomy, places)
    if checklist is not None:
        return Scope(checklist, tuple(places))
    ancestor = _common_ancestor(query_list, places)
    if ancestor is None:
        return WORLD
    code = checklists.nearest_built_in_code(taxonomy, ancestor)
    nearest = checklists.checklist_for_codes(taxonomy, [code]) if code else None
    if nearest is None:
        return WORLD
    named = ancestor
    current: str | None = ancestor
    while current is not None:
        place = checklists.place(current)
        if place is not None and checklists.checklist_code(place) == code:
            named = current
            break
        current = query_list.parent.get(current)
    return Scope(nearest, (named,))


def _checklist_of(checklists: Checklists, query_list: QueryList, taxonomy: Taxonomy,
                  places: list[str]) -> Checklist | None:  # fmt: skip
    """``getChecklistFromLocations``. Several places, all with built-in checklists, make a
    union of their checklists' codes; with lists' own checklists among them Scythebill merges
    those too, which Pipit doesn't yet (no checklist then)."""
    if len(places) == 1:
        return checklists.checklist(taxonomy, places[0])
    codes: dict[str, None] = {}
    for place in places:
        found = checklists.checklist(taxonomy, place)
        if found is None or not found.built_in:
            return None
    for place in places:
        place_codes = checklists.synthesized_codes(place)
        if place_codes is None:
            return None
        codes.update(dict.fromkeys(place_codes))
    return checklists.synthesize(taxonomy, frozenset(codes))


def _common_ancestor(query_list: QueryList, places: list[str]) -> str | None:
    def path(xml_id: str) -> list[str]:
        found: list[str] = []
        current: str | None = xml_id
        while current is not None:
            found.append(current)
            current = query_list.parent.get(current)
        return found[::-1]

    paths = [path(place) for place in places]
    common = None
    for step in zip(*paths, strict=False):
        if len(set(step)) != 1:
            break
        common = step[0]
    return common


# ------------------------------------------------------------------ totals


def compute(taxonomy: Taxonomy, group_type: TaxonType, checklist: Checklist | None, *,
            excluded: frozenset[str], accepts: TaxonPredicate,
            seen: set[str]) -> FamilyTotals:  # fmt: skip
    """``FamilyReportTotals.compute``: a species is possible if seen, or accepted and on the
    checklist with a status not left out (or there's no checklist)."""

    def possible(species: Taxon, was_seen: bool) -> bool:
        return _possible(species, was_seen, accepts, checklist, excluded)

    groups: list[GroupTotal] = []
    totals = [0, 0]  # seen, total species

    def visitor(taxon: Taxon) -> bool:
        if taxon.type is TaxonType.SPECIES:
            was_seen = taxon.id in seen
            if possible(taxon, was_seen):
                totals[1] += 1
                totals[0] += int(was_seen)
            return False
        if taxon.type is not group_type:
            return True
        counts = [0, 0]

        def inner(child: Taxon) -> bool:
            if child.type is not TaxonType.SPECIES:
                return True
            child_seen = child.id in seen
            if possible(child, child_seen):
                counts[1] += 1
                counts[0] += int(child_seen)
            return False

        visit(taxon, inner)
        if counts[1] > 0:
            groups.append(GroupTotal(taxon, len(groups), counts[0], counts[1]))
            totals[0] += counts[0]
            totals[1] += counts[1]
        return False

    assert taxonomy.root is not None
    visit(taxonomy.root, visitor)
    return FamilyTotals(group_type, groups, totals[0], totals[1])


def _possible(species: Taxon, was_seen: bool, accepts: TaxonPredicate,
              checklist: Checklist | None, excluded: frozenset[str]) -> bool:  # fmt: skip
    if was_seen:
        return True
    if not accepts(species):
        return False
    return checklist is None or checklist.includes(species.id, excluded)


# ------------------------------------------------------------------ the report


@dataclass(frozen=True, slots=True)
class FamilyReport:
    """One computation (``FamilyReportComputation.Result``): totals at any level come from it
    without querying again."""

    taxonomy: Taxonomy
    scope: Scope
    accepts: TaxonPredicate
    seen: frozenset[str]
    excluded: frozenset[str] = DEFAULT_EXCLUDED

    def totals(self, group_by: str) -> FamilyTotals:
        return compute(self.taxonomy, GROUP_TYPES[group_by], self.scope.checklist,
                       excluded=self.excluded, accepts=self.accepts,
                       seen=set(self.seen))  # fmt: skip

    def possible(self, species: Taxon) -> bool:
        return _possible(species, species.id in self.seen, self.accepts, self.scope.checklist,
                         self.excluded)  # fmt: skip

    def group_species(self, group: Taxon) -> list[tuple[Taxon, bool]]:
        """The species the totals count in one group, in taxonomic order, and whether each was
        seen."""
        found: list[tuple[Taxon, bool]] = []

        def visitor(taxon: Taxon) -> bool:
            if taxon.type is not TaxonType.SPECIES:
                return True
            if self.possible(taxon):
                found.append((taxon, taxon.id in self.seen))
            return False

        visit(group, visitor)
        return found


def family_report(context: EngineContext, checklists: Checklists,
                  query: StoredQuery) -> FamilyReport:  # fmt: skip
    """``FamilyReportPanel.recompute``: ``context`` is at species depth."""
    fields = list(query.fields)
    taxonomy = context.taxonomy
    results = run_query(query, context, include_families=False, only_countable=True)
    seen = results.countable_species_ids()
    places = query_places(fields)
    scope = resolve_scope(checklists, context.query_list, taxonomy, places)
    accepts = species_filter(eligibility(fields, taxonomy), seen)
    return FamilyReport(taxonomy, scope, accepts, frozenset(seen))
