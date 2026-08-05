import { mulberry32, randInt, randRange } from "./rng";
import type {
  ActivityEvent,
  ActivityEventKind,
  CommoditySnapshot,
  KpiSummary,
  WorldMapRegion,
} from "@/lib/types/dashboard";
import { COMMODITIES } from "@/lib/types/market";

const rng = mulberry32(90210);

export const KPI_SUMMARY: KpiSummary = {
  totalReports: 1284,
  totalReportsDelta: 4.8,
  knowledgeGraphNodes: 48392,
  knowledgeGraphNodesDelta: 2.3,
  validatedEntities: 12047,
  validatedEntitiesDelta: 1.6,
  retrievalRuns: 8213,
  retrievalRunsDelta: 9.1,
  aiConfidence: 94.2,
  aiConfidenceDelta: 0.4,
};

const ACTIVITY_TEMPLATES: Array<{
  kind: ActivityEventKind;
  title: string;
  detail: string;
  actor: string;
}> = [
  {
    kind: "document_ingested",
    title: "Report ingested",
    detail: "Argus Naphtha Weekly — 14 pages, OCR not required",
    actor: "Ingestion Worker",
  },
  {
    kind: "extraction_completed",
    title: "Extraction completed",
    detail: "42 entities and 6 tables extracted from Platts Coal Monitor",
    actor: "Extraction Pipeline",
  },
  {
    kind: "validation_flagged",
    title: "Validation flagged an inconsistency",
    detail: "Price unit mismatch on Baltic Exchange Freight Index row 18",
    actor: "Trust & Validation",
  },
  {
    kind: "graph_updated",
    title: "Knowledge graph rebuilt",
    detail: "312 nodes, 897 edges — 18 new company-port relationships",
    actor: "Graph Build Service",
  },
  {
    kind: "retrieval_run",
    title: "Retrieval run completed",
    detail: '"Naphtha market outlook India" — 24 candidates, 118ms',
    actor: "Hybrid Retriever",
  },
  {
    kind: "alert_raised",
    title: "Supply disruption alert raised",
    detail: "Port congestion detected at Jebel Ali — 3 related contracts",
    actor: "Alerting Engine",
  },
  {
    kind: "document_ingested",
    title: "Report ingested",
    detail: "Reuters LNG Freight Bulletin — 8 pages",
    actor: "Ingestion Worker",
  },
  {
    kind: "graph_updated",
    title: "Canonical entity resolved",
    detail: '"Adani Ports" merged with 2 alias variants',
    actor: "Trust & Validation",
  },
];

export const RECENT_ACTIVITY: ActivityEvent[] = ACTIVITY_TEMPLATES.map((template, index) => ({
  id: `activity-${index}`,
  ...template,
  timestamp: new Date(Date.now() - (index + 1) * randInt(rng, 6, 40) * 60_000).toISOString(),
}));

const WORLD_REGIONS: Array<
  Pick<WorldMapRegion, "countryCode" | "countryName" | "dominantCommodity" | "coordinates">
> = [
  { countryCode: "IN", countryName: "India", dominantCommodity: "Naphtha", coordinates: [78.9629, 20.5937] },
  { countryCode: "CN", countryName: "China", dominantCommodity: "Iron Ore", coordinates: [104.1954, 35.8617] },
  { countryCode: "US", countryName: "United States", dominantCommodity: "WTI Crude", coordinates: [-95.7129, 37.0902] },
  { countryCode: "AU", countryName: "Australia", dominantCommodity: "Thermal Coal", coordinates: [133.7751, -25.2744] },
  { countryCode: "ID", countryName: "Indonesia", dominantCommodity: "Coking Coal", coordinates: [113.9213, -0.7893] },
  { countryCode: "BR", countryName: "Brazil", dominantCommodity: "Iron Ore", coordinates: [-51.9253, -14.235] },
  { countryCode: "ZA", countryName: "South Africa", dominantCommodity: "Thermal Coal", coordinates: [22.9375, -30.5595] },
  { countryCode: "SA", countryName: "Saudi Arabia", dominantCommodity: "Brent Crude", coordinates: [45.0792, 23.8859] },
  { countryCode: "AE", countryName: "United Arab Emirates", dominantCommodity: "LNG", coordinates: [53.8478, 23.4241] },
  { countryCode: "SG", countryName: "Singapore", dominantCommodity: "Fuel Oil", coordinates: [103.8198, 1.3521] },
  { countryCode: "NL", countryName: "Netherlands", dominantCommodity: "Diesel", coordinates: [5.2913, 52.1326] },
  { countryCode: "QA", countryName: "Qatar", dominantCommodity: "LNG", coordinates: [51.1839, 25.3548] },
  { countryCode: "NG", countryName: "Nigeria", dominantCommodity: "Brent Crude", coordinates: [8.6753, 9.082] },
  { countryCode: "CL", countryName: "Chile", dominantCommodity: "Copper", coordinates: [-71.543, -35.6751] },
];

export const WORLD_MAP_REGIONS: WorldMapRegion[] = WORLD_REGIONS.map((region) => ({
  ...region,
  activityScore: Math.round(randRange(rng, 20, 100)),
  riskScore: Math.round(randRange(rng, 5, 90)),
}));

function sparkline(base: number, volatility: number): number[] {
  const points: number[] = [];
  let value = base;
  for (let i = 0; i < 14; i += 1) {
    value += randRange(rng, -volatility, volatility);
    points.push(Number(value.toFixed(2)));
  }
  return points;
}

export const TOP_COMMODITIES: CommoditySnapshot[] = COMMODITIES.map((commodity) => {
  const base = randRange(rng, 60, 420);
  const changePercent = Number(randRange(rng, -4.5, 4.5).toFixed(2));
  return {
    commodityId: commodity.id,
    name: commodity.name,
    shortName: commodity.shortName,
    price: Number(base.toFixed(2)),
    changePercent,
    sparkline: sparkline(base, base * 0.02),
  };
});
