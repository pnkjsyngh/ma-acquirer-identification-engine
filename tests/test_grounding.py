import asyncio
import os

import pytest

os.environ["MOCK_LLM"] = "1"

from app.data import load_transactions  # noqa: E402
from app.grounding import (  # noqa: E402
    check_near_duplicate_text,
    check_precedent_activity,
    check_run,
    check_valuation_medians,
)
from app.llm import synthesize_rationale  # noqa: E402
from app.output import write_outputs  # noqa: E402
from app.prompts import conviction_level_for_rank  # noqa: E402
from app.ranking import build_dossier, rank_acquirers  # noqa: E402

DEFAULT_PROFILE = {"sector": "Healthcare Services", "deal_size_mm": 200, "geography": None}


@pytest.fixture(scope="module")
def df():
    return load_transactions()


@pytest.fixture(scope="module")
def ranked_and_dossiers(df):
    return rank_acquirers(df, DEFAULT_PROFILE, top_n=3)


def test_check_precedent_activity_passes_for_real_deal(ranked_and_dossiers):
    ranked, deal_fit_df = ranked_and_dossiers
    acquirer = ranked.iloc[0]["acquirer"]
    dossier = build_dossier(deal_fit_df, acquirer, DEFAULT_PROFILE)
    real_deal = dossier["deals_table"][0]
    rationale = {
        "precedent_activity": [
            {
                "year": real_deal["deal_year"],
                "target": real_deal["target_company"],
                "sector": real_deal["sector"],
                "deal_size_mm": real_deal["deal_size_mm"],
                "deal_type": real_deal["deal_type"],
            }
        ]
    }
    results = check_precedent_activity(rationale, deal_fit_df, acquirer)
    assert len(results) == 1
    assert results[0]["ok"]
    assert results[0]["csv_row"] is not None


def test_check_precedent_activity_flags_fabricated_deal(ranked_and_dossiers):
    ranked, deal_fit_df = ranked_and_dossiers
    acquirer = ranked.iloc[0]["acquirer"]
    rationale = {
        "precedent_activity": [
            {
                "year": 1999,
                "target": "Not A Real Target",
                "sector": "Nowhere",
                "deal_size_mm": 1.0,
                "deal_type": "Made Up",
            }
        ]
    }
    results = check_precedent_activity(rationale, deal_fit_df, acquirer)
    assert results[0]["ok"] is False
    assert results[0]["csv_row"] is None


def test_check_precedent_activity_flags_wrong_deal_size(ranked_and_dossiers):
    ranked, deal_fit_df = ranked_and_dossiers
    acquirer = ranked.iloc[0]["acquirer"]
    dossier = build_dossier(deal_fit_df, acquirer, DEFAULT_PROFILE)
    real_deal = dossier["deals_table"][0]
    rationale = {
        "precedent_activity": [
            {
                "year": real_deal["deal_year"],
                "target": real_deal["target_company"],
                "sector": real_deal["sector"],
                "deal_size_mm": real_deal["deal_size_mm"] + 50,
                "deal_type": real_deal["deal_type"],
            }
        ]
    }
    results = check_precedent_activity(rationale, deal_fit_df, acquirer)
    assert results[0]["ok"] is False
    assert "deal_size_mm" in results[0]["error"]


def test_check_valuation_medians_passes_for_matching_value(ranked_and_dossiers):
    ranked, deal_fit_df = ranked_and_dossiers
    dossier = build_dossier(deal_fit_df, ranked.iloc[0]["acquirer"], DEFAULT_PROFILE)
    rationale = {
        "valuation_context": {
            "median_ev_ebitda": dossier["median_ev_ebitda"],
            "median_ev_revenue": dossier["median_ev_revenue"],
        }
    }
    assert check_valuation_medians(rationale, dossier) == []


def test_check_valuation_medians_flags_mismatch(ranked_and_dossiers):
    ranked, deal_fit_df = ranked_and_dossiers
    dossier = build_dossier(deal_fit_df, ranked.iloc[0]["acquirer"], DEFAULT_PROFILE)
    rationale = {"valuation_context": {"median_ev_ebitda": (dossier["median_ev_ebitda"] or 0) + 5, "median_ev_revenue": None}}
    errors = check_valuation_medians(rationale, dossier)
    assert any("median_ev_ebitda" in e for e in errors)


def test_check_near_duplicate_text_flags_identical_prose():
    rationales = {
        "A": {"acquirer_overview": "This acquirer has a long transaction history.", "strategic_fit_thesis": "x"},
        "B": {"acquirer_overview": "This acquirer has a long transaction history.", "strategic_fit_thesis": "y"},
    }
    errors = check_near_duplicate_text(rationales)
    assert any("acquirer_overview" in e for e in errors)


def test_check_near_duplicate_text_passes_for_distinct_prose():
    rationales = {
        "A": {"acquirer_overview": "Alpha Corp has acquired three healthcare companies since 2019.", "strategic_fit_thesis": "x"},
        "B": {"acquirer_overview": "Beta Partners focuses on industrials with a 2021 carve-out.", "strategic_fit_thesis": "y"},
    }
    assert check_near_duplicate_text(rationales) == []


def test_check_run_passes_structured_checks_on_mock_generated_output(df, ranked_and_dossiers, tmp_path):
    """Mock rationale copies precedent_activity/valuation_context verbatim from the
    dossier (see llm.py::_mock_stage2) -- this is a regression guard that check_run's
    per-acquirer structured checks don't false-positive on genuinely grounded output,
    and exercises the full check_run wiring end to end without any live API calls.

    Excludes the "_run" near-duplicate-text key: mock prose is intentionally templated
    boilerplate across acquirers ("[MOCK] {acquirer} is a {type} with..."), so it
    legitimately trips near-duplicate detection -- that's covered by its own unit tests
    above with realistic distinct/duplicate prose instead.
    """
    ranked, deal_fit_df = ranked_and_dossiers
    rationales = {}
    for i, row in ranked.reset_index(drop=True).iterrows():
        dossier = build_dossier(deal_fit_df, row["acquirer"], DEFAULT_PROFILE)
        rationales[row["acquirer"]] = asyncio.run(
            synthesize_rationale(DEFAULT_PROFILE, dossier, conviction_level_for_rank(i + 1), [])
        )

    out_path = write_outputs("test-grounding", DEFAULT_PROFILE, ranked, rationales, output_dir=tmp_path)
    import json

    results = json.loads((out_path / "results.json").read_text())

    per_acquirer_errors = {k: v for k, v in check_run(df, results).items() if k != "_run"}
    assert per_acquirer_errors == {}
