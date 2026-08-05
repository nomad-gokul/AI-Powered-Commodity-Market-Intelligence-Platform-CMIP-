import { mulberry32, pick, randInt, randRange } from "./rng";
import { REPORTS } from "./reports";
import type {
  EntityStatus,
  GraphDataset,
  GraphEdgeData,
  GraphEdgeEvidence,
  GraphEdgeType,
  GraphNodeData,
  GraphNodeType,
  RiskTier,
} from "@/lib/types/graph";

const rng = mulberry32(60221409);

const STATUSES: EntityStatus[] = ["active", "active", "active", "watch", "dormant"];
const RISKS: RiskTier[] = ["low", "moderate", "elevated", "high"];

function isoDaysAgo(days: number): string {
  return new Date(Date.now() - days * 86_400_000).toISOString();
}

function id(type: GraphNodeType, name: string): string {
  return `${type}:${name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")}`;
}

// ---------------------------------------------------------------------------
// Core entities — names taken directly from the brief's examples, extended
// with a few more of the same real-world archetype for a graph dense enough
// to feel like a real intelligence product.
// ---------------------------------------------------------------------------

const COMPANIES = [
  { name: "Adani Ports", sector: "Port Operator", hq: "India" },
  { name: "Reliance Industries", sector: "Integrated Refining", hq: "India" },
  { name: "Shell", sector: "Integrated Oil & Gas", hq: "Netherlands" },
  { name: "BP", sector: "Integrated Oil & Gas", hq: "United Kingdom" },
  { name: "Trafigura", sector: "Commodity Trading", hq: "Singapore" },
  { name: "Glencore", sector: "Commodity Trading", hq: "Switzerland" },
  { name: "Vitol", sector: "Commodity Trading", hq: "Switzerland" },
  { name: "QatarEnergy", sector: "State Energy Company", hq: "Qatar" },
];

const PORTS = [
  { name: "Mundra", country: "India" },
  { name: "Singapore", country: "Singapore" },
  { name: "Rotterdam", country: "Netherlands" },
  { name: "Fujairah", country: "United Arab Emirates" },
  { name: "Jebel Ali", country: "United Arab Emirates" },
  { name: "Ningbo-Zhoushan", country: "China" },
  { name: "Richards Bay", country: "South Africa" },
];

const COUNTRIES = ["India", "Indonesia", "China", "Singapore", "Saudi Arabia", "United Arab Emirates"];

const COMMODITIES = [
  { name: "Thermal Coal", unit: "USD/t" },
  { name: "Coking Coal", unit: "USD/t" },
  { name: "Brent Crude", unit: "USD/bbl" },
  { name: "WTI Crude", unit: "USD/bbl" },
  { name: "Naphtha", unit: "USD/t" },
  { name: "Diesel", unit: "USD/bbl" },
  { name: "LNG", unit: "USD/MMBtu" },
  { name: "Iron Ore", unit: "USD/t" },
];

const SHIP_NAMES = [
  "MT Ocean Pride",
  "MV Cape Endeavour",
  "MT Gulf Voyager",
  "MV Pacific Harmony",
  "MT Coral Navigator",
  "MV Atlas Trader",
  "MT Horizon Star",
];

const SHIP_TYPES = ["VLCC", "Panamax", "Capesize", "Aframax", "LNG Carrier"];
const CONTRACT_TYPES = ["FOB Term Contract", "CFR Spot Cargo", "Time Charter Agreement", "Supply & Offtake Agreement"];

function evidenceFor(nodeOrEdgeId: string, documentTitle: string, count: number): GraphEdgeEvidence[] {
  return Array.from({ length: count }).map((_, index) => ({
    id: `${nodeOrEdgeId}-ev-${index}`,
    documentId: `doc-${Math.floor(rng() * 1_000_000)}`,
    documentTitle,
    page: randInt(rng, 1, 24),
    chunkId: `chunk-${Math.floor(rng() * 1_000_000)}`,
    confidence: Number(randRange(rng, 0.7, 0.98).toFixed(2)),
    timestamp: isoDaysAgo(randInt(rng, 1, 60)),
    pipeline: "extraction-v2 → validation-v1 → graph-build-v3",
    promptVersion: `graph-entity-linker@${pick(rng, ["1.4.0", "1.4.1", "1.5.0"])}`,
    snippet: `…referenced in connection with recent market activity, corroborated by cross-source validation…`,
  }));
}

function buildNode(
  type: GraphNodeType,
  name: string,
  overrides: Record<string, string>,
  summary: string
): GraphNodeData {
  return {
    id: id(type, name),
    type,
    name,
    canonicalId: id(type, name),
    aliases: rng() > 0.6 ? [`${name.split(" ")[0]}`] : [],
    confidence: Number(randRange(rng, 0.72, 0.99).toFixed(2)),
    status: pick(rng, STATUSES),
    risk: pick(rng, RISKS),
    // Spans from "just added" through ~11 months back so every timeline
    // window (Week/Month/Quarter/Year) has a genuinely different, non-empty
    // graph to show rather than the scrubber going blank at the tight end.
    firstSeen: isoDaysAgo(randInt(rng, 1, 340)),
    lastActivity: isoDaysAgo(randInt(rng, 0, 21)),
    summary,
    facts: overrides,
  };
}

const nodes: GraphNodeData[] = [];
const edges: GraphEdgeData[] = [];

const companyNodes = COMPANIES.map((c) =>
  buildNode(
    "company",
    c.name,
    { Sector: c.sector, Headquarters: c.hq, "Founded": String(randInt(rng, 1955, 2005)) },
    `${c.name} is active across ${randInt(rng, 2, 5)} commodity markets with ${randInt(rng, 3, 12)} tracked counterparties.`
  )
);
const portNodes = PORTS.map((p) =>
  buildNode(
    "port",
    p.name,
    { Country: p.country, Berths: String(randInt(rng, 8, 40)), "Annual Throughput": `${randInt(rng, 40, 550)} MT` },
    `${p.name} handles ${pick(rng, ["dry bulk", "crude", "LNG", "containerized"])} cargo with ${randInt(rng, 2, 9)} active vessel calls this month.`
  )
);
const countryNodes = COUNTRIES.map((name) =>
  buildNode(
    "country",
    name,
    { Region: pick(rng, ["APAC", "Middle East", "EMEA"]), "Primary Export": pick(rng, COMMODITIES).name },
    `${name} shows ${pick(rng, ["strengthening", "stable", "softening"])} trade activity across tracked commodities.`
  )
);
const commodityNodes = COMMODITIES.map((c) =>
  buildNode(
    "commodity",
    c.name,
    { Unit: c.unit, Category: pick(rng, ["Energy", "Metals", "Refined Products"]) },
    `${c.name} assessments reference ${randInt(rng, 4, 15)} entities across the current reporting window.`
  )
);
const shipNodes = SHIP_NAMES.map((name) =>
  buildNode(
    "ship",
    name,
    { Type: pick(rng, SHIP_TYPES), "Flag State": pick(rng, COUNTRIES), DWT: `${randInt(rng, 80, 320)}k` },
    `${name} has completed ${randInt(rng, 2, 11)} tracked voyages in the last quarter.`
  )
);
const contractNodes = Array.from({ length: 9 }).map((_, i) => {
  const commodity = pick(rng, COMMODITIES);
  const type = pick(rng, CONTRACT_TYPES);
  const name = `${type} — ${commodity.name} #${1000 + i}`;
  return buildNode(
    "contract",
    name,
    { Type: type, Volume: `${randInt(rng, 20, 180)}k t`, Commodity: commodity.name },
    `A ${type.toLowerCase()} covering ${commodity.name.toLowerCase()}, cross-referenced against ${randInt(rng, 1, 4)} filed reports.`
  );
});
const reportSubset = REPORTS.slice(0, 14);
const reportNodes = reportSubset.map((r) =>
  buildNode(
    "report",
    r.title,
    { Source: r.source, Country: r.country, Pages: String(r.pageCount) },
    r.summary
  )
);
// Preserve the real report id so the Inspector can deep-link to /reports/[id].
reportNodes.forEach((node, index) => {
  node.canonicalId = reportSubset[index].id;
  node.facts["Confidence Score"] = `${reportSubset[index].confidence}%`;
});

nodes.push(...companyNodes, ...portNodes, ...countryNodes, ...commodityNodes, ...shipNodes, ...contractNodes, ...reportNodes);

function addEdge(
  sourceNode: GraphNodeData | undefined,
  targetNode: GraphNodeData | undefined,
  type: GraphEdgeType,
  documentTitle: string
) {
  if (!sourceNode || !targetNode) return;
  const edgeId = `${sourceNode.id}--${type}--${targetNode.id}`;
  if (edges.some((e) => e.id === edgeId)) return;
  edges.push({
    id: edgeId,
    source: sourceNode.id,
    target: targetNode.id,
    type,
    confidence: Number(randRange(rng, 0.68, 0.97).toFixed(2)),
    createdAt: isoDaysAgo(randInt(rng, 1, 300)),
    evidence: evidenceFor(edgeId, documentTitle, randInt(rng, 1, 3)),
  });
}

function byName(list: GraphNodeData[], name: string) {
  return list.find((n) => n.name === name);
}

// Companies own/operate ports, located in countries.
companyNodes.forEach((company) => {
  const port = pick(rng, portNodes);
  if (rng() > 0.4) addEdge(company, port, "OWNS", pick(rng, reportSubset).title);
  else addEdge(company, port, "OPERATES", pick(rng, reportSubset).title);
  const hqCountry = byName(countryNodes, company.facts.Headquarters);
  if (hqCountry) addEdge(company, hqCountry, "LOCATED_IN", pick(rng, reportSubset).title);
});

// Ports located in their country.
portNodes.forEach((port) => {
  const country = byName(countryNodes, port.facts.Country);
  addEdge(port, country, "LOCATED_IN", pick(rng, reportSubset).title);
});

// Ships shipped from/to ports.
shipNodes.forEach((ship) => {
  const [from, to] = [pick(rng, portNodes), pick(rng, portNodes)];
  addEdge(ship, from, "SHIPPED_FROM", pick(rng, reportSubset).title);
  if (to.id !== from.id) addEdge(ship, to, "SHIPPED_TO", pick(rng, reportSubset).title);
  const operator = pick(rng, companyNodes);
  addEdge(operator, ship, "OPERATES", pick(rng, reportSubset).title);
});

// Companies supply commodities.
companyNodes.forEach((company) => {
  const count = randInt(rng, 1, 3);
  for (let i = 0; i < count; i += 1) {
    addEdge(company, pick(rng, commodityNodes), "SUPPLIES", pick(rng, reportSubset).title);
  }
});

// Contracts reference commodities and a counterparty company; ships connect to contracts.
contractNodes.forEach((contract) => {
  const commodity = byName(commodityNodes, contract.facts.Commodity);
  addEdge(contract, commodity, "REFERENCES", pick(rng, reportSubset).title);
  addEdge(pick(rng, companyNodes), contract, "OWNS", pick(rng, reportSubset).title);
  if (rng() > 0.5) addEdge(pick(rng, shipNodes), contract, "CONNECTED_TO", pick(rng, reportSubset).title);
});

// Reports reference the entities they discuss.
reportNodes.forEach((reportNode, index) => {
  const sourceReport = reportSubset[index];
  const targets = [
    pick(rng, companyNodes),
    pick(rng, portNodes),
    byName(countryNodes, sourceReport.country) ?? pick(rng, countryNodes),
    pick(rng, commodityNodes),
  ];
  targets.forEach((target) => addEdge(reportNode, target, "REFERENCES", sourceReport.title));
});

// A handful of company-to-company trading relationships for graph density.
for (let i = 0; i < 6; i += 1) {
  const [a, b] = [pick(rng, companyNodes), pick(rng, companyNodes)];
  if (a.id !== b.id) addEdge(a, b, "CONNECTED_TO", pick(rng, reportSubset).title);
}

export const GRAPH_DATASET: GraphDataset = { nodes, edges };
