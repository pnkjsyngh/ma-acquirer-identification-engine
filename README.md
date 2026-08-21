# M&A Acquirer Identification Engine

Given a target company profile (sector, deal size, geography), ranks the 10 most likely acquirers from a
500-row historical M&A transaction dataset and generates an MD-ready, data-cited one-page rationale for each.

## Quick start

```bash
# No API key needed -- deterministic canned rationales, fully offline
MOCK_LLM=1 ./run.sh rank --profile healthcare_services_default

# Real synthesis (requires ANTHROPIC_API_KEY + OPENCODE_API_KEY, see below)
./run.sh rank --profile healthcare_services_default

# Run all 10 synthetic test profiles (see data/synthetic_profiles.json)
./run.sh rank --all-profiles

# Custom target profile
./run.sh rank --sector "Medical Devices" --deal-size-mm 300 --geography Midwest
```

`run.sh` creates/reuses a `.venv`, installs dependencies, and loads `.env` automatically -- no other setup.
Output lands in `output/<profile_slug>/`: `summary.md` (ranked table), `01_<acquirer>.md` … `10_<acquirer>.md`
(one rationale each), `results.json` (same data, machine-readable). Runs in 30-45 seconds end-to-end (live,
10 rationales generated concurrently), well under the 60-second target.

`./run.sh enrich` re-runs the one-time Wikipedia pre-fetch for all acquirers -- not required to run the ranker;
the cache is already committed at `data/enrichment_cache.json`.

### Environment variables

See `.env.example` for the full list with defaults. The two that matter for a live run:

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes (unless `MOCK_LLM=1`) | Stage 1: tool-calling, evidence gathering, routing |
| `OPENCODE_API_KEY` | Yes (unless `STAGE2_BACKEND=anthropic`) | Stage 2: bulk rationale synthesis |

Never commit `.env` -- it's gitignored. Copy `.env.example` to `.env` and fill in real values.

## Architecture

```
data.py ──▶ features.py ──▶ ranking.py ──▶ llm.py ──▶ output.py
 (CSV)      (signals)      (top 10 +      (two-stage   (markdown/JSON)
                           evidence)      LLM synthesis)
```

**Ranking (deterministic, no LLM).** A two-tier fit score: per-deal signals (sector adjacency, size distance,
profile fit, recency, outcome quality, tag alignment) rolled up to an acquirer via a recency/outcome-weighted
mean, then multiplied by a confidence dampener (`min(1, relevant_deals / 3)`) so a single lucky deal can't
outrank a firm with a genuine track record. The ranking never touches an LLM -- it's fully reproducible and
satisfies the "no hardcoded acquirer list" requirement, since the shortlist is derived from data every time,
not asserted.

**Sector adjacency is not a hand-tuned prior.** It's the cosine similarity of acquirer overlap between the
target sector and a deal's sector -- "do the same buyers transact in both" -- computed from the sector×acquirer
co-occurrence matrix, with an IDF-style downweight on acquirers active across many sectors. Without that
downweight, generalist PE mega-funds active in 8-10 of the 10 sectors inflate similarity between *every* sector
pair uniformly, making a Dental-only specialist look "relevant" to Pharma/Biotech. Verified target-sensitive:
running all 10 synthetic profiles in `data/synthetic_profiles.json`, top-10 overlap with the Healthcare Services
default ranges 0-5 acquirers out of 10 across sectors -- the ranking genuinely moves with the target rather than
always surfacing the same PE funds. Acquirer-type mix (Strategic vs. Financial Sponsor) in the top 10 also
varies realistically by sector (e.g. 8 Strategic / 2 Sponsor for Health IT vs. 2 Strategic / 8 Sponsor for
Physician Groups) rather than sitting at a fixed ratio.

**LLM synthesis is a two-stage, tool-calling pipeline, one call sequence per acquirer, all 10 acquirers run
concurrently via `asyncio.gather`.**

- *Stage 1 (Anthropic)* -- the judgment-heavy part only. The model selects and calls tools with defined JSON
  schemas (`get_precedent_deals`, `get_valuation_comps`, `get_rationale_tag_overlap`) to gather whatever
  evidence it needs, via the Anthropic Messages API's native tool-use loop (no MCP -- this app owns both the
  tools and the only client). When an acquirer's evidence is thin (`relevant_deals < 3`), the model decides
  whether to call `widen_to_adjacent_sector` to pull supplementary deals from adjacent sectors -- this is the
  one place the LLM's choice actually changes the code path; evidence-retrieval tools called unconditionally
  every time don't count as real routing. Stage 1's output includes a mandatory `reasoning` field (a
  scratchpad, not a one-shot stateless call) and is deliberately kept short and cheap, since Anthropic calls
  are the expensive ones in this split.
- *Stage 2 (opencode-go, `gpt-5.6-luna` by default)* -- bulk prose generation only. Takes Stage 1's finalized
  dossier plus its reasoning trace as fully-prepared input and writes the six-section rationale into a
  Pydantic-validated schema. Never calls tools, never re-decides anything Stage 1 already settled -- this is
  where the actual token volume lives (six prose sections × 10 acquirers), so it's also where the cost savings
  land by running on the cheaper model. `STAGE2_BACKEND=anthropic` is available as a fallback if opencode-go is
  unreachable, using the same client Stage 1 already has open.
- Output is validated against a `RationaleOutput` Pydantic model (`app/schemas.py`) with a repair/retry loop on
  validation failure -- not `json.loads()` and hope. The ranking layer, not the LLM, sets each acquirer's
  Conviction level (High/Medium/Low by rank); the LLM's job is to justify it with cited evidence, never override
  it.

**Why not one prompt per acquirer?** A single "here's everything, write the rationale" prompt has no tool use
and no LLM-driven routing -- it's a schema-constrained wrapper around one model call, regardless of how good the
prompt is. Splitting evidence-gathering (with real tool calls and a genuine conditional routing decision) from
prose-writing is what makes this an agentic pipeline rather than a prompt template.

**Why two providers?** Purely a cost decision. Anthropic calls are more expensive per token, so Stage 1 is kept
short (a routing decision plus a brief reasoning trace) while the token-heavy prose generation runs on a cheaper
model via opencode-go.

## Assumptions

- The default target profile (no `--sector`/`--deal-size-mm` given) is Healthcare Services, ~$200M EV,
  mid-market/private/regional/strong margins, per the assessment brief.
- "Regional" with no specific region given is treated as "any specific region is a full geography match" --
  only National/Multi-Regional deals score lower, since the target didn't rule out any particular region.
- Tier-1 signal weights (`sector_fit` 0.30 / `size_fit` 0.25 / `profile_fit` 0.20 / `recency` 0.10 /
  `outcome_quality` 0.10 / `tag_alignment` 0.05) and the eligibility threshold (3 relevant deals for full
  confidence) are documented constants, chosen to be directionally sensible and checked against the
  target-sensitivity results above, not the product of a formal weight-sensitivity sweep.
- "Relevant" deal = `sector_fit >= 0.35`; "adjacent" (widen-eligible) = `0.15 <= sector_fit < 0.35`.
- Conviction is rank-derived: High = rank ≤3, Medium = 4-7, Low = ≥8 -- a deliberate choice so conviction
  varies across the 10 acquirers rather than clustering, per the assessment's "conviction levels should vary
  and be defensible" guidance.
- `days_to_close` is null in ~19% of rows (only populated for `Closed` deals, which is structural, not a data
  quality bug) and isn't used by any ranking signal, so this doesn't affect scores.

## Known limitations

- **Grounding is not machine-verified end-to-end.** A manual spot-check (Atrium Health, Healthcare Services
  default profile) confirmed every precedent deal, multiple, and geographic count cited in the generated
  rationale traces exactly to the CSV -- with one exception: a comps-range figure was cited as "9.3x-16.6x"
  against an actual aggregate low of 9.2x, a 0.1 rounding slip rather than a fabrication. There's no automated
  numeric-diff validator checking every cited figure against the source data on every run; this would be the
  first thing to add with more time.
- **Sector adjacency is a proxy, not a direct measure.** The co-occurrence-based cosine similarity reflects
  which sectors share buyers, which is *related* to but not identical to strategic adjacency. The IDF downweight
  sharpens this meaningfully but doesn't eliminate the approximation.
- **Wikipedia enrichment covers 70 of 107 acquirers.** Coverage skews toward large PE sponsors and public
  strategics; smaller regional health systems and niche RCM/home-health names more often have no dedicated
  article. Handled gracefully (the Acquirer Overview and Risk Flags sections fall back to CSV-only content, no
  crash) -- not a bug, but real name-collision risk was found and mitigated during development (a business-entity
  filter plus a hard-coded exclusion list for one confirmed same-name mismatch), not eliminated entirely.
- **`STAGE2_BACKEND=anthropic` (the opencode-go fallback) is implemented but not live-tested** -- the default
  opencode-go path has been exercised extensively and works reliably; the fallback branch is straightforward
  (same client, same call shape Stage 1 already uses) but hasn't itself been run against a real outage.
- **No persistent feedback loop, no arbitrary-profile web UI** (the CLI already accepts `--sector`/
  `--deal-size-mm`/`--geography` directly, so arbitrary profiles work, just not through a form), **no MCP tool
  exposure** -- all considered and scoped out to stay within the assessment's intended effort level.
- **Weights are documented assumptions, not fitted or swept.** See Assumptions above.

## Non-determinism handling

- `temperature=0` on every LLM call (Stage 1 and Stage 2). Note: as of the current Anthropic SDK release,
  `temperature` was deprecated as a first-class `messages.create()` parameter by the API itself -- passing it
  directly now raises a `TypeError`. It's passed via `extra_body={"temperature": 0}` instead, which the SDK
  merges directly into the request JSON; this was found and fixed via live testing against the real API, not
  anticipated in advance.
- The ranking layer is pure and deterministic (no randomness, seeded only by the CSV itself) -- the acquirer
  list, order, and Conviction levels are always reproducible for a given target profile.
- LLM prose still has residual run-to-run variance even at temperature 0 -- a property of the models themselves,
  not something this codebase controls. `MOCK_LLM=1` substitutes fully deterministic canned output (built
  directly from the same dossier the real LLM would see) for a zero-key demo and for exercising the full
  pipeline -- including the conditional widen-to-adjacent-sector path -- deterministically in tests.
- Every rationale is schema- and business-rule-validated on the way out (`app/output.py::validate_rationale`,
  backed by the `RationaleOutput` Pydantic model) with one repair/retry attempt on failure before the run fails
  loudly for that acquirer, rather than silently shipping malformed or boilerplate output.

## Testing

```bash
MOCK_LLM=1 python -m pytest tests/ -q
```

33 tests covering the ranking/feature layer, the tool schemas and dispatch, the adjacent-sector-candidate
computation, and the full pipeline under `MOCK_LLM=1` -- including a test that specifically proves the
widen-to-adjacent-sector routing decision fires conditionally (not always, not never) for a real thin-evidence
acquirer, not just that the code path exists.
