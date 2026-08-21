import numpy as np
import pytest

from app.data import load_transactions
from app.features import (
    build_cooccurrence_matrix,
    build_sector_similarity,
    geography_score,
    margin_score,
    ownership_score,
    recency,
    sector_fit,
    size_fit,
    tag_alignment,
)


@pytest.fixture(scope="module")
def df():
    return load_transactions()


@pytest.fixture(scope="module")
def similarity(df):
    return build_sector_similarity(build_cooccurrence_matrix(df))


def test_sector_similarity_is_symmetric_with_unit_diagonal(similarity):
    assert np.allclose(similarity.values, similarity.values.T, atol=1e-9)
    assert np.allclose(np.diag(similarity.values), 1.0)


def test_exact_sector_match_scores_1(similarity):
    assert sector_fit("Healthcare Services", "Healthcare Services", similarity) == 1.0


def test_generalist_pe_downweight_sharpens_adjacency(similarity):
    # Without the IDF-style downweight in build_sector_similarity, Dental and
    # Pharma/Biotech look artificially "adjacent" because a handful of generalist
    # PE mega-funds transact in both. The downweight should pull this well under
    # the 0.35 relevance threshold used by ranking.py.
    assert similarity.loc["Dental", "Pharma/Biotech"] < 0.35


def test_size_fit_peaks_at_target_size():
    assert size_fit(200, 200) == pytest.approx(1.0)
    assert size_fit(20, 200) < size_fit(100, 200) < size_fit(200, 200)
    assert size_fit(2000, 200) < size_fit(400, 200)


def test_recency_decays_with_age():
    assert recency(2024, 2024) == pytest.approx(1.0)
    assert recency(2021, 2024) == pytest.approx(0.5)
    assert recency(2015, 2024) < recency(2021, 2024)


def test_ownership_score_prefers_private_and_pe_backed():
    assert ownership_score("Private") == 1.0
    assert ownership_score("PE-Backed") == 1.0
    assert ownership_score("Public") == 0.5


def test_geography_score_generic_target_rewards_specific_region():
    assert geography_score("Southeast", None) == 1.0
    assert geography_score("National", None) == 0.5
    assert geography_score("Multi-Regional", None) == 0.75


def test_geography_score_specific_target_rewards_exact_match():
    assert geography_score("Southeast", "Southeast") == 1.0
    assert geography_score("Northeast", "Southeast") == 0.3


def test_margin_score_bounded_0_1():
    assert margin_score(50, 0, 100) == pytest.approx(0.5)
    assert margin_score(-10, 0, 100) == 0.0
    assert margin_score(150, 0, 100) == 1.0


def test_tag_alignment_counts_overlap():
    thesis = ["Platform Build", "Geographic Expansion", "Scale"]
    assert tag_alignment(["Platform Build", "Geographic Expansion"], thesis) == pytest.approx(2 / 3)
    assert tag_alignment([], thesis) == 0.0
