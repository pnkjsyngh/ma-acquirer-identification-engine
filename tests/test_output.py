import asyncio
import os

import pytest

os.environ["MOCK_LLM"] = "1"

from app.data import load_transactions  # noqa: E402
from app.llm import synthesize_rationale  # noqa: E402
from app.output import render_acquirer_markdown, render_summary_markdown, validate_rationale  # noqa: E402
from app.prompts import conviction_level_for_rank  # noqa: E402
from app.ranking import build_dossier, rank_acquirers  # noqa: E402

DEFAULT_PROFILE = {"sector": "Healthcare Services", "deal_size_mm": 200, "geography": None}


@pytest.fixture(scope="module")
def df():
    return load_transactions()


@pytest.fixture(scope="module")
def ranked_and_dossiers(df):
    ranked, deal_fit_df = rank_acquirers(df, DEFAULT_PROFILE, top_n=3)
    return ranked, deal_fit_df


def test_mock_rationale_passes_validation(ranked_and_dossiers):
    ranked, deal_fit_df = ranked_and_dossiers
    row = ranked.iloc[0]
    dossier = build_dossier(deal_fit_df, row["acquirer"], DEFAULT_PROFILE)
    conviction_level = conviction_level_for_rank(1)
    rationale = asyncio.run(synthesize_rationale(DEFAULT_PROFILE, dossier, conviction_level, []))
    errors = validate_rationale(rationale, conviction_level)
    assert errors == []


def test_conviction_matches_rank():
    assert conviction_level_for_rank(1) == "High"
    assert conviction_level_for_rank(3) == "High"
    assert conviction_level_for_rank(4) == "Medium"
    assert conviction_level_for_rank(7) == "Medium"
    assert conviction_level_for_rank(8) == "Low"
    assert conviction_level_for_rank(10) == "Low"


def test_validate_rationale_flags_missing_sections():
    errors = validate_rationale({"conviction": {"level": "High", "rationale": "x"}}, "High")
    assert any("missing section" in e for e in errors)


def test_validate_rationale_flags_conviction_mismatch():
    rationale = {
        "conviction": {"level": "Low", "rationale": "x"},
        "acquirer_overview": "x",
        "strategic_fit_thesis": "x",
        "precedent_activity": [],
        "valuation_context": {},
        "risk_flags": [{"risk": "a", "evidence": "b"}, {"risk": "c", "evidence": "d"}],
    }
    errors = validate_rationale(rationale, "High")
    assert any("mismatch" in e for e in errors)


def test_validate_rationale_flags_insufficient_risk_flags():
    rationale = {
        "conviction": {"level": "High", "rationale": "x"},
        "acquirer_overview": "x",
        "strategic_fit_thesis": "x",
        "precedent_activity": [],
        "valuation_context": {},
        "risk_flags": [{"risk": "a", "evidence": "b"}],
    }
    errors = validate_rationale(rationale, "High")
    assert any("minimum 2" in e for e in errors)


def test_render_acquirer_markdown_includes_all_sections(ranked_and_dossiers):
    ranked, deal_fit_df = ranked_and_dossiers
    row = ranked.iloc[0]
    dossier = build_dossier(deal_fit_df, row["acquirer"], DEFAULT_PROFILE)
    rationale = asyncio.run(synthesize_rationale(DEFAULT_PROFILE, dossier, "High", []))
    md = render_acquirer_markdown(1, row, rationale)
    for heading in ["Conviction", "Acquirer Overview", "Strategic Fit Thesis", "Precedent Activity", "Valuation Context", "Risk Flags"]:
        assert heading in md


def test_render_summary_markdown_lists_all_acquirers(ranked_and_dossiers):
    ranked, deal_fit_df = ranked_and_dossiers
    rationales = {}
    for i, row in ranked.reset_index(drop=True).iterrows():
        dossier = build_dossier(deal_fit_df, row["acquirer"], DEFAULT_PROFILE)
        rationales[row["acquirer"]] = asyncio.run(
            synthesize_rationale(DEFAULT_PROFILE, dossier, conviction_level_for_rank(i + 1), [])
        )
    summary = render_summary_markdown(DEFAULT_PROFILE, ranked, rationales)
    for _, row in ranked.iterrows():
        assert row["acquirer"] in summary
