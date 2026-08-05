import { mulberry32, pick, randInt, randRange } from "./rng";
import { COMMODITIES } from "@/lib/types/market";
import {
  PROCESSING_STAGES,
  REPORT_SOURCES,
  type Report,
  type ReportEntity,
  type ReportEntityType,
  type ReportRelationship,
  type ReportTable,
  type ReportTimelineEvent,
  type ReportValidationResult,
} from "@/lib/types/reports";

const rng = mulberry32(773311);

const COUNTRIES = [
  "India",
  "China",
  "United States",
  "Saudi Arabia",
  "Australia",
  "Indonesia",
  "Brazil",
  "Qatar",
  "United Arab Emirates",
  "Singapore",
];

const COMPANIES = [
  "Reliance Industries",
  "Indian Oil Corporation",
  "Adani Ports",
  "Vitol",
  "Glencore",
  "Trafigura",
  "Shell",
  "Rio Tinto",
  "Vale",
  "QatarEnergy",
];

const SHIPS = ["MT Ocean Pride", "MV Cape Endeavour", "MT Gulf Voyager", "MV Pacific Harmony"];
const CONTRACTS = ["FOB Term Contract Q3", "CFR Spot Cargo", "Time Charter Agreement", "Supply & Offtake Agreement"];

const REPORT_TITLE_TEMPLATES: Array<(commodity: string, country: string) => string> = [
  (c, country) => `${c} Weekly Market Assessment — ${country}`,
  (c) => `${c} Price Outlook and Supply Analysis`,
  (c, country) => `${country} ${c} Trade Flow Report`,
  (c) => `${c} Monthly Fundamentals Review`,
  (c, country) => `${country} Refinery & ${c} Capacity Update`,
];

const TAGS_POOL = ["supply", "demand", "freight", "sanctions", "weather", "refinery", "exports", "inventory", "price-assessment"];

function entityFor(type: ReportEntityType, commodityName: string): ReportEntity {
  const pools: Record<ReportEntityType, string[]> = {
    company: COMPANIES,
    country: COUNTRIES,
    port: ["Jebel Ali", "Fujairah", "Singapore", "Rotterdam", "Ningbo-Zhoushan", "Houston", "Sikka"],
    commodity: [commodityName],
    contract: CONTRACTS,
    ship: SHIPS,
  };
  const name = pick(rng, pools[type]);
  return {
    id: `entity-${type}-${Math.floor(rng() * 1_000_000)}`,
    name,
    type,
    mentionCount: randInt(rng, 1, 14),
    canonicalId: type === "company" || type === "country" || type === "port" ? name.toLowerCase().replace(/\s+/g, "-") : null,
    sampleSnippet: `…${name} was referenced in connection with recent ${commodityName.toLowerCase()} market activity, reflecting shifts in regional positioning…`,
  };
}

function tablesFor(): ReportTable[] {
  const count = randInt(rng, 1, 4);
  return Array.from({ length: count }).map((_, index) => ({
    id: `table-${index}-${Math.floor(rng() * 1_000_000)}`,
    title: pick(rng, ["Price Assessment Summary", "Regional Supply Balance", "Vessel Loading Schedule", "Inventory by Region", "Freight Rate Matrix"]),
    page: randInt(rng, 1, 12),
    rowCount: randInt(rng, 4, 22),
    columnCount: randInt(rng, 3, 8),
  }));
}

function validationResultsFor(): ReportValidationResult[] {
  const count = randInt(rng, 2, 5);
  const rules = [
    "unit_consistency",
    "price_range_plausibility",
    "entity_alias_resolution",
    "date_sequence_check",
    "duplicate_table_detection",
  ];
  return Array.from({ length: count }).map((_, index) => {
    const passed = rng() > 0.22;
    return {
      id: `validation-${index}-${Math.floor(rng() * 1_000_000)}`,
      rule: pick(rng, rules),
      severity: passed ? "info" : pick(rng, ["warning", "critical"] as const),
      passed,
      message: passed
        ? "Passed automated consistency check."
        : "Flagged for review — value falls outside the expected historical range.",
    };
  });
}

function timelineFor(uploadedAt: string): ReportTimelineEvent[] {
  const base = new Date(uploadedAt).getTime();
  return [
    { id: "t-uploaded", label: "Document uploaded", timestamp: new Date(base).toISOString(), actor: "Ingestion Worker" },
    { id: "t-ocr", label: "OCR completed", timestamp: new Date(base + 15_000).toISOString(), actor: "OCR Pipeline" },
    { id: "t-extraction", label: "Entities & tables extracted", timestamp: new Date(base + 48_000).toISOString(), actor: "Extraction Pipeline" },
    { id: "t-validation", label: "Validation completed", timestamp: new Date(base + 76_000).toISOString(), actor: "Trust & Validation" },
    { id: "t-graph", label: "Knowledge graph updated", timestamp: new Date(base + 112_000).toISOString(), actor: "Graph Build Service" },
    { id: "t-embed", label: "Embeddings generated", timestamp: new Date(base + 138_000).toISOString(), actor: "Embedding Service" },
    { id: "t-indexed", label: "Indexed for retrieval", timestamp: new Date(base + 150_000).toISOString(), actor: "Hybrid Retriever" },
  ];
}

export const REPORTS: Report[] = Array.from({ length: 28 }).map((_, index) => {
  const commodity = pick(rng, COMMODITIES);
  const country = pick(rng, COUNTRIES);
  const source = rng() > 0.85 ? "Internal" : pick(rng, REPORT_SOURCES.filter((s) => s !== "Internal"));
  const title = pick(rng, REPORT_TITLE_TEMPLATES)(commodity.name, country);
  const uploadedAt = new Date(Date.now() - randInt(rng, 1, 21) * 86_400_000 - randInt(rng, 0, 82_800) * 1000).toISOString();

  const entities: ReportEntity[] = [
    entityFor("company", commodity.name),
    entityFor("company", commodity.name),
    entityFor("country", commodity.name),
    entityFor("port", commodity.name),
    entityFor("commodity", commodity.name),
    ...(rng() > 0.5 ? [entityFor("contract", commodity.name)] : []),
    ...(rng() > 0.6 ? [entityFor("ship", commodity.name)] : []),
  ];

  const relationships: ReportRelationship[] = entities.slice(0, -1).map((entity, i) => ({
    id: `rel-${index}-${i}`,
    sourceEntityId: entity.id,
    targetEntityId: entities[i + 1].id,
    relationshipType: pick(rng, ["supplies_to", "operates_in", "loaded_at", "party_to", "exports_from"]),
    confidence: Number(randRange(rng, 0.68, 0.98).toFixed(2)),
  }));

  const isProcessing = index < 2;
  const stageCount = isProcessing ? randInt(rng, 1, PROCESSING_STAGES.length - 1) : PROCESSING_STAGES.length;

  return {
    id: `report-${index}`,
    title,
    source,
    commodityIds: [commodity.id],
    country,
    summary: `${commodity.name} markets in ${country} showed notable movement this period, with desks citing shifts in ${pick(rng, ["refinery utilization", "export availability", "freight costs", "inventory positioning"])}. This report covers price assessments, trade flow, and near-term outlook.`,
    confidence: Number(randRange(rng, 74, 98).toFixed(1)),
    pageCount: randInt(rng, 4, 26),
    entities,
    tables: tablesFor(),
    validationResults: validationResultsFor(),
    relationships,
    timeline: timelineFor(uploadedAt),
    tags: Array.from(new Set(Array.from({ length: randInt(rng, 2, 4) }).map(() => pick(rng, TAGS_POOL)))),
    uploadedAt,
    processingStages: PROCESSING_STAGES.map((stage, i) => ({
      stage: stage.id,
      status: i < stageCount ? "completed" : i === stageCount ? "in_progress" : "pending",
    })),
    status: isProcessing ? "processing" : "completed",
  } satisfies Report;
}).sort((a, b) => new Date(b.uploadedAt).getTime() - new Date(a.uploadedAt).getTime());
