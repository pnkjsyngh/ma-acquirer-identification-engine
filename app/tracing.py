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


def record_usage(obs, model: str, input_tokens: int, output_tokens: int) -> None:
    # `model` is required for Langfuse to compute cost from usage_details -- it looks up
    # $/token by matching this string against its pricing table (built-in or custom
    # model definitions registered in the Langfuse project). Without it, cost silently
    # stays blank even though token counts still show up.
    if not is_enabled():
        return
    obs.update(model=model, usage_details={"input_tokens": input_tokens, "output_tokens": output_tokens})


def current_ids() -> tuple[str | None, str | None]:
    if not is_enabled():
        return None, None

    from langfuse import get_client

    client = get_client()
    return client.get_current_trace_id(), client.get_current_observation_id()


def create_score(trace_id: str | None, observation_id: str | None, flagged: bool) -> bool:
    if not is_enabled() or not trace_id:
        return False

    from langfuse import get_client

    get_client().create_score(
        name="flagged_irrelevant",
        value=1.0 if flagged else 0.0,
        trace_id=trace_id,
        observation_id=observation_id,
        data_type="BOOLEAN",
    )
    return True


def flush() -> None:
    if not is_enabled():
        return

    from langfuse import get_client

    get_client().flush()
