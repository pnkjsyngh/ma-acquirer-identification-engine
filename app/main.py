"""CLI entrypoint.

  python -m app rank --profile healthcare_services_default
  python -m app rank --sector "Healthcare Services" --deal-size-mm 200
  python -m app rank --all-profiles
  python -m app enrich
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from app.data import DEFAULT_CSV_PATH, load_transactions
from app.enrich import get_external_facts, load_enrichment_cache
from app.evidence import compute_adjacent_candidates
from app.features import ELIGIBILITY_DEAL_COUNT
from app.llm import synthesize_rationale
from app.output import validate_rationale, write_outputs
from app.prompts import conviction_level_for_rank
from app.ranking import build_dossier, rank_acquirers

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
    return target_profile["sector"].lower().replace("/", "-").replace(" ", "_")


async def run_profile(
    df,
    target_profile: dict,
    enrichment_cache: dict,
    top_n: int,
    output_dir: str,
    slug: str,
) -> Path:
    started = time.time()
    ranked, deal_fit_df = rank_acquirers(df, target_profile, top_n=top_n)

    async def _one(rank: int, row) -> tuple[str, dict]:
        acquirer = row["acquirer"]
        dossier = build_dossier(deal_fit_df, acquirer, target_profile)
        dossier["thin_evidence"] = dossier["relevant_deals"] < ELIGIBILITY_DEAL_COUNT
        dossier["adjacent_candidate_deals"] = compute_adjacent_candidates(deal_fit_df, acquirer, target_profile)
        conviction_level = conviction_level_for_rank(rank)
        external_facts = get_external_facts(acquirer, enrichment_cache)
        rationale = await synthesize_rationale(target_profile, dossier, conviction_level, external_facts)
        errors = validate_rationale(rationale, conviction_level)
        if errors:
            print(f"  [warn] {acquirer}: {'; '.join(errors)}", file=sys.stderr)
        return acquirer, rationale

    tasks = [_one(i + 1, row) for i, row in ranked.reset_index(drop=True).iterrows()]
    results = await asyncio.gather(*tasks)
    rationales = dict(results)

    out_path = write_outputs(slug, target_profile, ranked, rationales, output_dir=output_dir)
    elapsed = time.time() - started
    print(f"{target_profile['sector']} (~${target_profile['deal_size_mm']:.0f}M) -> {out_path} ({elapsed:.1f}s)")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app")
    sub = parser.add_subparsers(dest="command", required=True)

    rank_p = sub.add_parser("rank", help="Rank acquirers for a target profile")
    rank_p.add_argument("--profile", help="Synthetic profile slug from data/synthetic_profiles.json")
    rank_p.add_argument("--sector")
    rank_p.add_argument("--deal-size-mm", type=float)
    rank_p.add_argument("--geography", default=None)
    rank_p.add_argument("--top-n", type=int, default=10)
    rank_p.add_argument("--output-dir", default="output")
    rank_p.add_argument("--all-profiles", action="store_true", help="Run every profile in synthetic_profiles.json")

    sub.add_parser("enrich", help="Pre-fetch Wikipedia summaries for all acquirers (one-time, offline after)")

    args = parser.parse_args()

    if args.command == "enrich":
        from app.enrich import main as enrich_main

        enrich_main()
        return

    df = load_transactions(DEFAULT_CSV_PATH)
    enrichment_cache = load_enrichment_cache()

    if args.all_profiles:
        for profile in load_profiles():
            asyncio.run(
                run_profile(df, profile, enrichment_cache, args.top_n, args.output_dir, slug=profile["slug"])
            )
        return

    target_profile = resolve_profile(args.profile, args.sector, args.deal_size_mm, args.geography)
    slug = args.profile or default_slug(target_profile)
    asyncio.run(run_profile(df, target_profile, enrichment_cache, args.top_n, args.output_dir, slug=slug))


if __name__ == "__main__":
    main()
