"""Deterministic two-tier acquirer ranking.

Tier 1 (features.py): per-deal fit to the target profile.
Tier 2 (here): roll deals up to an acquirer, weighted by recency and outcome quality,
then apply a simple eligibility dampener so an acquirer with a single lucky deal can't
outrank a firm with a genuine track record -- a 1-deal specialist would otherwise score
~0.9 on fit alone.
"""

from __future__ import annotations

import pandas as pd

from app.features import (
    RELEVANT_SECTOR_FIT_THRESHOLD,
    ELIGIBILITY_DEAL_COUNT,
    build_cooccurrence_matrix,
    build_sector_similarity,
    compute_deal_fit,
)


def rank_acquirers(
    df: pd.DataFrame,
    target_profile: dict,
    top_n: int = 10,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (ranked_acquirers, deal_fit_df).

    ranked_acquirers: one row per acquirer, sorted desc by score, with a `margin_over_next`
    column on the last included row showing the gap to #(top_n + 1).
    deal_fit_df: the full deal-level frame with fit signals attached (used to build
    per-acquirer dossiers for the LLM layer).
    """
    cooccurrence = build_cooccurrence_matrix(df)
    similarity = build_sector_similarity(cooccurrence)
    deal_fit_df = compute_deal_fit(df, target_profile, similarity)

    deal_fit_df["weight"] = deal_fit_df["recency_score"] * deal_fit_df["outcome_quality_score"]
    deal_fit_df["relevant"] = deal_fit_df["sector_fit"] >= RELEVANT_SECTOR_FIT_THRESHOLD

    rows = []
    for acquirer, group in deal_fit_df.groupby("acquirer"):
        total_weight = group["weight"].sum()
        if total_weight > 0:
            fit_weighted = (group["deal_fit"] * group["weight"]).sum() / total_weight
        else:
            fit_weighted = group["deal_fit"].mean()

        relevant_deals = int(group["relevant"].sum())
        confidence = min(1.0, relevant_deals / ELIGIBILITY_DEAL_COUNT)
        score = fit_weighted * confidence

        rows.append(
            {
                "acquirer": acquirer,
                "acquirer_type": group["acquirer_type"].mode().iat[0],
                "score": score,
                "fit_weighted": fit_weighted,
                "confidence": confidence,
                "relevant_deals": relevant_deals,
                "total_deals": len(group),
            }
        )

    ranked = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)

    if len(ranked) > top_n:
        margin = float(ranked.loc[top_n - 1, "score"] - ranked.loc[top_n, "score"])
    else:
        margin = float("nan")
    ranked["margin_over_next"] = None
    if len(ranked) > top_n:
        ranked.loc[top_n - 1, "margin_over_next"] = margin

    top = ranked.head(top_n).copy()
    return top, deal_fit_df


def build_dossier(deal_fit_df: pd.DataFrame, acquirer: str, target_profile: dict) -> dict:
    """Evidence dossier for one acquirer: deals, aggregates, and comparable closed deals --
    everything the LLM synthesis layer is allowed to cite."""
    deals = deal_fit_df[deal_fit_df["acquirer"] == acquirer].sort_values("deal_year", ascending=False)

    closed = deals[deals["outcome"] == "Closed"]
    comps = deal_fit_df[
        (deal_fit_df["outcome"] == "Closed")
        & (deal_fit_df["sector_fit"] >= RELEVANT_SECTOR_FIT_THRESHOLD)
        & (deal_fit_df["deal_size_mm"].between(100, 400))
    ]

    withdrawn_terminated = deals[deals["outcome"].isin(["Withdrawn", "Terminated"])]
    large_deals = deals[deals["deal_size_mm"] >= 300]
    carve_outs = deals[deals["deal_type"] == "Carve-out"]
    high_bidder_deals = deals[deals["num_bidders"] >= 5]

    risk_candidates = []
    if len(withdrawn_terminated) > 0:
        risk_candidates.append(
            f"{len(withdrawn_terminated)} of this acquirer's deals in the dataset were withdrawn or terminated"
        )
    if len(large_deals) > 0:
        risk_candidates.append(
            f"{len(large_deals)} deals at $300M+ EV in the dataset -- antitrust/regulatory scrutiny scales with deal size"
        )
    if len(carve_outs) > 0:
        risk_candidates.append(f"{len(carve_outs)} carve-out deals -- integration/standalone-cost complexity")
    if len(high_bidder_deals) > 0:
        risk_candidates.append(
            f"{len(high_bidder_deals)} deals with 5+ bidders -- this acquirer operates in competitive processes"
        )

    return {
        "acquirer": acquirer,
        "acquirer_type": deals["acquirer_type"].mode().iat[0] if len(deals) else None,
        "total_deals": len(deals),
        "relevant_deals": int((deals["sector_fit"] >= RELEVANT_SECTOR_FIT_THRESHOLD).sum()),
        "deals_by_sector": deals["sector"].value_counts().to_dict(),
        "median_ev_ebitda": float(closed["ev_ebitda_multiple"].median()) if len(closed) else None,
        "median_ev_revenue": float(closed["ev_revenue_multiple"].median()) if len(closed) else None,
        "median_deal_size_mm": float(deals["deal_size_mm"].median()) if len(deals) else None,
        "geography_spread": deals["geography"].value_counts().to_dict(),
        "most_recent_deal_year": int(deals["deal_year"].max()) if len(deals) else None,
        "deals_table": deals[
            [
                "deal_year",
                "target_company",
                "sector",
                "deal_size_mm",
                "deal_type",
                "geography",
                "ev_ebitda_multiple",
                "ev_revenue_multiple",
                "ebitda_margin_pct",
                "revenue_growth_pct",
                "outcome",
                "strategic_rationale_tags",
            ]
        ].to_dict("records"),
        "comparable_closed_deals": comps[
            ["target_company", "acquirer", "sector", "deal_size_mm", "deal_type", "ev_ebitda_multiple", "ev_revenue_multiple"]
        ]
        .head(15)
        .to_dict("records"),
        "risk_candidates": risk_candidates,
    }
