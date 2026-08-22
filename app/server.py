"""Minimal FastAPI web UI on top of the existing CLI pipeline.

Reuses app.main's resolve_profile/default_slug/run_profile verbatim -- this file adds an HTTP
layer, it does not duplicate any ranking/LLM orchestration logic.

IMPORTANT: never call asyncio.run() in a route handler. Uvicorn already owns one persistent event
loop for the life of the server process; app.llm's shared clients (_get_anthropic_client,
_get_opencode_client) are singletons bound to whichever loop first created them. This is the exact
class of bug that broke --all-profiles when it called asyncio.run() once per profile ("RuntimeError:
Event loop is closed" from the second profile onward) -- route handlers must stay `async def` and
`await` directly into run_profile, never wrap it in a fresh event loop.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.data import DEFAULT_CSV_PATH, load_transactions
from app.enrich import load_enrichment_cache
from app.llm import RationaleGenerationError
from app.main import default_slug, resolve_profile, run_profile

app = FastAPI()

# Loaded once at import time, not per-request -- mirrors main() loading these once before
# dispatching to rank/--all-profiles.
_df = load_transactions(DEFAULT_CSV_PATH)
_enrichment_cache = load_enrichment_cache()

_INDEX_HTML_PATH = Path(__file__).resolve().parent / "web" / "index.html"


class RankRequest(BaseModel):
    slug: str | None = None
    sector: str | None = None
    deal_size_mm: float | None = None
    geography: str | None = None


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _INDEX_HTML_PATH.read_text()


@app.post("/rank")
async def rank(request: RankRequest) -> dict:
    try:
        target_profile = resolve_profile(request.slug, request.sector, request.deal_size_mm, request.geography)
    except SystemExit as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    slug = request.slug or default_slug(target_profile)

    try:
        out_path = await run_profile(_df, target_profile, _enrichment_cache, top_n=10, output_dir="output", slug=slug)
    except RationaleGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    return json.loads((out_path / "results.json").read_text())
