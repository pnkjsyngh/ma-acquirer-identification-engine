# Extensions

What this prototype would grow into with more time and resources, organized by theme. Each item notes what it
is, why it matters, and roughly how it would attach to the existing architecture (see `docs/architecture.md`).

## Data & target modeling

**Formal `TargetProfile` schema (Pydantic).** Today `target_profile` is a plain dict (`sector`, `deal_size_mm`,
`geography`) threaded through every module by convention. A Pydantic model would give type safety at the
boundary (CLI args, web form) and make new fields self-documenting rather than another string key someone has
to know to add.

**Richer target attributes.** The target's own EBITDA margin, revenue growth, and ownership type aren't
actually parameterized today — `features.py`'s `margin_score()` scores each historical deal's margin against
the *dataset's* min/max, not against anything the target specified. "Strong EBITDA margins" is currently
descriptive text, not a number that affects scoring. Extending this is architecturally cheap: one new signal
function per attribute (e.g. `margin_alignment_score(deal_margin, target_margin)`, distance-based like
`size_fit` already is), one new `WEIGHTS` entry, renormalize. The pattern — one function per signal, weighted
sum — is already additive, not a rewrite.

**Multi-target / portfolio mode.** Run the ranking across an entire pipeline of prospective targets at once
(e.g. a banker's full deal list for the quarter), not one at a time — same underlying `rank_acquirers` call,
batched, with a portfolio-level summary view.

## Cost & performance

**Operational memory / result caching.** Right now every run re-executes the full pipeline, live LLM calls
included, even for an identical request. A cache keyed on the full target profile (not just slug — see the
slug-collision fix earlier) that serves a prior `results.json` when nothing has changed would cut cost
significantly for repeat/demo traffic. Real design questions worth taking seriously: cache invalidation when
the underlying CSV changes, a TTL or explicit "force refresh" escape hatch, and where the cache lives (in-process
dict is fine for a demo; a real deployment wants Redis or a small SQLite table).

**Tracing + tokenomics — built, with one gap.** Langfuse tracing (`app/tracing.py`) gives per-call token counts,
cost, and latency in a dashboard, not just application logs (see the README's Observability & feedback
section). What's still missing: no aggregate cost-per-run figure surfaced in the app or the UI itself — it's
per-call in the Langfuse dashboard only. Surfacing it locally would mean threading a self-computed cost figure
through the pipeline the same way `trace_id`/`csv_row` already are, plus a locally-hardcoded per-token price
for Claude (Stage 1) alongside the one that already exists for `gpt-5.6-luna` (Stage 2) — a real staleness risk
if provider pricing changes, the same tradeoff already being carried for the Stage 2 fallback.

**Streaming/progressive UI.** The web UI currently blocks on one `POST /rank` for the full ~30-45s run. A
streaming variant (Server-Sent Events or WebSockets) could show each acquirer's rationale as it completes
rather than all-or-nothing, since the 10 acquirers already run concurrently — the data is available
progressively, it's just not surfaced that way yet.

**Weight tuning from real outcomes.** `WEIGHTS` are documented, sensitivity-tested constants (see `docs/
weight_sensitivity.md`), not fitted to anything. If the dataset had a genuine "did this acquirer actually
transact" label per candidate (rather than just historical deals), a real fitted model (logistic regression
over the same signal set) would replace hand-tuned weights with learned ones — a meaningfully different, more
rigorous approach than what's here now.

## Quality & trust

**Automated grounding/citation validation — built for structured fields, not free text.** `app/grounding.py`
now verifies every `precedent_activity` citation against the real deal history and diffs `valuation_context`
medians against deterministically-computed values, on every run, with a retry-then-hard-fail path (see the
README's Grounding & validation section). What's still missing: numbers embedded in free-text prose
(`acquirer_overview`, `risk_flags[].evidence`) aren't parsed/verified — that would need real NLP/regex work to
extract numeric claims from arbitrary sentences and re-derive the equivalent figure from the CSV. Narrower and
higher-value than a general-purpose framework, same reasoning as the guardrails discussion below.

**Guardrails.** Considered and deliberately scoped narrow: the real risk profile here doesn't include
untrusted free-text user input (target fields are structured, not open text), so general prompt-injection/
jailbreak defenses (NeMo Guardrails, LLM-Guard) mostly aren't solving a threat that exists in this app. The
higher-value version is the numeric-grounding validator above, which is a custom, in-house addition rather than
a new framework dependency. If a named framework is wanted anyway, Guardrails AI (open-source, free) is the
best fit since it extends the Pydantic-based validation already in place with semantic validators layered on
top.

**Fuller external enrichment.** Wikipedia-only enrichment covers 70/107 acquirers today, skewed toward large
PE sponsors and public strategics. Search-augmented enrichment (e.g. Anthropic's web search tool, ~$0.01/search)
would both raise coverage and fix a structural blind spot Wikipedia can't: disambiguating two real companies
sharing a name, since a search call can be given sector context ("Headway, a Behavioral Health acquirer")
a bare title lookup cannot.

**Golden-file regression testing.** As prompts, models, or weights change over time, a small suite of "known
good" outputs to diff against would catch quality regressions the way `tests/test_ranking.py`'s hardcoded
top-3 assertion already catches ranking regressions — extending that same idea to rationale *content*, not
just the acquirer list.

## Product & platform

**Closed-loop feedback — built as trace-attached annotation, not a re-ranking loop.** The assessment's feedback
stretch goal is scoped narrower than what's here: "Relevant"/"Not relevant" flags on each acquirer card attach
a score to that acquirer's Langfuse trace (see the README's Observability & feedback section) — visible in the
dashboard, doesn't touch future rankings. The fuller version — a penalty multiplier that adjusts future
rankings for similar targets based on accumulated flags — is a real product decision (a persistence layer, a
re-rank hook, and a decision about how much weight accumulated feedback should carry) and remains future work.

**Comparison mode — built.** `--compare SLUG_A SLUG_B` / the web UI's Compare tab run two target profiles
side by side, reusing the same ranking pipeline (target-agnostic by construction). See the README's Quick
start and Web UI sections.

**MCP tool exposure.** Wrap `rank_acquirers` and the evidence-gathering tools already built for Stage 1
(`app/tools.py`) as MCP tools, so any MCP-compatible client could call them directly rather than only through
this app's own CLI/web UI. Pure integration surface — doesn't change ranking correctness or output quality, so
it was deliberately deprioritized versus everything above.

**Real persistence layer.** Output is currently file-based (`output/<slug>/`), fine for a single-user prototype
but not for multi-user/audit-trail needs. A real datastore (Postgres) would enable querying past runs, versioning
rationale changes over time, and proper multi-user access rather than a shared local filesystem.

**Auth & multi-user.** If this became an actual internal tool rather than a prototype: authentication, per-user
run history, and rate limiting — none of which exist today and none of which were in scope for a take-home.
