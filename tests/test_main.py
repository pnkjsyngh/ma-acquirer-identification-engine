import asyncio
import os

os.environ["MOCK_LLM"] = "1"

from app.data import load_transactions  # noqa: E402
from app.enrich import load_enrichment_cache  # noqa: E402
from app.main import compare_profiles, default_slug, load_profiles, resolve_profile  # noqa: E402


def test_default_slug_distinguishes_by_deal_size():
    a = default_slug({"sector": "Medical Devices", "deal_size_mm": 300, "geography": "Midwest"})
    b = default_slug({"sector": "Medical Devices", "deal_size_mm": 150, "geography": None})
    assert a != b


def test_default_slug_distinguishes_by_geography():
    a = default_slug({"sector": "Medical Devices", "deal_size_mm": 300, "geography": "Midwest"})
    b = default_slug({"sector": "Medical Devices", "deal_size_mm": 300, "geography": "West Coast"})
    assert a != b


def test_default_slug_no_trailing_zero_for_whole_numbers():
    slug = default_slug({"sector": "Dental", "deal_size_mm": 80, "geography": None})
    assert slug == "dental_80mm"


def test_default_slug_omits_geography_when_absent():
    slug = default_slug({"sector": "Dental", "deal_size_mm": 80, "geography": None})
    assert "none" not in slug


def test_synthetic_profile_slugs_match_default_slug_convention():
    """Named profiles' stored slugs must match what default_slug() would derive from their
    own sector/deal_size_mm/geography -- keeps the two naming schemes from drifting apart."""
    for profile in load_profiles():
        assert profile["slug"] == default_slug(profile)


def test_compare_profiles_writes_comparison_and_both_profile_outputs(tmp_path):
    df = load_transactions()
    enrichment_cache = load_enrichment_cache()
    slug_a, slug_b = "healthcare_services_200mm", "health_it_150mm_national"
    profile_a = resolve_profile(slug_a, None, None, None)
    profile_b = resolve_profile(slug_b, None, None, None)

    compare_path = asyncio.run(
        compare_profiles(df, profile_a, profile_b, enrichment_cache, top_n=3, output_dir=str(tmp_path), slug_a=slug_a, slug_b=slug_b)
    )

    assert (compare_path / "comparison.md").exists()
    assert (tmp_path / slug_a / "results.json").exists()
    assert (tmp_path / slug_b / "results.json").exists()
