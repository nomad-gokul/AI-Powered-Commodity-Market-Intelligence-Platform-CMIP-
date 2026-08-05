from shared.embedding_contracts import (
    EmbeddingModelCapabilities,
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingUsage,
)


class TestEmbeddingRequest:
    def test_defaults(self) -> None:
        request = EmbeddingRequest(texts=["hello", "world"], model="text-embedding-3-small")
        assert request.texts == ["hello", "world"]
        assert request.metadata == {}

    def test_metadata_roundtrip(self) -> None:
        request = EmbeddingRequest(
            texts=["a"], model="m", metadata={"source_type": "document_chunk"}
        )
        assert request.metadata["source_type"] == "document_chunk"


class TestEmbeddingResponse:
    def test_vectors_align_with_input_order(self) -> None:
        response = EmbeddingResponse(
            vectors=[[0.1, 0.2], [0.3, 0.4]],
            provider="openai",
            model="text-embedding-3-small",
            dimension=2,
            usage=EmbeddingUsage(prompt_tokens=10, total_tokens=10),
            latency_ms=42.0,
        )
        assert len(response.vectors) == 2
        assert response.dimension == 2
        assert response.usage.prompt_tokens == 10


class TestEmbeddingModelCapabilities:
    def test_is_frozen(self) -> None:
        capabilities = EmbeddingModelCapabilities(dimension=1536)
        assert capabilities.dimension == 1536
        assert capabilities.max_batch_size == 1
