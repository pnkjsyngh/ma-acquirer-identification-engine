"""Two-stage per-acquirer LLM synthesis, run concurrently across acquirers via asyncio.gather.

Stage 1 (Anthropic): the complex/judgment part only -- the LLM selects and calls tools to
gather evidence, and decides whether to widen to adjacent sectors when evidence is thin.
Kept short and cheap on purpose (Anthropic calls are the expensive ones in this split).

Stage 2 (DeepSeek V4 Pro via opencode-go by default, Anthropic as an explicit fallback):
bulk prose generation only. Never calls tools, never re-decides anything Stage 1 already
settled -- this is where the token volume (and cost) actually is.

MOCK_LLM=1 substitutes deterministic canned output for both stages (no network call) so
the pipeline runs end-to-end with zero API keys -- this is also what test_output.py
exercises, including the conditional widen path.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

from pydantic import ValidationError

from app import tracing
from app.output import validate_rationale
from app.prompts import (
    OUTPUT_SCHEMA,
    STAGE1_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_stage1_prompt,
    build_stage2_prompt,
)
from app.schemas import Stage1Decision
from app.tools import TOOL_SCHEMAS, execute_tool

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
STAGE2_BACKEND = os.environ.get("STAGE2_BACKEND", "opencode-go")
STAGE2_MODEL = os.environ.get("STAGE2_MODEL", "gpt-5.6-luna")
OPENCODE_BASE_URL = os.environ.get("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1")
STAGE2_MAX_TOKENS = int(os.environ.get("STAGE2_MAX_TOKENS", "3500"))
MAX_TOOL_ITERATIONS = 6

logger = logging.getLogger(__name__)

_anthropic_client = None
_opencode_client = None


def _get_anthropic_client():
    # Shared across all concurrent acquirers -- a fresh client per call means a fresh
    # connection pool per call under a 10-way asyncio.gather fan-out. Reusing a single
    # client avoids that overhead entirely.
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic

        _anthropic_client = anthropic.AsyncAnthropic()
    return _anthropic_client


def _get_opencode_client():
    global _opencode_client
    if _opencode_client is None:
        import httpx

        _opencode_client = httpx.AsyncClient(timeout=120.0)
    return _opencode_client


class RationaleGenerationError(Exception):
    """Raised when the LLM output can't be coerced into valid JSON after one retry."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    # Strip ```json ... ``` fences if the model wrapped its output despite instructions.
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    return json.loads(text)


def _apply_stage1_decision(dossier: dict, decision: Stage1Decision) -> tuple[dict, str]:
    """The LLM decides *whether* to widen; the code decides *how* the merge is
    structured -- keeps the merge deterministic and testable independent of the model."""
    finalized = dict(dossier)
    finalized["widened"] = decision.used_widen
    finalized["widened_sectors"] = decision.sectors_widened
    if decision.used_widen:
        adjacent = dossier.get("adjacent_candidate_deals", [])
        finalized["deals_table"] = dossier["deals_table"] + adjacent
        by_sector = dict(dossier.get("deals_by_sector", {}))
        for deal in adjacent:
            by_sector[deal["sector"]] = by_sector.get(deal["sector"], 0) + 1
        finalized["deals_by_sector"] = by_sector
    return finalized, decision.reasoning


def _mock_stage1(dossier: dict) -> tuple[dict, str]:
    adjacent = dossier.get("adjacent_candidate_deals", [])
    used_widen = bool(dossier.get("thin_evidence", False)) and bool(adjacent)
    reasoning = (
        f"[MOCK] {dossier['relevant_deals']} of {dossier['total_deals']} deals are directly relevant. "
        + (
            f"Evidence was thin, so widened into adjacent sectors: {sorted({d['sector'] for d in adjacent})}."
            if used_widen
            else "Evidence is sufficient without widening to adjacent sectors."
        )
    )
    decision = Stage1Decision(
        reasoning=reasoning,
        used_widen=used_widen,
        sectors_widened=sorted({d["sector"] for d in adjacent}) if used_widen else [],
    )
    return _apply_stage1_decision(dossier, decision)


async def _stage1_tool_loop(client, dossier: dict, target_profile: dict, usage: dict) -> tuple[dict, str]:
    messages: list[dict] = [{"role": "user", "content": build_stage1_prompt(target_profile, dossier)}]

    for _ in range(MAX_TOOL_ITERATIONS):
        response = await client.messages.create(
            model=MODEL,
            max_tokens=700,
            extra_body={"temperature": 0},
            system=STAGE1_SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens

        if response.stop_reason != "tool_use":
            text = "".join(block.text for block in response.content if block.type == "text")
            try:
                decision = Stage1Decision.model_validate(_extract_json(text))
            except (json.JSONDecodeError, ValidationError):
                decision = Stage1Decision(
                    reasoning="[fallback] could not parse Stage 1 decision output", used_widen=False
                )
            return _apply_stage1_decision(dossier, decision)

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                result = execute_tool(block.name, block.input, dossier, target_profile)
            except (ValueError, TypeError) as e:
                result = {"error": str(e)}
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result, default=str)}
            )

        if not tool_results:
            # Defensive: confirmed live that stop_reason=="tool_use" can occur without
            # a usable tool_use block surviving to this point. The API rejects an empty
            # tool_result user turn with a 400 -- fall back instead of crashing this
            # acquirer's entire rationale over one anomalous turn.
            decision = Stage1Decision(
                reasoning="[fallback] Stage 1 reported a tool call but produced no usable tool_use block",
                used_widen=False,
            )
            return _apply_stage1_decision(dossier, decision)

        messages.append({"role": "user", "content": tool_results})

    decision = Stage1Decision(reasoning="[fallback] tool loop exceeded max iterations", used_widen=False)
    return _apply_stage1_decision(dossier, decision)


async def stage1_gather_evidence(target_profile: dict, dossier: dict) -> tuple[dict, str]:
    """Returns (finalized_dossier, stage1_reasoning)."""
    acquirer = dossier["acquirer"]
    started = time.monotonic()
    logger.info("Stage 1 (evidence gathering) started for %s", acquirer)

    with tracing.start_observation("generation", f"stage1:{acquirer}") as obs:
        usage = {"input_tokens": 0, "output_tokens": 0}
        if os.environ.get("MOCK_LLM") == "1":
            finalized_dossier, reasoning = _mock_stage1(dossier)
        else:
            finalized_dossier, reasoning = await _stage1_tool_loop(
                _get_anthropic_client(), dossier, target_profile, usage
            )
        tracing.record_usage(obs, MODEL, usage["input_tokens"], usage["output_tokens"])

    elapsed = time.monotonic() - started
    logger.info(
        "Stage 1 for %s completed in %.2fs (widened=%s)", acquirer, elapsed, finalized_dossier["widened"]
    )
    return finalized_dossier, reasoning


_FALLBACK_RISKS = [
    {"risk": "Limited precedent activity", "evidence": "[MOCK] few directly relevant deals in dataset"},
    {"risk": "Competitive process risk", "evidence": "[MOCK] deal history shows multi-bidder processes"},
]


def _mock_risk_flags(dossier: dict) -> list[dict]:
    flags = [{"risk": r, "evidence": "[MOCK] data-derived"} for r in dossier["risk_candidates"]]
    for fallback in _FALLBACK_RISKS:
        if len(flags) >= 2:
            break
        flags.append(fallback)
    return flags[:4]


def _mock_stage2(
    target_profile: dict,
    finalized_dossier: dict,
    conviction_level: str,
    external_facts: list[dict],
    stage1_reasoning: str,
) -> dict:
    sector = target_profile["sector"]
    deals = finalized_dossier["deals_table"][:3]
    return {
        "conviction": {
            "level": conviction_level,
            "rationale": (
                f"[MOCK] {finalized_dossier['relevant_deals']} of {finalized_dossier['total_deals']} deals are "
                f"relevant to {sector}, with a median EV/EBITDA of {finalized_dossier['median_ev_ebitda']}x on "
                f"closed deals."
            ),
        },
        "acquirer_overview": (
            f"[MOCK] {finalized_dossier['acquirer']} is a {finalized_dossier['acquirer_type']} with "
            f"{finalized_dossier['total_deals']} transactions in the dataset, most recently in "
            f"{finalized_dossier['most_recent_deal_year']}."
        ),
        "strategic_fit_thesis": (
            f"[MOCK] {finalized_dossier['acquirer']}'s deal history in "
            f"{list(finalized_dossier['deals_by_sector'].keys())} aligns with a "
            f"~${target_profile['deal_size_mm']:.0f}M {sector} target. Stage 1 evidence review: {stage1_reasoning}"
        ),
        "precedent_activity": [
            {
                "year": d["deal_year"],
                "target": d["target_company"],
                "sector": d["sector"],
                "deal_size_mm": d["deal_size_mm"],
                "deal_type": d["deal_type"],
                "ev_ebitda_multiple": d["ev_ebitda_multiple"],
            }
            for d in deals
        ],
        "valuation_context": {
            "median_ev_ebitda": finalized_dossier["median_ev_ebitda"],
            "median_ev_revenue": finalized_dossier["median_ev_revenue"],
            "comparable_deal_ids": [c["target_company"] for c in finalized_dossier["comparable_closed_deals"][:3]],
            "narrative": f"[MOCK] Comparable closed deals cluster around {finalized_dossier['median_ev_ebitda']}x EV/EBITDA.",
        },
        "risk_flags": _mock_risk_flags(finalized_dossier),
        "external_sources": [
            {"fact": f["text"], "source_url": f["source_url"], "kind": "wikipedia"} for f in external_facts[:2]
        ],
    }


OPENCODE_MAX_RETRIES = 3


async def _call_stage2_opencode(system: str, prompt: str, usage: dict) -> str:
    # gpt-5.6-luna is the default (see STAGE2_MODEL). Both deepseek-v4-pro and
    # deepseek-v4-flash are also available via opencode-go but are reasoning models
    # with no documented way to cap/disable hidden reasoning -- confirmed live that
    # deepseek-v4-pro burns 6000+ completion tokens on reasoning_content with zero
    # actual answer, and deepseek-v4-flash produced ~10k reasoning tokens on one call,
    # both a latency risk (10 concurrent calls, 60s hard budget) and wasted spend on
    # tokens Stage 2 never reads (Stage 1 already did the reasoning). gpt-5.6-luna
    # produces zero reasoning_content and converges well within a normal token budget.
    #
    # Retries with backoff on 5xx: confirmed live that opencode-go can return a
    # transient 500 under concurrent load (10 acquirers fanned out at once) -- retrying
    # here rather than only in the JSON-repair loop, since a 500 isn't a malformed
    # response to repair, it's a request that never got a real answer.
    import asyncio as _asyncio

    import httpx

    api_key = os.environ["OPENCODE_API_KEY"]
    client = _get_opencode_client()
    last_error: Exception | None = None
    for attempt in range(OPENCODE_MAX_RETRIES):
        try:
            response = await client.post(
                f"{OPENCODE_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": STAGE2_MODEL,
                    "temperature": 0,
                    "max_tokens": STAGE2_MAX_TOKENS,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500 or attempt == OPENCODE_MAX_RETRIES - 1:
                raise
            last_error = e
            await _asyncio.sleep(2**attempt)
            continue
        except (httpx.TimeoutException, httpx.TransportError) as e:
            # Confirmed live: a slow/hung request can exceed the client timeout under
            # concurrent load. Same retry treatment as a 5xx -- no response was ever
            # received, nothing to repair.
            if attempt == OPENCODE_MAX_RETRIES - 1:
                raise
            last_error = e
            await _asyncio.sleep(2**attempt)
            continue

        resp_usage = data.get("usage") or {}
        usage["input_tokens"] += resp_usage.get("prompt_tokens", 0)
        usage["output_tokens"] += resp_usage.get("completion_tokens", 0)

        choice = data["choices"][0]
        content = choice["message"]["content"]
        if not content and choice.get("finish_reason") == "length":
            raise RationaleGenerationError(
                "opencode-go response hit the token limit with empty content -- likely "
                "spent the whole max_tokens budget on reasoning_content. Increase "
                f"STAGE2_MAX_TOKENS (currently {STAGE2_MAX_TOKENS})."
            )
        return content

    raise RationaleGenerationError(f"opencode-go returned repeated server errors: {last_error}")


async def _call_stage2_anthropic(system: str, prompt: str, usage: dict) -> str:
    client = _get_anthropic_client()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=2000,
        extra_body={"temperature": 0},
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    usage["input_tokens"] += response.usage.input_tokens
    usage["output_tokens"] += response.usage.output_tokens
    return response.content[0].text


async def _call_stage2(system: str, prompt: str, usage: dict) -> str:
    """Returns raw text. STAGE2_BACKEND selects the backend: 'opencode-go' (default,
    DeepSeek V4 Pro -- cheap, bulk generation only, never sees tools) or 'anthropic'
    (fallback if opencode-go is unreachable -- same model as Stage 1, at Stage 1's
    price, but keeps a live-key run from having a single point of failure)."""
    if STAGE2_BACKEND == "anthropic":
        return await _call_stage2_anthropic(system, prompt, usage)
    return await _call_stage2_opencode(system, prompt, usage)


async def stage2_write_rationale(
    target_profile: dict,
    finalized_dossier: dict,
    conviction_level: str,
    external_facts: list[dict],
    stage1_reasoning: str,
) -> dict:
    acquirer = finalized_dossier["acquirer"]
    started = time.monotonic()
    logger.info("Stage 2 (synthesis) started for %s", acquirer)
    try:
        with tracing.start_observation("generation", f"stage2:{acquirer}") as obs:
            usage = {"input_tokens": 0, "output_tokens": 0}
            if os.environ.get("MOCK_LLM") == "1":
                result = _mock_stage2(
                    target_profile, finalized_dossier, conviction_level, external_facts, stage1_reasoning
                )
            else:
                result = await _stage2_write_rationale_live(
                    target_profile, finalized_dossier, conviction_level, external_facts, stage1_reasoning, usage
                )
            stage2_model = MODEL if STAGE2_BACKEND == "anthropic" else STAGE2_MODEL
            tracing.record_usage(obs, stage2_model, usage["input_tokens"], usage["output_tokens"])
            return result
    finally:
        logger.info("Stage 2 for %s completed in %.2fs", acquirer, time.monotonic() - started)


async def _stage2_write_rationale_live(
    target_profile: dict,
    finalized_dossier: dict,
    conviction_level: str,
    external_facts: list[dict],
    stage1_reasoning: str,
    usage: dict,
) -> dict:
    prompt = build_stage2_prompt(target_profile, finalized_dossier, conviction_level, external_facts, stage1_reasoning)

    async def _call(extra: str = "") -> str:
        return await _call_stage2(SYSTEM_PROMPT, prompt + extra, usage)

    raw = await _call()
    try:
        parsed = _extract_json(raw)
        errors = validate_rationale(parsed, conviction_level, dossier=finalized_dossier)
    except json.JSONDecodeError:
        parsed = None
        errors = [f"could not parse response as JSON:\n{raw}"]

    if parsed is not None and not errors:
        return parsed

    retry_suffix = (
        f"\n\nYour previous response had these problems: {'; '.join(errors)}\n\n"
        f"Return ONLY valid JSON matching this schema exactly (exact key names, no "
        f"renaming or nesting), no other text:\n{json.dumps(OUTPUT_SCHEMA)}"
    )
    raw_retry = await _call(retry_suffix)
    try:
        parsed_retry = _extract_json(raw_retry)
    except json.JSONDecodeError as e:
        raise RationaleGenerationError(
            f"Could not parse LLM output as JSON for {finalized_dossier['acquirer']} after retry: {e}"
        ) from e
    errors_retry = validate_rationale(parsed_retry, conviction_level, dossier=finalized_dossier)
    if errors_retry:
        raise RationaleGenerationError(
            f"LLM output still invalid for {finalized_dossier['acquirer']} after retry: {errors_retry}"
        )
    return parsed_retry


async def synthesize_rationale(
    target_profile: dict,
    dossier: dict,
    conviction_level: str,
    external_facts: list[dict],
) -> dict:
    """Thin orchestrator preserving the pre-retrofit external signature: Stage 1
    gathers/finalizes evidence, Stage 2 writes the rationale from it."""
    finalized_dossier, stage1_reasoning = await stage1_gather_evidence(target_profile, dossier)
    return await stage2_write_rationale(
        target_profile, finalized_dossier, conviction_level, external_facts, stage1_reasoning
    )
