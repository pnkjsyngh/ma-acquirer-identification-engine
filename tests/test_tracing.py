from app import tracing


def test_is_enabled_false_without_key(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    assert tracing.is_enabled() is False


def test_start_observation_is_safe_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    with tracing.start_observation("span", "test") as obs:
        obs.update(usage_details={"input_tokens": 1, "output_tokens": 1})  # must not raise


def test_record_usage_is_safe_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    with tracing.start_observation("generation", "test") as obs:
        tracing.record_usage(obs, "some-model", 10, 20)  # must not raise


def test_current_ids_none_when_disabled(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    assert tracing.current_ids() == (None, None)


def test_create_score_returns_false_when_disabled(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    assert tracing.create_score("some-trace-id", "some-observation-id", True) is False


def test_create_score_returns_false_without_trace_id(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    assert tracing.create_score(None, None, True) is False


def test_flush_does_not_raise_when_disabled(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    tracing.flush()
