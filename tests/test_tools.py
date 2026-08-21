import pytest

from app.evidence import compute_adjacent_candidates
from app.features import RELEVANT_SECTOR_FIT_THRESHOLD
from app.data import load_transactions
from app.ranking import build_dossier, rank_acquirers
from app.tools import (
    TOOL_SCHEMAS,
    execute_tool,
    get_precedent_deals,
    get_rationale_tag_overlap,
    get_valuation_comps,
    widen_to_adjacent_sector,
)

DEFAULT_PROFILE = {"sector": "Healthcare Services", "deal_size_mm": 200, "geography": None}


@pytest.fixture(scope="module")
def df():
    return load_transactions()


@pytest.fixture(scope="module")
def ranked_and_deal_fit(df):
    return rank_acquirers(df, DEFAULT_PROFILE, top_n=10)


@pytest.fixture(scope="module")
def sample_dossier(ranked_and_deal_fit):
    ranked, deal_fit_df = ranked_and_deal_fit
    acquirer = ranked.iloc[0]["acquirer"]
    dossier = build_dossier(deal_fit_df, acquirer, DEFAULT_PROFILE)
    dossier["adjacent_candidate_deals"] = compute_adjacent_candidates(deal_fit_df, acquirer, DEFAULT_PROFILE)
    return dossier


def test_tool_schemas_shape():
    assert len(TOOL_SCHEMAS) == 4
    for schema in TOOL_SCHEMAS:
        assert "name" in schema
        assert "description" in schema
        assert schema["input_schema"]["type"] == "object"
        assert schema["input_schema"]["additionalProperties"] is False


def test_get_precedent_deals_filters_by_sector(sample_dossier):
    all_deals = get_precedent_deals(sample_dossier)
    assert all_deals == sample_dossier["deals_table"]
    sectors = {d["sector"] for d in all_deals}
    if len(sectors) > 1:
        one_sector = next(iter(sectors))
        filtered = get_precedent_deals(sample_dossier, sector=one_sector)
        assert filtered and all(d["sector"] == one_sector for d in filtered)


def test_get_precedent_deals_filters_by_min_year(sample_dossier):
    all_deals = sample_dossier["deals_table"]
    if not all_deals:
        pytest.skip("no deals for this acquirer")
    min_year = max(d["deal_year"] for d in all_deals)
    filtered = get_precedent_deals(sample_dossier, min_year=min_year)
    assert all(d["deal_year"] >= min_year for d in filtered)


def test_get_valuation_comps_filters_by_sector(sample_dossier):
    comps = get_valuation_comps(sample_dossier)
    assert comps == sample_dossier["comparable_closed_deals"]


def test_get_rationale_tag_overlap_counts_and_overlap(sample_dossier):
    result = get_rationale_tag_overlap(sample_dossier, DEFAULT_PROFILE)
    assert "tag_counts" in result
    assert "overlapping_tags" in result
    assert set(result["overlapping_tags"]).issubset(set(result["tag_counts"]))


def test_widen_to_adjacent_sector_returns_precomputed_candidates(sample_dossier):
    assert widen_to_adjacent_sector(sample_dossier) == sample_dossier["adjacent_candidate_deals"]


def test_execute_tool_dispatches_correctly(sample_dossier):
    result = execute_tool("get_precedent_deals", {}, sample_dossier, DEFAULT_PROFILE)
    assert result == sample_dossier["deals_table"]


def test_execute_tool_unknown_name_raises(sample_dossier):
    with pytest.raises(ValueError):
        execute_tool("not_a_real_tool", {}, sample_dossier, DEFAULT_PROFILE)


def test_compute_adjacent_candidates_band_and_cap(ranked_and_deal_fit):
    ranked, deal_fit_df = ranked_and_deal_fit
    acquirer = ranked.iloc[0]["acquirer"]
    candidates = compute_adjacent_candidates(deal_fit_df, acquirer, DEFAULT_PROFILE)
    assert len(candidates) <= 5

    matches = deal_fit_df[deal_fit_df["acquirer"] == acquirer]
    for c in candidates:
        row = matches[
            (matches["deal_year"] == c["deal_year"]) & (matches["target_company"] == c["target_company"])
        ].iloc[0]
        assert 0.15 <= row["sector_fit"] < RELEVANT_SECTOR_FIT_THRESHOLD
