import asyncio
import uuid

from app.core.database import AsyncSessionLocal
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.documents.models import Document, DocumentChunk, StorageProviderKind
from app.modules.extraction.models import (
    EntityMention,
    EntityType,
    ExtractedEntity,
    ExtractionRun,
    ExtractionStatus,
)
from app.modules.extraction.trust.models import (
    ConfidenceScore,
    NormalizationResult,
    TrustPipelineRun,
)


async def main() -> None:
    chunk_text = "Adani Ports owns Mundra Port in Gujarat, India."
    async with AsyncSessionLocal() as session:
        document = Document(
            filename=f"{uuid.uuid4().hex}.pdf",
            original_filename="report.pdf",
            extension=".pdf",
            mime_type="application/pdf",
            file_size=100,
            sha256_hash=uuid.uuid4().hex + "0" * 32,
            storage_provider=StorageProviderKind.LOCAL,
            storage_key=f"{uuid.uuid4().hex}.pdf",
        )
        session.add(document)
        await session.flush()

        chunk = DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            page_number=1,
            text=chunk_text,
            token_count=14,
            metadata_json={},
        )
        session.add(chunk)
        await session.flush()

        run = ExtractionRun(
            document_id=document.id,
            pipeline_version="3.2.0",
            provider="groq",
            model="test-model",
            prompt_version="1.0",
            prompt_hash="livehash",
            status=ExtractionStatus.COMPLETED,
            token_usage={},
        )
        session.add(run)
        await session.flush()

        company = ExtractedEntity(
            extraction_run_id=run.id, entity_type=EntityType.COMPANY, raw_value="Adani Ports",
            confidence=0.9, page_number=1, source_chunk=chunk.id,
            provider="groq", model="test-model", prompt_version="1.0",
        )
        port = ExtractedEntity(
            extraction_run_id=run.id, entity_type=EntityType.PORT, raw_value="Mundra Port",
            confidence=0.9, page_number=1, source_chunk=chunk.id,
            provider="groq", model="test-model", prompt_version="1.0",
        )
        country = ExtractedEntity(
            extraction_run_id=run.id, entity_type=EntityType.COUNTRY, raw_value="India",
            confidence=0.9, page_number=1, source_chunk=chunk.id,
            provider="groq", model="test-model", prompt_version="1.0",
        )
        session.add_all([company, port, country])
        await session.flush()

        session.add_all([
            EntityMention(entity_id=company.id, page_number=1,
                           character_offset=chunk_text.index("Adani Ports"),
                           surrounding_text=chunk_text, source_chunk=chunk.id),
            EntityMention(entity_id=port.id, page_number=1,
                           character_offset=chunk_text.index("Mundra Port"),
                           surrounding_text=chunk_text, source_chunk=chunk.id),
            EntityMention(entity_id=country.id, page_number=1,
                           character_offset=chunk_text.index("India"),
                           surrounding_text=chunk_text, source_chunk=chunk.id),
        ])
        session.add_all([
            NormalizationResult(entity_id=company.id, canonical_id="company:adani_ports_live",
                                 canonical_name="Adani Ports", normalized_value="Adani Ports",
                                 normalization_method="slug_derivation", confidence=1.0),
            NormalizationResult(entity_id=port.id, canonical_id="port:mundra_live",
                                 canonical_name="Mundra Port", normalized_value="Mundra Port",
                                 normalization_method="alias_lookup", confidence=1.0),
            NormalizationResult(entity_id=country.id, canonical_id="country:india_live",
                                 canonical_name="India", normalized_value="India",
                                 normalization_method="alias_lookup", confidence=1.0),
        ])

        def _score(entity_id: uuid.UUID) -> ConfidenceScore:
            return ConfidenceScore(
                entity_id=entity_id, overall_score=0.9, extraction_score=1.0, geometry_score=1.0,
                layout_score=1.0, table_score=1.0, consistency_score=1.0, normalization_score=1.0,
                validation_score=1.0, provider_score=1.0, explanation_json={},
            )

        session.add_all([_score(company.id), _score(port.id), _score(country.id)])

        trust_run = TrustPipelineRun(
            extraction_run_id=run.id, pipeline_version="3.3.0", rule_registry_version="1.0",
            status=ExtractionStatus.COMPLETED, entities_validated=3,
            entities_flagged_for_review=0, average_confidence=0.9,
        )
        session.add(trust_run)
        await session.commit()

        print(f"EXTRACTION_RUN_ID={run.id}")
        print(f"COMPANY_ENTITY_ID={company.id}")
        print(f"PORT_ENTITY_ID={port.id}")
        print(f"COUNTRY_ENTITY_ID={country.id}")
        print(f"DOCUMENT_ID={document.id}")


if __name__ == "__main__":
    asyncio.run(main())
