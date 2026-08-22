import os

os.environ["MOCK_LLM"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.output import REQUIRED_SECTIONS  # noqa: E402
from app.server import app  # noqa: E402

client = TestClient(app)


def test_rank_known_profile_returns_full_rationale():
    response = client.post("/rank", json={"slug": "healthcare_services_200mm"})
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["elapsed_seconds"], (int, float))
    assert len(body["acquirers"]) == 10
    for acquirer in body["acquirers"]:
        for section in REQUIRED_SECTIONS:
            assert section in acquirer
        assert "rank" in acquirer
        assert "acquirer" in acquirer
        assert "acquirer_type" in acquirer
        assert "score" in acquirer


def test_rank_unknown_slug_returns_4xx_not_500():
    response = client.post("/rank", json={"slug": "not-a-real-slug"})
    assert 400 <= response.status_code < 500
    assert "detail" in response.json()


def test_index_returns_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert len(response.text) > 0
