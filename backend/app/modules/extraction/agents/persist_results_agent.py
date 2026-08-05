"""PersistResultsAgent: the pipeline's final stage, writing accumulated
entities/mentions/tables/cells to Postgres.

Unlike every other agent in this pipeline, this one makes no LLM call -
the Agent Protocol doesn't require one, it only requires
`async def run(context) -> Any`. Delete-then-insert scoped to its own
extraction_run_id, same idempotency pattern Phase 2 established for
DocumentChunk (see app.worker.tasks): re-running this step (a retry)
replaces rather than duplicates its rows.
"""

import uuid

from shared.agent_contracts import AgentContext

from app.modules.documents.models import DocumentChunk
from app.modules.extraction.agents.schemas import (
    EntityExtractionAgentOutput,
    GroundedEntity,
    GroundedTable,
    PersistResultsOutput,
    TableExtractionAgentOutput,
)
from app.modules.extraction.domain import find_mention_context
from app.modules.extraction.models import EntityMention, ExtractedEntity, ExtractedTable, TableCell
from app.modules.extraction.repository import (
    EntityMentionRepository,
    ExtractedEntityRepository,
    ExtractedTableRepository,
    TableCellRepository,
)


class PersistResultsAgent:
    def __init__(
        self,
        *,
        extraction_run_id: uuid.UUID,
        entity_repo: ExtractedEntityRepository,
        mention_repo: EntityMentionRepository,
        table_repo: ExtractedTableRepository,
        cell_repo: TableCellRepository,
        chunks: list[DocumentChunk],
        provider: str,
        model: str,
        entity_prompt_version: str,
        table_prompt_version: str,
    ) -> None:
        self._extraction_run_id = extraction_run_id
        self._entity_repo = entity_repo
        self._mention_repo = mention_repo
        self._table_repo = table_repo
        self._cell_repo = cell_repo
        self._chunks_by_id = {chunk.id: chunk for chunk in chunks}
        self._provider = provider
        self._model = model
        self._entity_prompt_version = entity_prompt_version
        self._table_prompt_version = table_prompt_version

    @property
    def name(self) -> str:
        return "persist_results"

    async def run(self, context: AgentContext) -> PersistResultsOutput:
        await self._entity_repo.delete_for_run(self._extraction_run_id)
        await self._table_repo.delete_for_run(self._extraction_run_id)

        entities_persisted = await self._persist_entities(context)
        tables_persisted, cells_persisted = await self._persist_tables(context)

        return PersistResultsOutput(
            extraction_run_id=self._extraction_run_id,
            entities_persisted=entities_persisted,
            tables_persisted=tables_persisted,
            cells_persisted=cells_persisted,
        )

    async def _persist_entities(self, context: AgentContext) -> int:
        entity_output = context.state.get("entity_extraction")
        if not isinstance(entity_output, EntityExtractionAgentOutput):
            return 0

        entity_rows = [self._build_entity_row(item) for item in entity_output.entities]
        created = await self._entity_repo.bulk_create(entity_rows)

        mention_rows = [
            self._build_mention_row(entity_row, item)
            for entity_row, item in zip(created, entity_output.entities, strict=True)
        ]
        await self._mention_repo.bulk_create(mention_rows)
        return len(created)

    def _build_entity_row(self, item: GroundedEntity) -> ExtractedEntity:
        return ExtractedEntity(
            extraction_run_id=self._extraction_run_id,
            entity_type=item.entity_type,
            raw_value=item.raw_value,
            normalized_value=item.normalized_value,
            confidence=item.confidence,
            page_number=item.page_number,
            bounding_box=item.bounding_box.model_dump() if item.bounding_box else None,
            source_chunk=item.source_chunk_id,
            provider=self._provider,
            model=self._model,
            prompt_version=self._entity_prompt_version,
        )

    def _build_mention_row(
        self, entity_row: ExtractedEntity, item: GroundedEntity
    ) -> EntityMention:
        chunk = self._chunks_by_id.get(item.source_chunk_id) if item.source_chunk_id else None
        if chunk is not None:
            offset, surrounding_text = find_mention_context(item.raw_value, chunk.text)
        else:
            offset, surrounding_text = None, item.raw_value
        return EntityMention(
            entity_id=entity_row.id,
            page_number=item.page_number or 0,
            character_offset=offset,
            surrounding_text=surrounding_text,
            source_chunk=item.source_chunk_id,
        )

    async def _persist_tables(self, context: AgentContext) -> tuple[int, int]:
        table_output = context.state.get("table_extraction")
        if not isinstance(table_output, TableExtractionAgentOutput):
            return 0, 0

        table_rows = [self._build_table_row(item) for item in table_output.tables]
        created_tables = await self._table_repo.bulk_create(table_rows)

        cell_rows: list[TableCell] = []
        for table_row, item in zip(created_tables, table_output.tables, strict=True):
            for cell in item.cells:
                cell_rows.append(
                    TableCell(
                        table_id=table_row.id,
                        row=cell.row,
                        column=cell.column,
                        raw_value=cell.raw_value,
                        normalized_value=cell.normalized_value,
                        confidence=cell.confidence,
                    )
                )
        await self._cell_repo.bulk_create(cell_rows)
        return len(created_tables), len(cell_rows)

    def _build_table_row(self, item: GroundedTable) -> ExtractedTable:
        bounding_box = item.bounding_box.model_dump() if item.bounding_box else None
        return ExtractedTable(
            extraction_run_id=self._extraction_run_id,
            page_number=item.page_number,
            title=item.title,
            confidence=item.confidence,
            row_count=item.row_count,
            column_count=item.column_count,
            metadata_json={"bounding_box": bounding_box},
        )
