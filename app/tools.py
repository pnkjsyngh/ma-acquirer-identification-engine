"""Stage 1 tool schemas + implementations: evidence retrieval the LLM selects and calls,
plus the one genuine dynamic-routing tool (widen_to_adjacent_sector).

All tools read from an already-built dossier dict (see app/ranking.py::build_dossier,
app/evidence.py::compute_adjacent_candidates) -- no pandas access at call time, so these
stay simple, synchronous, and unit-testable independent of the LLM loop.
"""

from __future__ import annotations

from app.features import DEFAULT_THESIS_TAGS

TOOL_SCHEMAS = [
    {
        "name": "get_precedent_deals",
        "description": (
            "Return this acquirer's deal history rows already computed in the dossier "
            "(year, target, sector, size, deal type, multiples, outcome, strategic tags). "
            "Optionally filter by sector or minimum year to narrow the result before citing it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sector": {"type": "string", "description": "Restrict to deals in this sector. Omit for all sectors."},
                "min_year": {"type": "integer", "description": "Restrict to deals in or after this year."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_valuation_comps",
        "description": (
            "Return closed comparable deals (adjacent-sector, $100-400M EV) already computed "
            "in the dossier for valuation benchmarking, optionally narrowed by sector."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sector": {"type": "string", "description": "Restrict comps to this sector. Omit for all comps in the dossier."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_rationale_tag_overlap",
        "description": (
            "Return counts of strategic_rationale_tags across this acquirer's deal history "
            "and which of those tags overlap with the target's thesis tags."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "widen_to_adjacent_sector",
        "description": (
            "Pull supplementary deals from sectors adjacent to the target's sector (by "
            "data-derived sector similarity) to widen thin evidence. Only call this when "
            "dossier.thin_evidence is true and the deals already visible are insufficient "
            "to support a rationale."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def get_precedent_deals(dossier: dict, sector: str | None = None, min_year: int | None = None) -> list[dict]:
    deals = dossier["deals_table"]
    if sector:
        deals = [d for d in deals if d["sector"] == sector]
    if min_year:
        deals = [d for d in deals if d["deal_year"] >= min_year]
    return deals


def get_valuation_comps(dossier: dict, sector: str | None = None) -> list[dict]:
    comps = dossier["comparable_closed_deals"]
    if sector:
        comps = [c for c in comps if c["sector"] == sector]
    return comps


def get_rationale_tag_overlap(dossier: dict, target_profile: dict) -> dict:
    thesis_tags = target_profile.get("thesis_tags", DEFAULT_THESIS_TAGS)
    counts: dict[str, int] = {}
    for deal in dossier["deals_table"]:
        for tag in deal["strategic_rationale_tags"]:
            counts[tag] = counts.get(tag, 0) + 1
    overlap = [tag for tag in thesis_tags if tag in counts]
    return {"tag_counts": counts, "thesis_tags": thesis_tags, "overlapping_tags": overlap}


def widen_to_adjacent_sector(dossier: dict) -> list[dict]:
    return dossier.get("adjacent_candidate_deals", [])


_TOOL_FUNCS = {
    "get_precedent_deals": get_precedent_deals,
    "get_valuation_comps": get_valuation_comps,
    "get_rationale_tag_overlap": get_rationale_tag_overlap,
    "widen_to_adjacent_sector": widen_to_adjacent_sector,
}

_NEEDS_TARGET_PROFILE = {"get_rationale_tag_overlap"}


def execute_tool(name: str, tool_input: dict, dossier: dict, target_profile: dict) -> list[dict] | dict:
    if name not in _TOOL_FUNCS:
        raise ValueError(f"Unknown tool: {name!r}")
    func = _TOOL_FUNCS[name]
    if name in _NEEDS_TARGET_PROFILE:
        return func(dossier, target_profile)
    return func(dossier, **tool_input)
