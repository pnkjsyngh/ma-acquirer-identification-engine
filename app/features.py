"""Deterministic signal computation: sector adjacency (data-derived) and per-deal fit signals.

Sector adjacency is intentionally *not* a hand-tuned prior. It's the cosine similarity
of acquirer overlap between two sectors (computed from the sector x acquirer
co-occurrence matrix), i.e. "do the same buyers transact in both sectors." This is a
proxy for sector adjacency, not true sector similarity, but it's derived from the data
and it's per-target -- it doesn't need to be recentered by hand for a new target sector.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

DEFAULT_THESIS_TAGS = ["Platform Build", "Geographic Expansion", "Scale"]

OUTCOME_QUALITY = {
    "Closed": 1.0,
    "Pending": 0.6,
    "Rumored": 0.4,
    "Withdrawn": 0.2,
    "Terminated": 0.2,
}

WEIGHTS = {
    "sector_fit": 0.30,
    "size_fit": 0.25,
    "profile_fit": 0.20,
    "recency": 0.10,
    "outcome_quality": 0.10,
    "tag_alignment": 0.05,
}

RELEVANT_SECTOR_FIT_THRESHOLD = 0.35
ELIGIBILITY_DEAL_COUNT = 3


def build_cooccurrence_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """sector x acquirer matrix of deal counts."""
    return pd.crosstab(df["sector"], df["acquirer"])


def build_sector_similarity(cooccurrence: pd.DataFrame) -> pd.DataFrame:
    """Cosine similarity between sector rows of the co-occurrence matrix, with an
    IDF-style downweight on acquirers active across many sectors.

    Without this, generalist mega-funds active in 8-10 of the 10 sectors dominate every
    sector's count vector and inflate cosine similarity between *all* sector pairs
    uniformly (a Dental-only specialist ends up looking "relevant" to Pharma/Biotech).
    Downweighting each acquirer by how many sectors they appear in sharpens the signal
    down to sector-specific buyer overlap -- still fully data-derived, no hand-tuned
    prior or constant.
    """
    mat = cooccurrence.values.astype(float)
    n_sectors = mat.shape[0]
    sectors_per_acquirer = (mat > 0).sum(axis=0)
    idf = np.log((n_sectors + 1) / (sectors_per_acquirer + 1)) + 1.0
    weighted = mat * idf

    norms = np.linalg.norm(weighted, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normed = weighted / norms
    sim = normed @ normed.T
    return pd.DataFrame(sim, index=cooccurrence.index, columns=cooccurrence.index)


def sector_fit(target_sector: str, deal_sector: str, similarity: pd.DataFrame) -> float:
    if deal_sector == target_sector:
        return 1.0
    if target_sector not in similarity.index or deal_sector not in similarity.columns:
        return 0.0
    return float(similarity.loc[target_sector, deal_sector])


def size_fit(deal_size_mm: float, target_size_mm: float) -> float:
    if deal_size_mm <= 0 or target_size_mm <= 0:
        return 0.0
    distance = abs(math.log10(deal_size_mm / target_size_mm))
    return max(0.0, 1.0 - min(1.0, distance))


def margin_score(ebitda_margin_pct: float, margin_min: float, margin_max: float) -> float:
    if margin_max == margin_min:
        return 0.5
    return max(0.0, min(1.0, (ebitda_margin_pct - margin_min) / (margin_max - margin_min)))


def ownership_score(target_ownership_pre: str) -> float:
    return 1.0 if target_ownership_pre in {"Private", "PE-Backed"} else 0.5


def geography_score(deal_geography: str, target_geography: str | None) -> float:
    """target_geography=None means the target only specifies 'regional' generically
    (not a specific region) -- any specific region is treated as a full match."""
    if target_geography:
        if deal_geography == target_geography:
            return 1.0
        if deal_geography == "Multi-Regional":
            return 0.75
        if deal_geography == "National":
            return 0.6
        return 0.3
    if deal_geography == "National":
        return 0.5
    if deal_geography == "Multi-Regional":
        return 0.75
    return 1.0


def profile_fit(row: pd.Series, target_profile: dict, margin_min: float, margin_max: float) -> float:
    m = margin_score(row["ebitda_margin_pct"], margin_min, margin_max)
    o = ownership_score(row["target_ownership_pre"])
    g = geography_score(row["geography"], target_profile.get("geography"))
    return (m + o + g) / 3


def recency(deal_year: int, max_year: int, half_life_years: float = 3.0) -> float:
    return 0.5 ** ((max_year - deal_year) / half_life_years)


def outcome_quality(outcome: str) -> float:
    return OUTCOME_QUALITY.get(outcome, 0.2)


def tag_alignment(deal_tags: list[str], thesis_tags: list[str]) -> float:
    if not thesis_tags:
        return 0.0
    overlap = len(set(deal_tags) & set(thesis_tags))
    return overlap / len(thesis_tags)


def compute_deal_fit(
    df: pd.DataFrame,
    target_profile: dict,
    similarity: pd.DataFrame,
) -> pd.DataFrame:
    """Adds per-signal columns and a composite `deal_fit` column to a copy of df."""
    out = df.copy()
    target_sector = target_profile["sector"]
    target_size = target_profile["deal_size_mm"]
    thesis_tags = target_profile.get("thesis_tags", DEFAULT_THESIS_TAGS)
    max_year = int(df["deal_year"].max())
    margin_min = float(df["ebitda_margin_pct"].min())
    margin_max = float(df["ebitda_margin_pct"].max())

    out["sector_fit"] = out["sector"].apply(lambda s: sector_fit(target_sector, s, similarity))
    out["size_fit"] = out["deal_size_mm"].apply(lambda v: size_fit(v, target_size))
    out["profile_fit"] = out.apply(lambda r: profile_fit(r, target_profile, margin_min, margin_max), axis=1)
    out["recency_score"] = out["deal_year"].apply(lambda y: recency(y, max_year))
    out["outcome_quality_score"] = out["outcome"].apply(outcome_quality)
    out["tag_alignment_score"] = out["strategic_rationale_tags"].apply(lambda t: tag_alignment(t, thesis_tags))

    out["deal_fit"] = (
        WEIGHTS["sector_fit"] * out["sector_fit"]
        + WEIGHTS["size_fit"] * out["size_fit"]
        + WEIGHTS["profile_fit"] * out["profile_fit"]
        + WEIGHTS["recency"] * out["recency_score"]
        + WEIGHTS["outcome_quality"] * out["outcome_quality_score"]
        + WEIGHTS["tag_alignment"] * out["tag_alignment_score"]
    )
    return out
