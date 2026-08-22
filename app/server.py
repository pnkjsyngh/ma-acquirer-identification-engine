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
import os
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
from app.main import compare_profiles, default_slug, resolve_profile, run_profile

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

# Module-level so tests can redirect writes (e.g. to tmp_path) without touching real run output.
# Also reads OUTPUT_DIR from the environment so a manual/ad-hoc smoke test (curl, a throwaway
# script) has a trivial way to redirect writes too, e.g. `OUTPUT_DIR=/tmp/smoketest MOCK_LLM=1
# uvicorn app.server:app` -- this app has repeatedly clobbered real generated output at the
# default path during manual debugging; the env var makes redirecting the obvious default action
# instead of something that has to be remembered.
_OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
_COMPARE_TOP_N = 3


class RankRequest(BaseModel):
    slug: str | None = None
    sector: str | None = None
    deal_size_mm: float | None = None
    geography: str | None = None


class FeedbackRequest(BaseModel):
    trace_id: str | None = None
    observation_id: str | None = None
    relevant: bool = True
    comment: str | None = None


class CompareRequest(BaseModel):
    slug_a: str
    slug_b: str


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
        out_path = await run_profile(_df, target_profile, _enrichment_cache, top_n=2, output_dir=_OUTPUT_DIR, slug=slug)
    except RationaleGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    return json.loads((out_path / "results.json").read_text())


@app.post("/compare")
async def compare(request: CompareRequest) -> dict:
    logger.info("Received /compare request: %s", request.model_dump())
    try:
        profile_a = resolve_profile(request.slug_a, None, None, None)
        profile_b = resolve_profile(request.slug_b, None, None, None)
    except SystemExit as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    try:
        await compare_profiles(
            _df, profile_a, profile_b, _enrichment_cache, _COMPARE_TOP_N, _OUTPUT_DIR, request.slug_a, request.slug_b
        )
    except RationaleGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    results_a = json.loads((Path(_OUTPUT_DIR) / request.slug_a / "results.json").read_text())
    results_b = json.loads((Path(_OUTPUT_DIR) / request.slug_b / "results.json").read_text())
    names_a = {a["acquirer"] for a in results_a["acquirers"]}
    names_b = {a["acquirer"] for a in results_b["acquirers"]}
    overlap = sorted(names_a & names_b)

    return {
        "profile_a": results_a,
        "profile_b": results_b,
        "overlap": {"count": len(overlap), "total": max(len(names_a), len(names_b)), "acquirers": overlap},
    }


@app.post("/feedback")
async def feedback(request: FeedbackRequest) -> dict:
    recorded = tracing.create_score(request.trace_id, request.observation_id, request.relevant, request.comment)
    return {"recorded": recorded}
