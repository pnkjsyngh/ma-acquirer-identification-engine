"""Validation + rendering: rationale dict -> validated -> markdown/JSON on disk."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

REQUIRED_SECTIONS = [
    "conviction",
    "acquirer_overview",
    "strategic_fit_thesis",
    "precedent_activity",
    "valuation_context",
    "risk_flags",
]


def validate_rationale(rationale: dict, expected_conviction: str) -> list[str]:
    """Returns a list of validation error strings (empty = valid). Never raises --
    callers decide whether to surface a structured error or proceed with warnings."""
    errors = []
    for section in REQUIRED_SECTIONS:
        if section not in rationale:
            errors.append(f"missing section: {section}")

    if "conviction" in rationale:
        level = rationale["conviction"].get("level")
        if level not in {"High", "Medium", "Low"}:
            errors.append(f"invalid conviction level: {level!r}")
        elif level != expected_conviction:
            errors.append(f"conviction mismatch: LLM returned {level!r}, expected {expected_conviction!r}")

    if "risk_flags" in rationale:
        if len(rationale["risk_flags"]) < 2:
            errors.append(f"only {len(rationale['risk_flags'])} risk_flags, minimum 2 required")
        for i, r in enumerate(rationale["risk_flags"]):
            if "risk" not in r or "evidence" not in r:
                errors.append(f"risk_flags[{i}] missing 'risk' or 'evidence' key: {sorted(r.keys())}")

    for field in ("acquirer_overview", "strategic_fit_thesis"):
        if field in rationale and not isinstance(rationale[field], str):
            errors.append(f"{field} must be a plain string, got {type(rationale[field]).__name__}")

    if "precedent_activity" in rationale:
        for i, p in enumerate(rationale["precedent_activity"]):
            missing = [k for k in ("year", "target", "sector", "deal_size_mm", "deal_type") if k not in p]
            if missing:
                errors.append(f"precedent_activity[{i}] missing keys {missing}: has {sorted(p.keys())}")

    if "valuation_context" in rationale:
        missing = [k for k in ("median_ev_ebitda", "median_ev_revenue") if k not in rationale["valuation_context"]]
        if missing:
            errors.append(f"valuation_context missing keys {missing}")

    return errors


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def render_acquirer_markdown(rank: int, score_row: pd.Series, rationale: dict) -> str:
    conviction = rationale["conviction"]
    precedent = "\n".join(
        f"- {p['year']} | {p['target']} | {p['sector']} | ${p['deal_size_mm']:.0f}M | "
        f"{p['deal_type']} | EV/EBITDA {p.get('ev_ebitda_multiple', 'n/a')}"
        for p in rationale["precedent_activity"]
    ) or "- No directly comparable precedent transactions in the dataset."
    risks = "\n".join(f"- **{r['risk']}**: {r['evidence']}" for r in rationale["risk_flags"])
    val = rationale["valuation_context"]
    external = rationale.get("external_sources") or []
    external_block = (
        "\n\n### Sources\n" + "\n".join(f"- [{f['fact']}]({f['source_url']})" for f in external)
        if external
        else ""
    )

    return f"""# {rank}. {score_row['acquirer']} ({score_row['acquirer_type']})

**Score:** {score_row['score']:.3f} | **Conviction:** {conviction['level']}

## Conviction
{conviction['rationale']}

## Acquirer Overview
{rationale['acquirer_overview']}

## Strategic Fit Thesis
{rationale['strategic_fit_thesis']}

## Precedent Activity
{precedent}

## Valuation Context
Median EV/EBITDA: {val.get('median_ev_ebitda', 'n/a')}x | Median EV/Revenue: {val.get('median_ev_revenue', 'n/a')}x

{val.get('narrative', '')}

## Risk Flags
{risks}
{external_block}
"""


def render_summary_markdown(target_profile: dict, ranked: pd.DataFrame, rationales: dict[str, dict]) -> str:
    rows = "\n".join(
        f"| {i + 1} | {row['acquirer']} | {row['acquirer_type']} | {row['score']:.3f} | "
        f"{rationales[row['acquirer']]['conviction']['level']} | {row['relevant_deals']}/{row['total_deals']} |"
        for i, row in ranked.reset_index(drop=True).iterrows()
    )
    margin_row = ranked[ranked["margin_over_next"].notna()]
    margin_note = (
        f"\nMargin of #{len(ranked)} over #{len(ranked) + 1}: {margin_row.iloc[0]['margin_over_next']:.3f}\n"
        if len(margin_row)
        else ""
    )

    return f"""# Acquirer Ranking -- {target_profile['sector']} (~${target_profile['deal_size_mm']:.0f}M EV)

| Rank | Acquirer | Type | Score | Conviction | Relevant/Total Deals |
|---|---|---|---|---|---|
{rows}
{margin_note}
Full rationale for each acquirer is in the numbered files in this folder.
"""


def write_outputs(
    profile_slug: str,
    target_profile: dict,
    ranked: pd.DataFrame,
    rationales: dict[str, dict],
    output_dir: str | Path = "output",
) -> Path:
    out_path = Path(output_dir) / profile_slug
    out_path.mkdir(parents=True, exist_ok=True)

    (out_path / "summary.md").write_text(render_summary_markdown(target_profile, ranked, rationales))

    payload = {"target_profile": target_profile, "acquirers": []}
    for i, row in ranked.reset_index(drop=True).iterrows():
        rank = i + 1
        rationale = rationales[row["acquirer"]]
        md = render_acquirer_markdown(rank, row, rationale)
        (out_path / f"{rank:02d}_{slugify(row['acquirer'])}.md").write_text(md)
        payload["acquirers"].append(
            {
                "rank": rank,
                "acquirer": row["acquirer"],
                "acquirer_type": row["acquirer_type"],
                "score": row["score"],
                **rationale,
            }
        )

    (out_path / "results.json").write_text(json.dumps(payload, indent=2, default=str))
    return out_path
