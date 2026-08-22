"""CLI entrypoint.

  python -m app rank --profile healthcare_services_200mm
  python -m app rank --sector "Healthcare Services" --deal-size-mm 200
  python -m app rank --all-profiles
  python -m app enrich
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from app import tracing
from app.data import DEFAULT_CSV_PATH, load_transactions
from app.enrich import get_external_facts, load_enrichment_cache
from app.evidence import compute_adjacent_candidates
from app.features import ELIGIBILITY_DEAL_COUNT
from app.grounding import annotate_precedent_activity
from app.llm import synthesize_rationale
from app.output import validate_rationale, write_outputs
from app.prompts import conviction_level_for_rank
from app.ranking import build_dossier, rank_acquirers

logger = logging.getLogger(__name__)

PROFILES_PATH = Path(__file__).resolve().parent.parent / "data" / "synthetic_profiles.json"


def load_profiles() -> list[dict]:
    return json.loads(PROFILES_PATH.read_text())


def resolve_profile(slug: str | None, sector: str | None, deal_size_mm: float | None, geography: str | None) -> dict:
    if slug:
        profiles = {p["slug"]: p for p in load_profiles()}
        if slug not in profiles:
            raise SystemExit(f"Unknown profile slug: {slug!r}. Available: {sorted(profiles)}")
        return profiles[slug]
    if not sector or not deal_size_mm:
        raise SystemExit("Provide --profile <slug>, or both --sector and --deal-size-mm")
    return {"sector": sector, "deal_size_mm": deal_size_mm, "geography": geography}


def default_slug(target_profile: dict) -> str:
    def clean(s: str) -> str:
        return s.lower().replace("/", "-").replace(" ", "_")

    parts = [clean(target_profile["sector"]), f"{target_profile['deal_size_mm']:g}mm"]
    if target_profile.get("geography"):
        parts.append(clean(target_profile["geography"]))
    return "_".join(parts)


async def run_profile(
    df,
    target_profile: dict,
    enrichment_cache: dict,
    top_n: int,
    output_dir: str,
    slug: str,
) -> Path:
    started = time.time()
    logger.info(
        "Starting ranking for %s (~$%.0fM, slug=%s)",
        target_profile["sector"],
        target_profile["deal_size_mm"],
        slug,
    )

    ranking_started = time.time()
    ranked, deal_fit_df = rank_acquirers(df, target_profile, top_n=top_n)
    logger.info("Ranked top %d acquirers in %.2fs", top_n, time.time() - ranking_started)

    async def _one(rank: int, row) -> tuple[str, dict, str | None, str | None]:
        acquirer = row["acquirer"]
        dossier = build_dossier(deal_fit_df, acquirer, target_profile)
        dossier["thin_evidence"] = dossier["relevant_deals"] < ELIGIBILITY_DEAL_COUNT
        dossier["adjacent_candidate_deals"] = compute_adjacent_candidates(deal_fit_df, acquirer, target_profile)
        conviction_level = conviction_level_for_rank(rank)
        external_facts = get_external_facts(acquirer, enrichment_cache)
        with tracing.start_observation("span", f"acquirer:{acquirer}"):
            trace_id, observation_id = tracing.current_ids()
            rationale = await synthesize_rationale(target_profile, dossier, conviction_level, external_facts)
        errors = validate_rationale(rationale, conviction_level, dossier=dossier)
        if errors:
            print(f"  [warn] {acquirer}: {'; '.join(errors)}", file=sys.stderr)
        rationale["precedent_activity"] = annotate_precedent_activity(
            rationale["precedent_activity"], deal_fit_df, acquirer
        )
        return acquirer, rationale, trace_id, observation_id

    logger.info("Synthesizing rationale for %d acquirers concurrently...", top_n)
    with tracing.start_observation("span", f"run_profile:{slug}"):
        # Tasks must be created (asyncio.gather -> ensure_future) while this span is the
        # active context -- asyncio copies the current contextvars at task-creation time,
        # which is how each acquirer's nested span below ends up parented under this one
        # instead of becoming its own root trace.
        tasks = [_one(i + 1, row) for i, row in ranked.reset_index(drop=True).iterrows()]
        results = await asyncio.gather(*tasks)
    rationales = {acquirer: rationale for acquirer, rationale, _, _ in results}
    trace_ids = {acquirer: (trace_id, obs_id) for acquirer, _, trace_id, obs_id in results}

    elapsed = time.time() - started
    out_path = write_outputs(
        slug,
        target_profile,
        ranked,
        rationales,
        output_dir=output_dir,
        elapsed_seconds=elapsed,
        trace_ids=trace_ids,
    )
    logger.info("Total time for %s: %.2fs", slug, elapsed)
    print(f"{target_profile['sector']} (~${target_profile['deal_size_mm']:.0f}M) -> {out_path} ({elapsed:.1f}s)")
    return out_path


def main() -> None:
    from app.logging_config import configure_logging

    configure_logging()

    parser = argparse.ArgumentParser(prog="python -m app")
    sub = parser.add_subparsers(dest="command", required=True)

    rank_p = sub.add_parser("rank", help="Rank acquirers for a target profile")
    rank_p.add_argument("--profile", help="Synthetic profile slug from data/synthetic_profiles.json")
    rank_p.add_argument("--sector")
    rank_p.add_argument("--deal-size-mm", type=float)
    rank_p.add_argument("--geography", default=None)
    rank_p.add_argument("--top-n", type=int, default=2)
    rank_p.add_argument("--output-dir", default="output")
    rank_p.add_argument("--all-profiles", action="store_true", help="Run every profile in synthetic_profiles.json")

    sub.add_parser("enrich", help="Pre-fetch Wikipedia summaries for all acquirers (one-time, offline after)")

    serve_p = sub.add_parser("serve", help="Run the minimal web UI")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()

    if args.command == "enrich":
        from app.enrich import main as enrich_main

        enrich_main()
        return

    if args.command == "serve":
        import uvicorn

        from app.server import app as web_app

        uvicorn.run(web_app, host=args.host, port=args.port)
        return

    df = load_transactions(DEFAULT_CSV_PATH)
    enrichment_cache = load_enrichment_cache()

    if args.all_profiles:
        # Single asyncio.run() for the whole sweep, not one per profile -- the shared
        # LLM clients in app.llm are module-level singletons bound to whichever event
        # loop created them, so a fresh asyncio.run() per profile broke the second
        # profile onward with "RuntimeError: Event loop is closed" (confirmed live).
        async def _run_all() -> None:
            for profile in load_profiles():
                await run_profile(df, profile, enrichment_cache, args.top_n, args.output_dir, slug=profile["slug"])

        asyncio.run(_run_all())
        tracing.flush()
        return

    target_profile = resolve_profile(args.profile, args.sector, args.deal_size_mm, args.geography)
    slug = args.profile or default_slug(target_profile)
    asyncio.run(run_profile(df, target_profile, enrichment_cache, args.top_n, args.output_dir, slug=slug))
    tracing.flush()


if __name__ == "__main__":
    main()
