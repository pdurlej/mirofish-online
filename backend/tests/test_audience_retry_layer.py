"""The rescue path has to admit when it cannot rescue anything.

`_should_high_quality_retry` requires `model != retry_model`, and the shipped
defaults set both to "gemma4:31b". So the retry layer has never once fired, and
nothing in the receipt said so. The fix is visibility, not a hardcoded second
model: naming one would assume every deployment can reach it.
"""

from __future__ import annotations

from app.audience import AudienceLiveRunner, AudienceRunInput
from app.audience.model_router import ModelRouter
from app.utils.llm_client import LLMChatResult


class _InvalidJsonClient:
    """Fails with a retryable error kind on every call."""

    def chat_with_metadata(self, **kwargs):
        return LLMChatResult(
            content="not json at all",
            model=kwargs["model"],
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            latency_ms=1,
            finish_reason="stop",
        )


def test_shipped_default_reports_the_retry_layer_as_unavailable():
    router = ModelRouter(model_pool=("gemma4:31b",), high_quality_retry_model="gemma4:31b")
    assert router.high_quality_retry_available is False


def test_a_distinct_retry_model_reports_as_available():
    router = ModelRouter(
        model_pool=("gemma4:31b",), high_quality_retry_model="deepseek-v4-pro"
    )
    assert router.high_quality_retry_available is True


def test_retry_model_normalizes_the_cloud_suffix_like_the_pool(monkeypatch):
    """Otherwise a suffixed retry model never matches a stripped pool.

    The pool runs every entry through `_normalize_model_id`; the retry model did
    not, so "gemma4:31b:cloud" against a "gemma4:31b" pool would have looked
    like a live rescue path that can never actually differ.
    """
    monkeypatch.setenv("MIROFISH_AUDIENCE_RETRY_MODEL", "gemma4:31b:cloud")
    router = ModelRouter(model_pool=("gemma4:31b",))

    assert router.high_quality_retry_model == "gemma4:31b"
    assert router.high_quality_retry_available is False


def test_receipt_carries_retry_availability():
    runner = AudienceLiveRunner(
        client_factory=_InvalidJsonClient,
        failure_threshold=1.0,
        model_router=ModelRouter(
            model_pool=("model-a",), high_quality_retry_model="model-a"
        ),
    )
    receipt = runner.run(
        AudienceRunInput(topic="Retry visibility probe", run_seed="noretry")
    ).to_dict()["receipt"]

    assert receipt["model_routing"]["high_quality_retry_available"] is False


def test_failed_personas_with_a_dead_retry_layer_are_flagged():
    runner = AudienceLiveRunner(
        client_factory=_InvalidJsonClient,
        failure_threshold=1.0,
        model_router=ModelRouter(
            model_pool=("model-a",), high_quality_retry_model="model-a"
        ),
    )
    receipt = runner.run(
        AudienceRunInput(topic="Retry visibility probe", run_seed="dead")
    ).to_dict()["receipt"]
    kinds = {warning["kind"] for warning in receipt["quality_warnings"]}

    assert receipt["failed_persona_count"] == 20
    assert "retry_layer_unavailable" in kinds


def test_no_flag_when_a_second_model_was_actually_tried():
    runner = AudienceLiveRunner(
        client_factory=_InvalidJsonClient,
        failure_threshold=1.0,
        model_router=ModelRouter(
            model_pool=("model-a",), high_quality_retry_model="model-b"
        ),
    )
    receipt = runner.run(
        AudienceRunInput(topic="Retry visibility probe", run_seed="alive")
    ).to_dict()["receipt"]
    kinds = {warning["kind"] for warning in receipt["quality_warnings"]}

    assert receipt["high_quality_retry_count"] == 20
    assert "retry_layer_unavailable" not in kinds
