export interface KpiSummary {
  totalReports: number;
  totalReportsDelta: number;
  knowledgeGraphNodes: number;
  knowledgeGraphNodesDelta: number;
  validatedEntities: number;
  validatedEntitiesDelta: number;
  retrievalRuns: number;
  retrievalRunsDelta: number;
  aiConfidence: number;
  aiConfidenceDelta: number;
}

export type ActivityEventKind =
  | "document_ingested"
  | "extraction_completed"
  | "validation_flagged"
  | "graph_updated"
  | "retrieval_run"
  | "alert_raised";

export interface ActivityEvent {
  id: string;
  kind: ActivityEventKind;
  title: string;
  detail: string;
  actor: string;
  timestamp: string;
}

export interface WorldMapRegion {
  countryCode: string;
  countryName: string;
  /** [longitude, latitude] — used for the geo effectScatter layer, plotted
   * directly on coordinates rather than matched against map polygon names
   * (sidesteps small-nation resolution/name-matching fragility for hubs
   * like Singapore/Qatar). */
  coordinates: [number, number];
  activityScore: number;
  riskScore: number;
  dominantCommodity: string;
}

export interface CommoditySnapshot {
  commodityId: string;
  name: string;
  shortName: string;
  price: number;
  changePercent: number;
  sparkline: number[];
}
