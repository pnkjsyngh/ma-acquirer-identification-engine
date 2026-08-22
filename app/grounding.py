"""Deterministic grounding checks: verify LLM-cited structured fields trace back to the
CSV-derived dossier the LLM was actually given. No LLM calls -- reruns the same
deterministic pipeline (ranking.rank_acquirers / ranking.build_dossier) used at generation
time and diffs the rationale against it. Free-text number extraction (numbers embedded in
prose like acquirer_overview/risk_flags evidence) is explicitly out of scope here -- see
plan.md's Stretch item for a fuller citation validator.
"""

from __future__ import annotations

import difflib

import pandas as pd

from app.ranking import build_dossier, rank_acquirers

DEAL_SIZE_TOLERANCE_MM = 0.5
MULTIPLE_TOLERANCE = 0.15
DUPLICATE_SIMILARITY_THRESHOLD = 0.85


def _row_lookup(deal_fit_df: pd.DataFrame, acquirer: str) -> dict[tuple[str, int], int]:
    """Maps (target_company, deal_year) -> 1-based CSV row number for this acquirer's
    deals. Matches on (target, year) -- confirmed unique per acquirer in the dataset (no
    acquirer buys the same target twice in the same year)."""
    acquirer_deals = deal_fit_df[deal_fit_df["acquirer"] == acquirer]
    # +1 for the header line, +1 to go from 0-based pandas index to 1-based CSV row.
    return {(r.target_company, r.deal_year): idx + 2 for idx, r in acquirer_deals.iterrows()}


def annotate_precedent_activity(precedent_activity: list[dict], deal_fit_df: pd.DataFrame, acquirer: str) -> list[dict]:
    """Attach csv_row (1-based CSV line number, None if unmatched) to each cited item --
    used both for display (rendered in the acquirer markdown/JSON output) and for
    grounding checks below, so the row-matching logic lives in one place."""
    row_lookup = _row_lookup(deal_fit_df, acquirer)
    return [{**item, "csv_row": row_lookup.get((item["target"], item["year"]))} for item in precedent_activity]


def _citation_mismatches(item: dict, real) -> list[str]:
    """Compares a cited precedent_activity item against the real deal it matched --
    `real` is either a dossier deals_table dict or a deal_fit_df row (pandas Series),
    both support the same `[key]` access, so this works for either caller."""
    mismatches = []
    if abs(item["deal_size_mm"] - real["deal_size_mm"]) > DEAL_SIZE_TOLERANCE_MM:
        mismatches.append(f"deal_size_mm {item['deal_size_mm']} vs actual {real['deal_size_mm']}")
    if item["sector"] != real["sector"]:
        mismatches.append(f"sector {item['sector']!r} vs actual {real['sector']!r}")
    if item["deal_type"] != real["deal_type"]:
        mismatches.append(f"deal_type {item['deal_type']!r} vs actual {real['deal_type']!r}")
    return mismatches


def check_precedent_activity(rationale: dict, deal_fit_df: pd.DataFrame, acquirer: str) -> list[dict]:
    """Returns one result dict per cited precedent_activity item: the item's own fields
    plus csv_row, ok, and error. Used for the offline/CI eval (app/grounding.py's
    check_run), where a CSV row number is available and useful for spot-checking."""
    acquirer_deals = deal_fit_df[deal_fit_df["acquirer"] == acquirer]
    deals_by_row = {idx + 2: r for idx, r in acquirer_deals.iterrows()}

    results = []
    for item in annotate_precedent_activity(rationale.get("precedent_activity", []), deal_fit_df, acquirer):
        csv_row = item["csv_row"]
        if csv_row is None:
            results.append({**item, "ok": False, "error": "no matching deal in CSV"})
            continue
        mismatches = _citation_mismatches(item, deals_by_row[csv_row])
        results.append({**item, "ok": not mismatches, "error": "; ".join(mismatches) if mismatches else None})
    return results


def check_precedent_activity_against_dossier(precedent_activity: list[dict], dossier: dict) -> list[str]:
    """Same grounding check as check_precedent_activity, but against a dossier dict
    instead of deal_fit_df -- used inside Stage 2's generation-time retry loop
    (app/llm.py), where the dossier is in scope but the CSV row index isn't. A
    fabricated or mismatched citation here becomes a validation error that triggers
    the existing retry-with-correction path, the same way schema violations already do.
    """
    real_by_key = {(d["target_company"], d["deal_year"]): d for d in dossier["deals_table"]}
    errors = []
    for item in precedent_activity:
        key = (item.get("target"), item.get("year"))
        real = real_by_key.get(key)
        if real is None:
            errors.append(f"precedent_activity cites {item.get('target')!r} ({item.get('year')}) -- no matching deal in dossier")
            continue
        mismatches = _citation_mismatches(item, real)
        if mismatches:
            errors.append(f"precedent_activity {item.get('target')!r} ({item.get('year')}): {'; '.join(mismatches)}")
    return errors


def check_valuation_medians(rationale: dict, dossier: dict) -> list[str]:
    """valuation_context medians must match the dossier's deterministically-computed
    values (this acquirer's own closed-deal medians, see ranking.build_dossier). Stage 2
    is a full LLM call that retypes these into JSON rather than the code injecting them,
    so this checks a real risk, not a redundant one.
    """
    errors = []
    val = rationale.get("valuation_context", {})
    for field in ("median_ev_ebitda", "median_ev_revenue"):
        cited, actual = val.get(field), dossier.get(field)
        if actual is None or cited is None:
            continue
        if abs(cited - actual) > MULTIPLE_TOLERANCE:
            errors.append(f"{field}: cited {cited} vs actual {actual}")
    return errors


def check_near_duplicate_text(rationales: dict[str, dict]) -> list[str]:
    """Flag acquirer pairs whose overview/thesis prose is suspiciously similar --
    a sign of templated, non-acquirer-specific LLM output rather than a real citation
    error."""
    errors = []
    names = list(rationales)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            for field in ("acquirer_overview", "strategic_fit_thesis"):
                ratio = difflib.SequenceMatcher(None, rationales[a][field], rationales[b][field]).ratio()
                if ratio > DUPLICATE_SIMILARITY_THRESHOLD:
                    errors.append(f"{field}: {a} vs {b} similarity {ratio:.2f}")
    return errors


def check_run(df: pd.DataFrame, results: dict) -> dict[str, list]:
    """Top-level entry point: given the loaded CSV and a saved results.json payload,
    return {acquirer: [errors]} for any acquirer with grounding issues, plus a "_run"
    key for cross-acquirer checks (near-duplicate text). Empty dict means fully grounded.
    """
    target_profile = results["target_profile"]
    acquirers = results["acquirers"]
    _, deal_fit_df = rank_acquirers(df, target_profile, top_n=len(acquirers))
    rationales = {a["acquirer"]: a for a in acquirers}

    out: dict[str, list] = {}
    for acquirer, rationale in rationales.items():
        dossier = build_dossier(deal_fit_df, acquirer, target_profile)
        precedent_results = check_precedent_activity(rationale, deal_fit_df, acquirer)
        errors = [r["error"] for r in precedent_results if not r["ok"]]
        errors += check_valuation_medians(rationale, dossier)
        if errors:
            out[acquirer] = errors

    dup_errors = check_near_duplicate_text(rationales)
    if dup_errors:
        out["_run"] = dup_errors
    return out
