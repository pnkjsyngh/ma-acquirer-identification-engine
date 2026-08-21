"""Adjacent-sector candidate deals for widening thin evidence."""

from __future__ import annotations

import pandas as pd

from app.features import RELEVANT_SECTOR_FIT_THRESHOLD

ADJACENT_SECTOR_FIT_MIN = 0.15
MAX_ADJACENT_CANDIDATES = 5


def compute_adjacent_candidates(
    deal_fit_df: pd.DataFrame,
    acquirer: str,
    target_profile: dict,
) -> list[dict]:
    """Deals for this acquirer in sectors adjacent to (but not already counted as
    relevant to) the target sector -- candidates for widening thin evidence."""
    matches = deal_fit_df[deal_fit_df["acquirer"] == acquirer]
    adjacent = matches[
        (matches["sector_fit"] >= ADJACENT_SECTOR_FIT_MIN)
        & (matches["sector_fit"] < RELEVANT_SECTOR_FIT_THRESHOLD)
    ]
    adjacent = adjacent.sort_values(["sector_fit", "deal_year"], ascending=False).head(
        MAX_ADJACENT_CANDIDATES
    )
    return adjacent[
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
    ].to_dict("records")
