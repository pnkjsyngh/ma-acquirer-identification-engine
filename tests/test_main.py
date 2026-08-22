from app.main import default_slug, load_profiles


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
