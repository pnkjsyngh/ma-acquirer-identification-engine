"""Optional Langfuse tracing wrapper. The only file in this codebase that imports langfuse.

Tracing is entirely optional: every function here is a safe no-op when LANGFUSE_PUBLIC_KEY
isn't set, so the rest of the app -- including MOCK_LLM=1 and CI, neither of which has
Langfuse keys -- behaves identically whether this is configured or not.
"""

from __future__ import annotations

import contextlib
import os
from typing import Literal


def is_enabled() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY"))


class _NoopObservation:
    def update(self, **kwargs) -> None:
        pass


@contextlib.contextmanager
def start_observation(as_type: Literal["span", "generation"], name: str):
    if not is_enabled():
        yield _NoopObservation()
        return

    from langfuse import get_client

    with get_client().start_as_current_observation(as_type=as_type, name=name) as obs:
        yield obs


# Self-computed cost fallback for models where Langfuse's own auto-calculation doesn't
# work despite correctly matching the model (confirmed live: gpt-5.6-luna resolves to
# its custom model definition every time -- same model_id, input_price/output_price
# populated -- but calculated_total_cost stays 0.0 and cost_details stays empty,
# reproduced across multiple fresh observations, so it isn't a caching/timing issue).
# Rates below are the same input_price/output_price shown on that model definition
# itself; we just apply them ourselves instead of relying on Langfuse's tier
# calculation for this specific model. Models not listed here still rely on Langfuse's
# own auto-calc (e.g. Anthropic models, which compute correctly today).
_KNOWN_PRICE_PER_TOKEN = {
    "gpt-5.6-luna": (2e-07, 1.2e-06),  # (input $/token, output $/token)
}


def record_usage(obs, model: str, input_tokens: int, output_tokens: int) -> None:
    # `model` is required for Langfuse to compute cost from usage_details -- it looks up
    # $/token by matching this string against its pricing table (built-in or custom
    # model definitions registered in the Langfuse project). Without it, cost silently
    # stays blank even though token counts still show up.
    if not is_enabled():
        return

    update_kwargs = {
        "model": model,
        "usage_details": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }
    if model in _KNOWN_PRICE_PER_TOKEN:
        input_price, output_price = _KNOWN_PRICE_PER_TOKEN[model]
        input_cost = input_tokens * input_price
        output_cost = output_tokens * output_price
        update_kwargs["cost_details"] = {
            "input": input_cost,
            "output": output_cost,
            "total": input_cost + output_cost,
        }
    obs.update(**update_kwargs)


def current_ids() -> tuple[str | None, str | None]:
    if not is_enabled():
        return None, None

    from langfuse import get_client

    client = get_client()
    return client.get_current_trace_id(), client.get_current_observation_id()


def create_score(
    trace_id: str | None, observation_id: str | None, relevant: bool, comment: str | None = None
) -> bool:
    if not is_enabled() or not trace_id:
        return False

    from langfuse import get_client

    get_client().create_score(
        name="acquirer_relevant",
        value=1.0 if relevant else 0.0,
        trace_id=trace_id,
        observation_id=observation_id,
        data_type="BOOLEAN",
        comment=comment or None,
    )
    return True


def flush() -> None:
    if not is_enabled():
        return

    from langfuse import get_client

    get_client().flush()
