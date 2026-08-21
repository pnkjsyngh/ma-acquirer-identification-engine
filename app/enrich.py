"""One-time offline enrichment: Wikipedia summaries for all acquirers, committed to
data/enrichment_cache.json. Runtime (main.py) reads this cache only -- no network
dependency during a `rank` run, so results are fully offline and reproducible.

Acquirers are real companies (targets in the CSV are semi-fictional), so Wikipedia
lookups are valid for acquirers and must never be attempted for targets.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

from app.data import DEFAULT_CSV_PATH, load_transactions

DEFAULT_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "enrichment_cache.json"
WIKI_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKI_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "ma-acquirer-engine/1.0 (take-home assessment prototype)"


def _clean_name(name: str) -> str:
    """Strip parenthetical suffixes like 'Aspen Dental (ADMI)' -> 'Aspen Dental'."""
    return re.sub(r"\s*\([^)]*\)", "", name).strip()


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _title_matches(query: str, title: str) -> bool:
    nq, nt = _normalize(query), _normalize(title)
    return bool(nq) and bool(nt) and (nq in nt or nt in nq)


# A same-named unrelated topic (armored vehicle, footwear retailer, traffic-engineering
# term, ...) is worse than no external fact at all for a banker-facing document. This is
# a coarse but cheap guard: the page must both title-match the acquirer name AND read
# like a business entity, not just resolve to *a* Wikipedia page with that name.
_BUSINESS_KEYWORDS = (
    "company", "companies", "corporation", "corp.", "firm", "business", "inc.",
    "llc", "ltd", "healthcare", "health care", "hospital", "provider",
    "manufacturer", "pharmaceutical", "biotechnology", "biotech",
    "private equity", "investment", "asset management", "software",
    "technology", "insurer", "insurance", "retailer", "retail chain",
    "health system", "medical device", "clinic", "practice management",
    "platform", "saas", "bank", "financial services", "conglomerate",
    "multinational", "operator", "provider of", "developer of",
)


def _looks_like_business(description: str, extract: str) -> bool:
    text = f"{description or ''} {extract or ''}".lower()
    return any(kw in text for kw in _BUSINESS_KEYWORDS)


def _get_with_backoff(url: str, params: dict | None = None, max_retries: int = 4) -> requests.Response:
    delay = 2.0
    for attempt in range(max_retries):
        resp = requests.get(url, params=params, timeout=10, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 429:
            return resp
        time.sleep(delay)
        delay *= 2
    return resp


def _fetch_summary(query: str, title: str) -> dict | None:
    resp = _get_with_backoff(WIKI_SUMMARY_URL.format(title=requests.utils.quote(title)))
    if resp.status_code != 200:
        return None
    data = resp.json()
    if data.get("type") == "disambiguation":
        return None
    extract = data.get("extract")
    if not extract:
        return None
    # Reject raw wiki-template leakage (e.g. infobox-only stubs like "| website = ... }}")
    # -- not prose, unusable and would look broken in a rationale.
    if extract.strip().startswith("|") or "}}" in extract or "{{" in extract:
        return None
    resolved_title = data.get("title", title)
    if not _title_matches(query, resolved_title):
        return None
    if not _looks_like_business(data.get("description", ""), extract):
        return None
    url = data.get("content_urls", {}).get("desktop", {}).get("page") or f"https://en.wikipedia.org/wiki/{title}"
    return {"text": extract, "source_url": url}


def _search_title(query: str) -> str | None:
    resp = _get_with_backoff(
        WIKI_SEARCH_URL,
        params={"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 1},
    )
    if resp.status_code != 200:
        return None
    results = resp.json().get("query", {}).get("search", [])
    return results[0]["title"] if results else None


# Acquirers manually confirmed (by inspection) to only match an unrelated same-named
# Wikipedia article, despite passing the automated title/business-keyword filters --
# e.g. "Headway" (the mental-health company in this dataset) has no Wikipedia article
# of its own; the only candidate is an unrelated "Headway Inc" ed-tech company. Common,
# short, genericish company names are the main blind spot the automated filter can't
# close without a dataset-specific industry crosswalk.
KNOWN_MISMATCHES = {"Headway"}


def enrich_acquirer(name: str) -> dict | None:
    if name in KNOWN_MISMATCHES:
        return None
    clean = _clean_name(name)
    for candidate in dict.fromkeys([name, clean]):  # dedupe, preserve order
        result = _fetch_summary(clean, candidate)
        if result:
            return result
    searched = _search_title(f"{clean} company")
    if searched:
        result = _fetch_summary(clean, searched)
        if result:
            return result
    return None


def enrich_all(acquirers: list[str], delay_seconds: float = 0.3, existing: dict | None = None) -> dict:
    """Resumable: acquirers already present in `existing` are skipped (not re-fetched)."""
    cache = dict(existing or {})
    for name in acquirers:
        if name in cache:
            continue
        fact = enrich_acquirer(name)
        if fact:
            cache[name] = {"facts": [{"text": fact["text"], "source_url": fact["source_url"], "kind": "wikipedia"}]}
        time.sleep(delay_seconds)
    return cache


def load_enrichment_cache(path: Path | str = DEFAULT_CACHE_PATH) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def get_external_facts(acquirer: str, cache: dict, max_facts: int = 2) -> list[dict]:
    entry = cache.get(acquirer)
    if not entry:
        return []
    return entry.get("facts", [])[:max_facts]


def main() -> None:
    df = load_transactions(DEFAULT_CSV_PATH)
    acquirers = sorted(df["acquirer"].unique())
    existing = load_enrichment_cache()
    cache = enrich_all(acquirers, existing=existing)
    DEFAULT_CACHE_PATH.write_text(json.dumps(cache, indent=2))
    print(f"Enriched {len(cache)}/{len(acquirers)} acquirers -> {DEFAULT_CACHE_PATH}")


if __name__ == "__main__":
    main()
