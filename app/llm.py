"""Anthropic adapter: one async call per acquirer, run concurrently via asyncio.gather.

MOCK_LLM=1 substitutes a deterministic canned rationale (built straight from the
dossier, no network call) so the pipeline runs end-to-end with zero API keys --
this is also what test_output.py exercises.
"""

from __future__ import annotations

import json
import os
import re

from app.output import validate_rationale
from app.prompts import OUTPUT_SCHEMA, SYSTEM_PROMPT, build_user_prompt

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")


class RationaleGenerationError(Exception):
    """Raised when the LLM output can't be coerced into valid JSON after one retry."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    # Strip ```json ... ``` fences if the model wrapped its output despite instructions.
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    return json.loads(text)


_FALLBACK_RISKS = [
    {"risk": "Limited precedent activity", "evidence": "[MOCK] few directly relevant deals in dataset"},
    {"risk": "Competitive process risk", "evidence": "[MOCK] deal history shows multi-bidder processes"},
]


def _mock_risk_flags(dossier: dict) -> list[dict]:
    flags = [{"risk": r, "evidence": "[MOCK] data-derived"} for r in dossier["risk_candidates"]]
    for fallback in _FALLBACK_RISKS:
        if len(flags) >= 2:
            break
        flags.append(fallback)
    return flags[:4]


def _mock_rationale(target_profile: dict, dossier: dict, conviction_level: str, external_facts: list[dict]) -> dict:
    sector = target_profile["sector"]
    deals = dossier["deals_table"][:3]
    return {
        "conviction": {
            "level": conviction_level,
            "rationale": (
                f"[MOCK] {dossier['relevant_deals']} of {dossier['total_deals']} deals are relevant to "
                f"{sector}, with a median EV/EBITDA of {dossier['median_ev_ebitda']}x on closed deals."
            ),
        },
        "acquirer_overview": (
            f"[MOCK] {dossier['acquirer']} is a {dossier['acquirer_type']} with {dossier['total_deals']} "
            f"transactions in the dataset, most recently in {dossier['most_recent_deal_year']}."
        ),
        "strategic_fit_thesis": (
            f"[MOCK] {dossier['acquirer']}'s deal history in {list(dossier['deals_by_sector'].keys())} "
            f"aligns with a ~${target_profile['deal_size_mm']:.0f}M {sector} target."
        ),
        "precedent_activity": [
            {
                "year": d["deal_year"],
                "target": d["target_company"],
                "sector": d["sector"],
                "deal_size_mm": d["deal_size_mm"],
                "deal_type": d["deal_type"],
                "ev_ebitda_multiple": d["ev_ebitda_multiple"],
            }
            for d in deals
        ],
        "valuation_context": {
            "median_ev_ebitda": dossier["median_ev_ebitda"],
            "median_ev_revenue": dossier["median_ev_revenue"],
            "comparable_deal_ids": [c["target_company"] for c in dossier["comparable_closed_deals"][:3]],
            "narrative": f"[MOCK] Comparable closed deals cluster around {dossier['median_ev_ebitda']}x EV/EBITDA.",
        },
        "risk_flags": _mock_risk_flags(dossier),
        "external_sources": [
            {"fact": f["text"], "source_url": f["source_url"], "kind": "wikipedia"} for f in external_facts[:2]
        ],
    }


async def synthesize_rationale(
    target_profile: dict,
    dossier: dict,
    conviction_level: str,
    external_facts: list[dict],
) -> dict:
    if os.environ.get("MOCK_LLM") == "1":
        return _mock_rationale(target_profile, dossier, conviction_level, external_facts)

    import anthropic

    client = anthropic.AsyncAnthropic()
    user_prompt = build_user_prompt(target_profile, dossier, conviction_level, external_facts)

    async def _call(extra: str = "") -> str:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=2000,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt + extra}],
        )
        return response.content[0].text

    raw = await _call()
    try:
        parsed = _extract_json(raw)
        errors = validate_rationale(parsed, conviction_level)
    except json.JSONDecodeError:
        parsed = None
        errors = [f"could not parse response as JSON:\n{raw}"]

    if parsed is not None and not errors:
        return parsed

    retry_suffix = (
        f"\n\nYour previous response had these problems: {'; '.join(errors)}\n\n"
        f"Return ONLY valid JSON matching this schema exactly (exact key names, no "
        f"renaming or nesting), no other text:\n{json.dumps(OUTPUT_SCHEMA)}"
    )
    raw_retry = await _call(retry_suffix)
    try:
        parsed_retry = _extract_json(raw_retry)
    except json.JSONDecodeError as e:
        raise RationaleGenerationError(
            f"Could not parse LLM output as JSON for {dossier['acquirer']} after retry: {e}"
        ) from e
    errors_retry = validate_rationale(parsed_retry, conviction_level)
    if errors_retry:
        raise RationaleGenerationError(
            f"LLM output still invalid for {dossier['acquirer']} after retry: {errors_retry}"
        )
    return parsed_retry
