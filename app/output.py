"""Validation + rendering: rationale dict -> validated -> markdown/JSON on disk."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from app.grounding import check_precedent_activity_against_dossier
from app.schemas import RationaleOutput

REQUIRED_SECTIONS = [
    "conviction",
    "acquirer_overview",
    "strategic_fit_thesis",
    "precedent_activity",
    "valuation_context",
    "risk_flags",
]


def validate_rationale(rationale: dict, expected_conviction: str, dossier: dict | None = None) -> list[str]:
    """Returns a list of validation error strings (empty = valid). Never raises --
    callers decide whether to surface a structured error or proceed with warnings.

    Structural/type checks are backed by RationaleOutput (Pydantic); conviction-match
    is checked directly against the raw dict since it's a business rule ("must equal
    the deterministically-computed level") that a schema alone can't express. Passing
    `dossier` also grounds precedent_activity citations against real CSV-derived deals
    (app/llm.py's retry loop calls this with the dossier so a fabricated citation is
    treated the same as a schema violation -- it triggers a retry, not a silent pass).
    """
    errors = []
    if dossier is not None:
        errors.extend(check_precedent_activity_against_dossier(rationale.get("precedent_activity", []), dossier))
    for section in REQUIRED_SECTIONS:
        if section not in rationale:
            errors.append(f"missing section: {section}")

    conviction = rationale.get("conviction")
    if isinstance(conviction, dict):
        level = conviction.get("level")
        if level not in {"High", "Medium", "Low"}:
            errors.append(f"invalid conviction level: {level!r}")
        elif level != expected_conviction:
            errors.append(f"conviction mismatch: LLM returned {level!r}, expected {expected_conviction!r}")

    try:
        RationaleOutput.model_validate(rationale)
    except ValidationError as e:
        already_reported = {msg.split(": ", 1)[1] for msg in errors if msg.startswith("missing section: ")}
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"])
            if err["type"] == "missing":
                if loc in already_reported:
                    continue
                errors.append(f"missing field: {loc}")
            elif loc == "risk_flags":
                actual = len(rationale.get("risk_flags") or [])
                errors.append(f"only {actual} risk_flags, minimum 2 required")
            elif loc.startswith("risk_flags."):
                idx = loc.split(".")[1]
                errors.append(f"risk_flags[{idx}] invalid: {err['msg']}")
            elif loc in ("acquirer_overview", "strategic_fit_thesis"):
                errors.append(f"{loc} must be a plain string: {err['msg']}")
            else:
                errors.append(f"{loc}: {err['msg']}")

    return errors


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def render_acquirer_markdown(rank: int, score_row: pd.Series, rationale: dict) -> str:
    conviction = rationale["conviction"]
    precedent = "\n".join(
        f"- {p['year']} | {p['target']} | {p['sector']} | ${p['deal_size_mm']:.0f}M | "
        f"{p['deal_type']} | EV/EBITDA {p.get('ev_ebitda_multiple', 'n/a')} | "
        f"CSV row {p['csv_row'] if p.get('csv_row') is not None else 'NOT FOUND'}"
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
    elapsed_seconds: float | None = None,
    trace_ids: dict[str, tuple[str | None, str | None]] | None = None,
) -> Path:
    out_path = Path(output_dir) / profile_slug
    out_path.mkdir(parents=True, exist_ok=True)

    (out_path / "summary.md").write_text(render_summary_markdown(target_profile, ranked, rationales))

    payload = {"target_profile": target_profile, "elapsed_seconds": elapsed_seconds, "acquirers": []}
    for i, row in ranked.reset_index(drop=True).iterrows():
        rank = i + 1
        rationale = rationales[row["acquirer"]]
        md = render_acquirer_markdown(rank, row, rationale)
        (out_path / f"{rank:02d}_{slugify(row['acquirer'])}.md").write_text(md)
        trace_id, observation_id = (trace_ids or {}).get(row["acquirer"], (None, None))
        payload["acquirers"].append(
            {
                "rank": rank,
                "acquirer": row["acquirer"],
                "acquirer_type": row["acquirer_type"],
                "score": row["score"],
                **rationale,
                "trace_id": trace_id,
                "observation_id": observation_id,
            }
        )

    (out_path / "results.json").write_text(json.dumps(payload, indent=2, default=str))
    return out_path
