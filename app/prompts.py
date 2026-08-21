"""System/user prompt construction and the output JSON schema for per-acquirer synthesis.

Design principles:
1. Evidence-first -- the LLM only sees numbers we compute; it cannot invent data.
2. Per-acquirer -- one call per acquirer, never a single "rank 10" prompt (avoids
   template drift where every rationale reads the same).
3. Schema-constrained -- structured JSON, validated on parse.
4. Anti-boilerplate -- explicit rule forbidding claims that don't cite data.
5. Ranking is deterministic upstream -- the LLM synthesizes prose from computed
   signals; it never re-ranks and never sets the conviction level.
6. Source discipline -- CSV figures for Precedent Activity and Valuation Context;
   external facts (each with a source_url) only in Acquirer Overview and Risk Flags.
"""

from __future__ import annotations

import json

SYSTEM_PROMPT = """You are an M&A advisory associate at an investment bank writing an \
acquirer rationale for a Managing Director. Your work goes directly into client \
materials with no further editing.

Hard rules:
- Every factual claim MUST cite a specific figure from the data provided below.
- If a claim is not supported by the provided data, omit it.
- Never write a sentence that could apply to a different acquirer.
- Return valid JSON matching the schema exactly. No prose outside the JSON.
- Match every field name in the schema exactly -- do not rename, add, or nest fields.
- `acquirer_overview` and `strategic_fit_thesis` are plain strings, not objects.
- Cite CSV figures for Precedent Activity and Valuation Context only. Cite external \
facts (with source_url) only in Acquirer Overview and Risk Flags. Drop any fact \
without a source.
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "required": [
        "conviction",
        "acquirer_overview",
        "strategic_fit_thesis",
        "precedent_activity",
        "valuation_context",
        "risk_flags",
    ],
    "properties": {
        "conviction": {
            "type": "object",
            "required": ["level", "rationale"],
            "properties": {
                "level": {"enum": ["High", "Medium", "Low"]},
                "rationale": {"type": "string"},
            },
        },
        "acquirer_overview": {"type": "string"},
        "strategic_fit_thesis": {"type": "string"},
        "precedent_activity": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer"},
                    "target": {"type": "string"},
                    "sector": {"type": "string"},
                    "deal_size_mm": {"type": "number"},
                    "deal_type": {"type": "string"},
                    "ev_ebitda_multiple": {"type": ["number", "null"]},
                },
            },
        },
        "valuation_context": {
            "type": "object",
            "properties": {
                "median_ev_ebitda": {"type": ["number", "null"]},
                "median_ev_revenue": {"type": ["number", "null"]},
                "comparable_deal_ids": {"type": "array", "items": {"type": "string"}},
                "narrative": {"type": "string"},
            },
        },
        "risk_flags": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "required": ["risk", "evidence"],
                "properties": {"risk": {"type": "string"}, "evidence": {"type": "string"}},
            },
        },
        "external_sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fact": {"type": "string"},
                    "source_url": {"type": "string"},
                    "kind": {"enum": ["wikipedia"]},
                },
            },
        },
    },
}


def conviction_level_for_rank(rank: int) -> str:
    """Conviction is a deterministic function of rank position -- the LLM justifies
    it, it never sets it."""
    if rank <= 3:
        return "High"
    if rank <= 7:
        return "Medium"
    return "Low"


def build_user_prompt(
    target_profile: dict,
    dossier: dict,
    conviction_level: str,
    external_facts: list[dict],
) -> str:
    deals_table = "\n".join(
        f"- {d['deal_year']} | {d['target_company']} | {d['sector']} | ${d['deal_size_mm']:.0f}M | "
        f"{d['deal_type']} | {d['geography']} | EV/EBITDA {d['ev_ebitda_multiple']} | "
        f"EV/Rev {d['ev_revenue_multiple']} | margin {d['ebitda_margin_pct']}% | "
        f"{d['outcome']} | tags: {', '.join(d['strategic_rationale_tags'])}"
        for d in dossier["deals_table"]
    )
    comps_table = "\n".join(
        f"- {c['target_company']} acquired by {c['acquirer']} | {c['sector']} | ${c['deal_size_mm']:.0f}M | "
        f"{c['deal_type']} | EV/EBITDA {c['ev_ebitda_multiple']} | EV/Rev {c['ev_revenue_multiple']}"
        for c in dossier["comparable_closed_deals"]
    )
    risk_candidates = "\n".join(f"- {r}" for r in dossier["risk_candidates"]) or "- None flagged by the data"
    external = (
        "\n".join(f"- {f['text']} (source: {f['source_url']})" for f in external_facts)
        if external_facts
        else "- None available for this acquirer"
    )

    geography = target_profile.get("geography") or "regional (no specific region required)"

    return f"""TARGET PROFILE
- Sector: {target_profile['sector']}
- Deal Size: ~${target_profile['deal_size_mm']:.0f}M EV
- Profile: mid-market, private, {geography}, strong EBITDA margins

ACQUIRER DOSSIER: {dossier['acquirer']}
- Type: {dossier['acquirer_type']}
- Deals in dataset: {dossier['total_deals']} (relevant to this target's sector: {dossier['relevant_deals']})
- Deals by sector: {json.dumps(dossier['deals_by_sector'])}
- Median EV/EBITDA (closed): {dossier['median_ev_ebitda']}
- Median EV/Revenue (closed): {dossier['median_ev_revenue']}
- Median deal size: ${dossier['median_deal_size_mm']}M
- Geography spread: {json.dumps(dossier['geography_spread'])}
- Most recent deal year: {dossier['most_recent_deal_year']}

DEALS:
{deals_table}

COMPARABLE CLOSED DEALS (adjacent sectors, $100-400M)
{comps_table}

DATA-DERIVED RISK CANDIDATES
{risk_candidates}

EXTERNAL FACTS (Wikipedia, use only in acquirer_overview / risk_flags, cite source_url)
{external}

CONVICTION (deterministically computed -- do not change): {conviction_level}
Justify this level with 1-2 sentences citing the data above. The level is fixed by the \
scoring layer; your job is to explain it with the evidence, not to override it.

Return JSON matching this schema exactly -- these are the only field names to use, \
with no renaming or nesting:
{json.dumps(OUTPUT_SCHEMA, indent=2)}

external_sources: only facts you used from the EXTERNAL FACTS block above, empty if none."""
