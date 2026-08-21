import pytest

from app.data import load_transactions
from app.ranking import build_dossier, rank_acquirers

DEFAULT_PROFILE = {"sector": "Healthcare Services", "deal_size_mm": 200, "geography": None}


@pytest.fixture(scope="module")
def df():
    return load_transactions()


def test_rank_acquirers_returns_top_n_sorted_desc(df):
    top, _ = rank_acquirers(df, DEFAULT_PROFILE, top_n=10)
    assert len(top) == 10
    assert list(top["score"]) == sorted(top["score"], reverse=True)


def test_no_tiny_firm_dominance(df):
    """An acquirer with fewer than the eligibility threshold (3) relevant deals must
    have confidence < 1, so a single lucky deal can't outrank a real track record."""
    top, _ = rank_acquirers(df, DEFAULT_PROFILE, top_n=10)
    thin = top[top["relevant_deals"] < 3]
    assert (thin["confidence"] < 1.0).all()


def test_healthcare_services_top3_regression(df):
    """Regression check on the validated Healthcare Services top-10 (see sanity pass
    in the build plan). The exact-sector strategics should lead the list."""
    top, _ = rank_acquirers(df, DEFAULT_PROFILE, top_n=10)
    assert set(top["acquirer"].head(3)) == {"Atrium Health", "UPMC", "Steward Health Care"}


def test_ranking_is_target_sensitive(df):
    """Changing the target sector should change the top-10 substantially -- guards
    against the 'always the same PE mega-funds' failure mode."""
    hs_top, _ = rank_acquirers(df, DEFAULT_PROFILE, top_n=10)
    hit_top, _ = rank_acquirers(df, {"sector": "Health IT", "deal_size_mm": 150, "geography": None}, top_n=10)
    overlap = len(set(hs_top["acquirer"]) & set(hit_top["acquirer"]))
    assert overlap <= 3


def test_build_dossier_has_required_fields(df):
    top, deal_fit_df = rank_acquirers(df, DEFAULT_PROFILE, top_n=10)
    dossier = build_dossier(deal_fit_df, top.iloc[0]["acquirer"], DEFAULT_PROFILE)
    for key in ("acquirer", "total_deals", "deals_table", "comparable_closed_deals", "risk_candidates"):
        assert key in dossier
    assert dossier["total_deals"] > 0
