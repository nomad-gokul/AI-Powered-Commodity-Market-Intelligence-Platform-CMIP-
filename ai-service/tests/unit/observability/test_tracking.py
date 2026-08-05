"""Unit tests for record_llm_call: Prometheus metrics are updated, and a
failed call never touches the token/cost counters meant for successes."""

from shared.ai_contracts import LLMUsage

from ai_service.observability.metrics import (
    llm_call_duration_seconds,
    llm_call_failures_total,
    llm_estimated_cost_usd_total,
    llm_retries_total,
    llm_tokens_total,
)
from ai_service.observability.tracking import LLMCallObservation, record_llm_call


def _counter_value(counter: object, **labels: str) -> float:
    value = counter.labels(**labels)._value.get()  # type: ignore[attr-defined]
    return float(value)


class TestRecordLlmCall:
    def test_successful_call_increments_token_and_duration_metrics(self) -> None:
        before_prompt = _counter_value(
            llm_tokens_total, provider="test-provider", model="test-model-a", kind="prompt"
        )
        before_count = llm_call_duration_seconds.labels(
            provider="test-provider", model="test-model-a"
        )._sum.get()

        record_llm_call(
            LLMCallObservation(
                provider="test-provider",
                model="test-model-a",
                latency_ms=250.0,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                success=True,
                estimated_cost_usd=0.001,
            )
        )

        after_prompt = _counter_value(
            llm_tokens_total, provider="test-provider", model="test-model-a", kind="prompt"
        )
        after_count = llm_call_duration_seconds.labels(
            provider="test-provider", model="test-model-a"
        )._sum.get()
        cost = _counter_value(
            llm_estimated_cost_usd_total, provider="test-provider", model="test-model-a"
        )

        assert after_prompt == before_prompt + 10
        assert after_count > before_count
        assert cost >= 0.001

    def test_failed_call_increments_failure_counter_not_token_counter(self) -> None:
        before_failures = _counter_value(
            llm_call_failures_total,
            provider="test-provider",
            model="test-model-b",
            error_type="ProviderTimeoutError",
        )
        before_prompt = _counter_value(
            llm_tokens_total, provider="test-provider", model="test-model-b", kind="prompt"
        )

        record_llm_call(
            LLMCallObservation(
                provider="test-provider",
                model="test-model-b",
                latency_ms=0.0,
                usage=LLMUsage(),
                success=False,
                error_type="ProviderTimeoutError",
            )
        )

        after_failures = _counter_value(
            llm_call_failures_total,
            provider="test-provider",
            model="test-model-b",
            error_type="ProviderTimeoutError",
        )
        after_prompt = _counter_value(
            llm_tokens_total, provider="test-provider", model="test-model-b", kind="prompt"
        )
        assert after_failures == before_failures + 1
        assert after_prompt == before_prompt

    def test_retry_count_increments_retries_metric(self) -> None:
        before = _counter_value(llm_retries_total, provider="test-provider", model="test-model-c")

        record_llm_call(
            LLMCallObservation(
                provider="test-provider",
                model="test-model-c",
                latency_ms=1.0,
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                success=True,
                retry_count=2,
            )
        )

        after = _counter_value(llm_retries_total, provider="test-provider", model="test-model-c")
        assert after == before + 2
