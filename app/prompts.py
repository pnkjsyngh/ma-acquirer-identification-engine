"""Prompt construction for the two-stage per-acquirer LLM synthesis.

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
7. Two-stage cost split -- Stage 1 (Anthropic) is the only stage that calls tools or
   decides whether to widen to adjacent sectors; its prompt stays short and cheap.
   Stage 2 (bulk prose) never sees tool schemas and never re-decides anything Stage 1
   already settled -- it writes from a finalized dossier + Stage 1's reasoning trace.
"""

from __future__ import annotations

import json

from app.schemas import RationaleOutput

OUTPUT_SCHEMA = RationaleOutput.model_json_schema()

STAGE1_SYSTEM_PROMPT = """You are an M&A research associate preparing evidence for a \
colleague who will write the final acquirer rationale. Your job is only to gather and \
assess evidence for one acquirer against one target profile -- you do not write the \
rationale yourself.

Hard rules:
- Use the tools to pull whatever deal history, valuation comps, or tag-overlap data you \
need. Do not assume data you haven't retrieved via a tool call.
- Only call widen_to_adjacent_sector if thin_evidence is true AND the deals already \
visible are genuinely insufficient to support a rationale. Calling it unconditionally, \
or when there is already enough relevant evidence, is wrong -- the point is that this \
is a real decision, not a reflex.
- When you are done gathering evidence, respond with ONLY a JSON object (no other text, \
no markdown fences) with exactly these fields: `reasoning` (string -- your assessment of \
the evidence quality and what it supports), `used_widen` (boolean), `sectors_widened` \
(array of strings, empty if used_widen is false), `notes` (string, empty string if \
nothing else to flag).
"""

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
- A "STAGE 1 EVIDENCE REVIEW" block, if present, is grounding context from an earlier \
evidence-gathering pass -- use it to inform your prose, but do not treat it as \
something to re-decide or override (evidence scope and sector widening are already \
final by the time you see this).
"""


def conviction_level_for_rank(rank: int) -> str:
    """Conviction is a deterministic function of rank position -- the LLM justifies
    it, it never sets it."""
    if rank <= 3:
        return "High"
    if rank <= 7:
        return "Medium"
    return "Low"


def build_stage1_prompt(target_profile: dict, dossier: dict) -> str:
    """Condensed summary, not the full dossier dump -- Stage 1's job is to decide what
    to look at via tools, not to draft prose, so its input and output both stay small
    and cheap (this is the expensive-model call in the two-stage split)."""
    geography = target_profile.get("geography") or "regional (no specific region required)"
    return f"""TARGET PROFILE
- Sector: {target_profile['sector']}
- Deal Size: ~${target_profile['deal_size_mm']:.0f}M EV
- Profile: mid-market, private, {geography}, strong EBITDA margins

ACQUIRER: {dossier['acquirer']} ({dossier['acquirer_type']})
- Total deals in dataset: {dossier['total_deals']}
- Relevant to this target's sector: {dossier['relevant_deals']}
- thin_evidence: {str(dossier.get('thin_evidence', False)).lower()}

Use the tools available to you to gather whatever precedent deals, valuation comps, or \
tag-overlap evidence you need to assess fit. If thin_evidence is true and what's visible \
isn't enough, consider widen_to_adjacent_sector. When you're done, respond with the \
required JSON decision object and nothing else."""


def build_stage2_prompt(
    target_profile: dict,
    dossier: dict,
    conviction_level: str,
    external_facts: list[dict],
    stage1_reasoning: str = "",
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
    stage1_block = f"\nSTAGE 1 EVIDENCE REVIEW\n{stage1_reasoning}\n" if stage1_reasoning else ""
    widened_note = (
        f"\nNOTE: evidence was widened to include adjacent sectors: {', '.join(dossier.get('widened_sectors', []))}\n"
        if dossier.get("widened")
        else ""
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
{widened_note}
DEALS:
{deals_table}

COMPARABLE CLOSED DEALS (adjacent sectors, $100-400M)
{comps_table}

DATA-DERIVED RISK CANDIDATES
{risk_candidates}

EXTERNAL FACTS (Wikipedia, use only in acquirer_overview / risk_flags, cite source_url)
{external}
{stage1_block}
CONVICTION (deterministically computed -- do not change): {conviction_level}
Justify this level with 1-2 sentences citing the data above. The level is fixed by the \
scoring layer; your job is to explain it with the evidence, not to override it.

Return JSON matching this schema exactly -- these are the only field names to use, \
with no renaming or nesting:
{json.dumps(OUTPUT_SCHEMA, indent=2)}

external_sources: only facts you used from the EXTERNAL FACTS block above, empty if none."""


# Backward-compatible alias -- earlier revision of this module named this build_user_prompt.
build_user_prompt = build_stage2_prompt
