"""Builds the object graph the ARQ worker process needs: storage provider,
OCR provider, extractors, chunker, LLM client. Constructed once at worker
startup and stored in ARQ's ctx dict, not rebuilt per job - matters most
for OCR providers, where a real engine (PaddleOCR) is expensive to
initialize.
"""

from typing import Any

from ai_service.client.llm_client import LLMClient, get_llm_client
from ai_service.embeddings.base import EmbeddingProvider
from ai_service.embeddings.factory import get_embedding_provider
from ai_service.structured.service import StructuredOutputService
from shared.ai_exceptions import ConfigurationError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.documents.chunking.chunker import DocumentChunker
from app.modules.documents.extraction.image_extractor import ImageExtractor
from app.modules.documents.extraction.pdf_extractor import PDFExtractor
from app.modules.documents.extraction.table_extractor import TableExtractor
from app.modules.documents.ocr.tesseract_provider import TesseractOCRProvider
from app.modules.documents.storage.factory import get_storage_provider
from app.modules.extraction.prompts import get_extraction_prompt_registry

logger = get_logger(__name__)


def _build_llm_client() -> LLMClient | None:
    """None (with a logged warning), not a raised exception: an
    unconfigured LLM provider must not prevent the worker from starting
    at all - process_document (Phase 2's ingestion pipeline) never
    touches this. Only run_extraction (Phase 3.2) needs it, and it will
    fail clearly, per-job, if invoked with this still None - a real
    production deployment always has a real provider configured, so this
    path is a local-dev/CI convenience, not a production behavior.
    """
    try:
        return get_llm_client()
    except ConfigurationError as exc:
        logger.warning(
            "llm_provider_not_configured",
            detail=str(exc),
            note="run_extraction jobs will fail until an LLM provider is configured",
        )
        return None


def _build_embedding_provider() -> EmbeddingProvider | None:
    """None (with a logged warning), not a raised exception - same
    rationale as _build_llm_client(): Phase 5's embedding-generation task
    is optional, additive background work triggered off of ingestion/
    graph-rebuild, not something process_document/run_graph_rebuild
    themselves depend on. An unconfigured embedding provider must not
    prevent the worker from starting."""
    try:
        return get_embedding_provider()
    except ConfigurationError as exc:
        logger.warning(
            "embedding_provider_not_configured",
            detail=str(exc),
            note="generate_embeddings_task will skip until an embedding provider is configured",
        )
        return None


def build_worker_context() -> dict[str, Any]:
    settings = get_settings()
    ocr_provider = TesseractOCRProvider(tesseract_cmd=settings.ocr_tesseract_cmd)
    llm_client = _build_llm_client()
    return {
        "settings": settings,
        "storage": get_storage_provider(),
        "ocr_provider": ocr_provider,
        "pdf_extractor": PDFExtractor(
            ocr_provider=ocr_provider,
            ocr_language=settings.ocr_language,
            min_native_chars_per_page=settings.ocr_min_native_chars_per_page,
        ),
        "table_extractor": TableExtractor(),
        "image_extractor": ImageExtractor(
            ocr_provider=ocr_provider, ocr_language=settings.ocr_language
        ),
        "chunker": DocumentChunker(
            chunk_size_tokens=settings.chunk_size_tokens,
            chunk_overlap_tokens=settings.chunk_overlap_tokens,
        ),
        "llm_client": llm_client,
        "structured_output_service": StructuredOutputService(llm_client) if llm_client else None,
        "prompt_registry": get_extraction_prompt_registry(),
        "embedding_provider": _build_embedding_provider(),
    }
