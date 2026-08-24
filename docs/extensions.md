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

**Broader target-profile parameter surface.** Today a target is `sector` + `deal_size_mm` + optional
`geography` (plus optional `thesis_tags`) — three or four levers total. The dataset itself carries several more
dimensions a real analyst would want to express a preference on: preferred `financing_type` or `deal_type`
(e.g. "prefers all-cash, avoid earnouts"), a minimum `num_bidders` threshold (competitive-process tolerance), an
`outcome`-quality preference, or a target `target_ownership_pre` (e.g. "comparable to other PE-backed exits").
Each is architecturally the same shape as "Richer target attributes" above — one new signal function, one new
`WEIGHTS` entry — so this is really that same pattern applied more broadly rather than a new mechanism. Worth
sequencing after `WEIGHTS` is externalized to a config file (see "Externalize `WEIGHTS` to a config file" under
Cost & performance below): more parameters means more weights, and a growing hardcoded `WEIGHTS` dict is
exactly the pressure that makes externalizing it worthwhile.

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
for the Stage 1 model alongside the one that already exists for the Stage 2 model — a real staleness risk if
provider pricing changes, the same tradeoff already being carried for the Stage 2 fallback.

**Streaming/progressive UI.** The web UI currently blocks on one `POST /rank` for the full ~30-45s run. A
streaming variant (Server-Sent Events or WebSockets) could show each acquirer's rationale as it completes
rather than all-or-nothing, since the 10 acquirers already run concurrently — the data is available
progressively, it's just not surfaced that way yet.

**Externalize `WEIGHTS` to a config file.** `app/features.py`'s `WEIGHTS` dict is a hardcoded Python constant
today — directionally sensible and sensitivity-tested (see `docs/weight_sensitivity.md`), but changing any
value means a code edit and a redeploy, not a config change. Moving it to a YAML/JSON file loaded at startup is
mechanically simple on its own; it becomes worth doing specifically once "Broader target-profile parameter
surface" (above) adds more weights to tune — a six-entry hardcoded dict is easy to live with, a fifteen-entry
one is exactly the pressure that makes externalizing it worthwhile.

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

**Surface the widen-to-adjacent-sector decision structurally, not just in prose.** When Stage 1 widens evidence
for a thin acquirer, that fact only reaches the final report informally: `build_stage2_prompt` nudges the model
to mention it in prose (`app/prompts.py`), but nothing guarantees the words show up, and there's no `widened`
field in `results.json`, no badge in the web UI, and nothing in the Langfuse trace metadata. An acquirer that
triggers widening already has a dampened score (`confidence = min(1.0, relevant_deals / 3)` in `app/ranking.py`
is the same `relevant_deals` count that sets `thin_evidence`, so the two are directly linked), so this isn't
covering up a hidden problem, it's a transparency nicety: making "which acquirers on this list are here on
thinner evidence than others" a one-glance answer instead of something a reader has to infer from prose or
rank position. Cheap to add (same `trace_id`/`csv_row` threading pattern already used elsewhere), just not
built.

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

**A meeting/engagement-history tool (e.g. Fellow).** Stage 1's evidence gathering today is three tools plus
Wikipedia enrichment, all derived from the static CSV or a public summary — none of it reflects whether a
banker has actually talked to this acquirer about this target. A fourth tool pulling engagement history from a
meeting-notes platform like Fellow would be a genuinely new kind of evidence, not "did this acquirer transact
historically" but "has anyone already had this conversation." Same mechanism as the existing three tools, one
more entry in Stage 1's tool schema, no new pattern. It also doubles as a plausible real source for the
outcome-engagement label "Weight tuning from real outcomes" (above) and "No closed-loop feedback" (README's
Limitations section) both currently lack — did the acquirer take the meeting, move forward, or pass.

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
this app's own CLI/web UI. Concrete motivation, not just "for completeness": AI copilots built for deal teams
— Rogo and BlueFlame, both AI-native platforms for banking/investing workflows — are exactly the kind of
client that would want to call "who are the likely acquirers for this target" as a tool rather than
reimplement the ranking logic themselves. Pure integration surface either way — doesn't change ranking
correctness or output quality, so it was deliberately deprioritized versus everything above.

**Agentic harness migration (e.g. LangGraph).** Stage 1's tool-calling loop is intentionally hand-rolled today
(`app/llm.py`'s `_stage1_tool_loop`) — a native Anthropic tool-use loop with one conditional branch, widen or
don't — appropriate for a surface this small. That stops being true once the tool roster and entry points
grow: a fourth tool (meeting-history, above) means more of what to call and when, and MCP exposure (above)
means the same agent effectively serves two different callers — this app's own pipeline, and an external MCP
client — which starts to want explicit state rather than a closure captured in one Python function. A
framework like LangGraph would replace the implicit while-loop with an explicit state graph, literally the
thing the README's Figure 4 is hand-drawing today, becoming the actual runtime instead of just documentation
of it, and buys checkpointing/resumability and a natural human-in-the-loop seam for free. Not worth the
complexity cost at today's one-loop, one-branch scale; worth it specifically once the surface above grows into
it.

**Real persistence layer.** Output is currently file-based (`output/<slug>/`), fine for a single-user prototype
but not for multi-user/audit-trail needs. A real datastore (Postgres) would enable querying past runs, versioning
rationale changes over time, and proper multi-user access rather than a shared local filesystem.

**Productionizing & deployment.** This is architecturally solid (modular, tested, observable) but still a
single-process prototype, not something built for concurrent multi-user traffic:
- **Deployment & scaling** — containerized and orchestrated (K8s/ECS), with the existing CI (test-only today,
  see the README's Testing section) extended into an actual CD pipeline. Deliberately not built now: `run.sh`
  already satisfies what this prototype actually needs (single command, no manual setup, reproducible
  environment), so a container would be adding a dependency rather than removing one at this scale — it starts
  to earn its keep once there's a real multi-user deploy target to orchestrate, which is the rest of this list.
- **Secrets management** — `.env` files are fine for a prototype, not for a real deploy; a real secrets manager
  (Vault or a cloud-native equivalent) instead.
- **Backpressure & rate limiting.** `asyncio.gather` concurrency is validated for one request's 10 acquirers
  (see the README's Architecture section), not for N simultaneous users each firing a full profile run and
  hitting Anthropic/opencode-go concurrently. No request queueing or throttling today, and no protection
  against concurrent requests racing on the same `output/<slug>/` path (already a documented last-writer-wins
  gap in the README's Web UI section).
- **Health checks & alerting.** Langfuse tracing gives observability (what happened) but there's no alerting
  layer (get paged when something's wrong) and no `/health`/readiness endpoint for an orchestrator to use.

**Auth & multi-user.** If this became an actual internal tool rather than a prototype: authentication and
per-user run history, neither of which exist today or were in scope for a take-home.
