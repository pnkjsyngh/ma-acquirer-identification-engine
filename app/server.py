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
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app import tracing
from app.data import DEFAULT_CSV_PATH, load_transactions
from app.enrich import load_enrichment_cache
from app.llm import RationaleGenerationError
from app.logging_config import configure_logging
from app.main import default_slug, resolve_profile, run_profile

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    yield
    tracing.flush()


app = FastAPI(lifespan=_lifespan)

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


class FeedbackRequest(BaseModel):
    trace_id: str | None = None
    observation_id: str | None = None
    flagged: bool = True


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _INDEX_HTML_PATH.read_text()


@app.post("/rank")
async def rank(request: RankRequest) -> dict:
    logger.info("Received /rank request: %s", request.model_dump(exclude_none=True))
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


@app.post("/feedback")
async def feedback(request: FeedbackRequest) -> dict:
    recorded = tracing.create_score(request.trace_id, request.observation_id, request.flagged)
    return {"recorded": recorded}
