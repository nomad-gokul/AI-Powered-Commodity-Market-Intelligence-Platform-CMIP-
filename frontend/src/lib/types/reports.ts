export type ReportSource =
  | "Argus"
  | "Platts"
  | "Reuters"
  | "ICE"
  | "CME"
  | "Baltic Exchange"
  | "Internal";

export const REPORT_SOURCES: ReportSource[] = [
  "Argus",
  "Platts",
  "Reuters",
  "ICE",
  "CME",
  "Baltic Exchange",
  "Internal",
];

export type ProcessingStageId =
  | "uploaded"
  | "ocr"
  | "extraction"
  | "validation"
  | "knowledge_graph"
  | "embeddings"
  | "indexed";

export const PROCESSING_STAGES: Array<{ id: ProcessingStageId; label: string }> = [
  { id: "uploaded", label: "Uploaded" },
  { id: "ocr", label: "OCR" },
  { id: "extraction", label: "Extraction" },
  { id: "validation", label: "Validation" },
  { id: "knowledge_graph", label: "Knowledge Graph" },
  { id: "embeddings", label: "Embeddings" },
  { id: "indexed", label: "Indexed" },
];

export interface ProcessingStageStatus {
  stage: ProcessingStageId;
  status: "pending" | "in_progress" | "completed" | "failed";
}

export type ReportEntityType = "company" | "country" | "port" | "commodity" | "contract" | "ship";

export interface ReportEntity {
  id: string;
  name: string;
  type: ReportEntityType;
  mentionCount: number;
  canonicalId: string | null;
  /** Snippet of document text this entity appears in — used to demo the
   * "clicking an entity highlights it" interaction against the mock
   * document surface in the report viewer. */
  sampleSnippet: string;
}

export interface ReportTable {
  id: string;
  title: string;
  page: number;
  rowCount: number;
  columnCount: number;
}

export interface ReportValidationResult {
  id: string;
  rule: string;
  severity: "info" | "warning" | "critical";
  passed: boolean;
  message: string;
}

export interface ReportRelationship {
  id: string;
  sourceEntityId: string;
  targetEntityId: string;
  relationshipType: string;
  confidence: number;
}

export interface ReportTimelineEvent {
  id: string;
  label: string;
  timestamp: string;
  actor: string;
}

export interface Report {
  id: string;
  title: string;
  source: ReportSource;
  commodityIds: string[];
  country: string;
  summary: string;
  confidence: number;
  pageCount: number;
  entities: ReportEntity[];
  tables: ReportTable[];
  validationResults: ReportValidationResult[];
  relationships: ReportRelationship[];
  timeline: ReportTimelineEvent[];
  tags: string[];
  uploadedAt: string;
  processingStages: ProcessingStageStatus[];
  status: "processing" | "completed" | "failed";
}

export interface ReportFilters {
  sources: ReportSource[];
  commodityId: string | null;
  country: string | null;
  tag: string | null;
  query: string;
}
