"""Unit tests for build_worker_context()'s graceful LLM-provider
degradation: an unconfigured provider must not prevent the worker from
starting - only run_extraction (which actually needs it) is affected.

Regression test for a real bug this exact scenario caused: wiring an
LLMClient into build_worker_context() unconditionally broke every
Phase 2 ingestion test (process_document never touches an LLM) the first
time this dev environment's GROQ_API_KEY was unset - caught by running
the full suite, not by any single test in isolation.
"""

import pytest
from shared.ai_exceptions import ConfigurationError

from app.worker import context as context_module


class TestBuildLlmClient:
    def test_returns_none_when_provider_is_unconfigured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise() -> None:
            raise ConfigurationError("GROQ_API_KEY is required when LLM_PROVIDER=groq")

        monkeypatch.setattr(context_module, "get_llm_client", _raise)
        assert context_module._build_llm_client() is None

    def test_returns_the_client_when_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = object()
        monkeypatch.setattr(context_module, "get_llm_client", lambda: sentinel)
        assert context_module._build_llm_client() is sentinel


class TestBuildEmbeddingProvider:
    """Same graceful-degradation rationale as TestBuildLlmClient, for
    Phase 5's generate_embeddings_task: an unconfigured embedding provider
    must not prevent the worker from starting - only that one optional
    task is affected."""

    def test_returns_none_when_provider_is_unconfigured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise() -> None:
            raise ConfigurationError("OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai")

        monkeypatch.setattr(context_module, "get_embedding_provider", _raise)
        assert context_module._build_embedding_provider() is None

    def test_returns_the_provider_when_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = object()
        monkeypatch.setattr(context_module, "get_embedding_provider", lambda: sentinel)
        assert context_module._build_embedding_provider() is sentinel


class TestBuildWorkerContext:
    def test_structured_output_service_is_none_when_llm_client_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(context_module, "_build_llm_client", lambda: None)
        ctx = context_module.build_worker_context()
        assert ctx["llm_client"] is None
        assert ctx["structured_output_service"] is None

    def test_context_always_has_the_non_llm_ingestion_dependencies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(context_module, "_build_llm_client", lambda: None)
        ctx = context_module.build_worker_context()
        for key in ("storage", "ocr_provider", "pdf_extractor", "table_extractor", "chunker"):
            assert ctx[key] is not None

    def test_embedding_provider_key_is_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(context_module, "_build_llm_client", lambda: None)
        monkeypatch.setattr(context_module, "_build_embedding_provider", lambda: None)
        ctx = context_module.build_worker_context()
        assert "embedding_provider" in ctx
