"""TableExtractionAgent: semantic interpretation of already-real table
grids, never re-derivation of table structure via LLM.

Row/column structure and raw cell text come from Phase 2's own pipeline
(DocumentChunk.metadata_json["tables"], populated by TableExtractor's
pdfplumber pass in app.worker.tasks); real per-table and per-cell
bounding boxes come from a fresh pdfplumber find_tables() pass
(TableGeometryExtractor, which - unlike Phase 2's TableExtractor - keeps
coordinates). The LLM only titles the table and normalizes cell values.
"""

from app.ai.engine.types import AgentContext
from app.ai.prompts.package import PromptPackage
from app.ai.prompts.registry import PromptRegistry
from app.ai.providers.base import LLMRequest, LLMUsage
from app.ai.structured.service import StructuredOutputService
from app.modules.documents.models import DocumentChunk
from app.modules.extraction.agents.schemas import (
    BoundingBoxModel,
    GroundedCell,
    GroundedTable,
    TableExtractionAgentOutput,
    TableExtractionOutput,
)
from app.modules.extraction.domain import sum_usage
from app.modules.extraction.geometry import TableGeometry, TableGeometryExtractor

RawTable = list[list[str | None]]


class TableExtractionAgent:
    def __init__(
        self,
        *,
        structured_output_service: StructuredOutputService,
        prompt_registry: PromptRegistry,
        model: str,
        chunks: list[DocumentChunk],
        pdf_bytes: bytes,
        table_geometry_extractor: TableGeometryExtractor | None = None,
    ) -> None:
        self._structured = structured_output_service
        self._prompts = prompt_registry
        self._model = model
        self._chunks = chunks
        self._pdf_bytes = pdf_bytes
        self._table_geometry = table_geometry_extractor or TableGeometryExtractor()

    @property
    def name(self) -> str:
        return "table_extraction"

    async def run(self, context: AgentContext) -> TableExtractionAgentOutput:
        raw_tables_by_page = _collect_raw_tables_by_page(self._chunks)
        if not raw_tables_by_page:
            return TableExtractionAgentOutput(tables=[], total_usage=LLMUsage())

        geometries = self._table_geometry.extract(self._pdf_bytes)
        geometries_by_page = _index_geometries_by_page(geometries)

        prompt = self._prompts.get("table_extraction")
        tables: list[GroundedTable] = []
        usages: list[LLMUsage] = []

        for page_number, raw_tables in raw_tables_by_page.items():
            page_geometries = geometries_by_page.get(page_number, [])
            for table_index, rows in enumerate(raw_tables):
                geometry = (
                    page_geometries[table_index] if table_index < len(page_geometries) else None
                )
                output, usage = await self._interpret_table(prompt, page_number, rows, context)
                usages.append(usage)
                tables.append(_build_grounded_table(page_number, rows, output, geometry))

        return TableExtractionAgentOutput(tables=tables, total_usage=sum_usage(usages))

    async def _interpret_table(
        self, prompt: PromptPackage, page_number: int, rows: RawTable, context: AgentContext
    ) -> tuple[TableExtractionOutput, LLMUsage]:
        system_prompt, user_prompt = prompt.render(
            page_number=page_number, table_grid=_format_grid(rows)
        )
        request = LLMRequest(
            model=self._model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            prompt_package_name=prompt.name,
            prompt_package_version=str(prompt.version),
        )
        return await self._structured.generate_structured_with_usage(
            request, TableExtractionOutput, correlation_id=context.correlation_id
        )


def _collect_raw_tables_by_page(chunks: list[DocumentChunk]) -> dict[int, list[RawTable]]:
    """Every chunk on the same page carries an identical copy of that
    page's tables in metadata_json["tables"] (see app.worker.tasks) - take
    the first occurrence per page only, or every table would be processed
    once per chunk on that page."""
    result: dict[int, list[RawTable]] = {}
    for chunk in chunks:
        if chunk.page_number is None or chunk.page_number in result:
            continue
        raw = (chunk.metadata_json or {}).get("tables")
        if raw:
            result[chunk.page_number] = raw
    return result


def _index_geometries_by_page(geometries: list[TableGeometry]) -> dict[int, list[TableGeometry]]:
    by_page: dict[int, list[TableGeometry]] = {}
    for geometry in geometries:
        by_page.setdefault(geometry.page_number, []).append(geometry)
    return by_page


def _format_grid(rows: RawTable) -> str:
    return "\n".join(" | ".join(cell or "" for cell in row) for row in rows)


def _build_grounded_table(
    page_number: int,
    rows: RawTable,
    output: TableExtractionOutput,
    geometry: TableGeometry | None,
) -> GroundedTable:
    normalized_by_cell = {(item.row, item.column): item for item in output.cells}
    column_count = max((len(row) for row in rows), default=0)

    cells: list[GroundedCell] = []
    for row_index, row in enumerate(rows):
        for column_index, raw_value in enumerate(row):
            normalized_item = normalized_by_cell.get((row_index, column_index))
            cell_bbox = geometry.cell_bboxes.get((row_index, column_index)) if geometry else None
            cells.append(
                GroundedCell(
                    row=row_index,
                    column=column_index,
                    raw_value=raw_value,
                    normalized_value=normalized_item.normalized_value if normalized_item else None,
                    confidence=normalized_item.confidence if normalized_item else 0.0,
                    bounding_box=BoundingBoxModel(**cell_bbox.to_json()) if cell_bbox else None,
                )
            )

    return GroundedTable(
        page_number=page_number,
        title=output.title,
        confidence=output.confidence,
        row_count=len(rows),
        column_count=column_count,
        bounding_box=BoundingBoxModel(**geometry.bbox.to_json()) if geometry else None,
        cells=cells,
    )
