from app.main import default_slug


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
