import { mulberry32, pick, randInt, randRange } from "./rng";
import { PORT_COORDINATES, PORT_NAMES } from "@/lib/geo/ports";
import { COMMODITIES, type MarketQuote, type RiskLevel } from "@/lib/types/market";
import type {
  AiCommentaryBlock,
  CommodityDetail,
  DriverItem,
  InventoryPoint,
  MarketNewsItem,
  MarketRisk,
  RelatedEntityRef,
  TradeRoute,
  TrendPoint,
} from "@/lib/types/market-detail";

const rng = mulberry32(482913);

const COMPANIES = [
  "Reliance Industries",
  "Indian Oil Corporation",
  "Adani Ports",
  "Vitol",
  "Glencore",
  "Trafigura",
  "Shell",
  "BP",
  "TotalEnergies",
  "Rio Tinto",
  "Vale",
  "BHP",
  "Rosneft",
  "Saudi Aramco",
  "QatarEnergy",
  "Cargill",
  "Maersk",
  "COSCO Shipping",
];

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
  "Russia",
  "Nigeria",
  "South Africa",
  "Chile",
  "Netherlands",
  "Singapore",
];

function pickUnique<T>(count: number, pool: readonly T[]): T[] {
  const shuffled = [...pool].sort(() => rng() - 0.5);
  return shuffled.slice(0, count);
}

const SUPPLY_TEMPLATES = [
  (c: string, country: string) => `${country} refinery maintenance is trimming ${c} output`,
  (c: string, _country: string, company: string) => `${company} restarts ${c} production after a planned outage`,
  (c: string, _country: string, _company: string, port: string) => `Port congestion at ${port} is delaying ${c} cargo discharge`,
  (c: string) => `New ${c} export terminal capacity is coming online next quarter`,
  (c: string, country: string) => `${country} export quotas are tightening near-term ${c} availability`,
];

const DEMAND_TEMPLATES = [
  (c: string, country: string) => `${country} industrial activity signals stronger ${c} demand`,
  (c: string) => `Seasonal ${c} demand is building ahead of peak season`,
  (c: string, _country: string, company: string) => `${company} increased ${c} procurement for next quarter's contracts`,
  (c: string, country: string) => `Softer ${country} manufacturing PMI is weighing on ${c} demand`,
  (c: string) => `Power-sector switching is lifting ${c} consumption amid gas price volatility`,
];

const RISK_TEMPLATES: Array<{
  category: MarketRisk["category"];
  build: (c: string, country: string, port: string) => string;
}> = [
  { category: "supply", build: (c, country) => `${country} supply disruption risk for ${c} remains elevated into next month` },
  { category: "demand", build: (c, country) => `A demand slowdown in ${country} could soften ${c} assessments` },
  { category: "weather", build: (c) => `Seasonal weather patterns are adding volatility to ${c} logistics` },
  { category: "geopolitical", build: (c, country) => `Geopolitical tension involving ${country} is a watch factor for ${c}` },
  { category: "logistics", build: (c, _country, port) => `Vessel availability at ${port} is constraining ${c} loadings` },
];

function buildDriver(
  templates: Array<(c: string, country: string, company: string, port: string) => string>,
  commodityName: string,
  impact: DriverItem["impact"]
): DriverItem {
  const template = pick(rng, templates);
  const country = pick(rng, COUNTRIES);
  const company = pick(rng, COMPANIES);
  const port = pick(rng, PORT_NAMES);
  const detail = template(commodityName, country, company, port);
  return { label: detail.split(" ").slice(0, 4).join(" "), detail, impact };
}

function buildRisk(commodityId: string, commodityName: string): MarketRisk {
  const template = pick(rng, RISK_TEMPLATES);
  const country = pick(rng, COUNTRIES);
  const port = pick(rng, PORT_NAMES);
  const severities: RiskLevel[] = ["low", "moderate", "elevated", "high"];
  return {
    id: `${commodityId}-risk-${Math.floor(rng() * 1_000_000)}`,
    label: `${template.category[0].toUpperCase()}${template.category.slice(1)} watch`,
    severity: pick(rng, severities),
    category: template.category,
    detail: template.build(commodityName, country, port),
  };
}

function priceHistory(base: number, days: number): TrendPoint[] {
  const points: TrendPoint[] = [];
  let value = base;
  const now = Date.now();
  for (let i = days; i >= 0; i -= 1) {
    value += randRange(rng, -base * 0.012, base * 0.012);
    points.push({
      timestamp: new Date(now - i * 86_400_000).toISOString(),
      price: Number(value.toFixed(2)),
    });
  }
  return points;
}

function tradeRoutesFor(commodityId: string): TradeRoute[] {
  const count = randInt(rng, 2, 4);
  const routes: TradeRoute[] = [];
  for (let i = 0; i < count; i += 1) {
    const [origin, destination] = pickUnique(2, PORT_NAMES);
    routes.push({
      id: `${commodityId}-route-${i}`,
      origin,
      destination,
      originCoordinates: PORT_COORDINATES[origin],
      destinationCoordinates: PORT_COORDINATES[destination],
      volumeIndex: Math.round(randRange(rng, 30, 100)),
      status: pick(rng, ["normal", "normal", "normal", "congested", "disrupted"] as const),
    });
  }
  return routes;
}

function inventoryFor(): InventoryPoint[] {
  const regions = pickUnique(4, ["US Gulf Coast", "ARA (Rotterdam)", "Singapore", "China Ports", "Fujairah", "Japan/Korea"]);
  return regions.map((region) => ({
    region,
    level: Math.round(randRange(rng, 20, 95)),
    changePercent: Number(randRange(rng, -8, 8).toFixed(1)),
  }));
}

function relatedEntities(): {
  companies: RelatedEntityRef[];
  countries: RelatedEntityRef[];
  ports: RelatedEntityRef[];
} {
  return {
    companies: pickUnique(4, COMPANIES).map((name, i) => ({ id: `company-${i}-${name}`, name, type: "company" })),
    countries: pickUnique(3, COUNTRIES).map((name, i) => ({ id: `country-${i}-${name}`, name, type: "country" })),
    ports: pickUnique(3, PORT_NAMES).map((name, i) => ({ id: `port-${i}-${name}`, name, type: "port" })),
  };
}

function aiCommentaryFor(commodityName: string, changePercent: number): AiCommentaryBlock {
  const direction = changePercent >= 0 ? "strengthened" : "eased";
  const driver = pick(rng, SUPPLY_TEMPLATES)(commodityName, pick(rng, COUNTRIES), pick(rng, COMPANIES), pick(rng, PORT_NAMES));
  const secondDriver = pick(rng, DEMAND_TEMPLATES)(commodityName, pick(rng, COUNTRIES), pick(rng, COMPANIES));
  return {
    summary: `${commodityName} prices ${direction} today. ${driver}, while ${secondDriver.charAt(0).toLowerCase()}${secondDriver.slice(1)}. Assessed spreads versus regional benchmarks remain within recent ranges, with desks citing balanced positioning into the next assessment window.`,
    confidence: Number(randRange(rng, 78, 97).toFixed(1)),
    evidenceCount: randInt(rng, 4, 18),
    relatedReportIds: [],
    generatedAt: new Date(Date.now() - randInt(rng, 5, 90) * 60_000).toISOString(),
  };
}

export const MARKET_QUOTES: MarketQuote[] = COMMODITIES.map((commodity) => {
  const base = randRange(rng, 60, 420);
  const changePercent = Number(randRange(rng, -4.5, 4.5).toFixed(2));
  const changeAbsolute = Number(((changePercent / 100) * base).toFixed(2));
  const weeklyTrend: number[] = [];
  let value = base;
  for (let i = 0; i < 7; i += 1) {
    value += randRange(rng, -base * 0.015, base * 0.015);
    weeklyTrend.push(Number(value.toFixed(2)));
  }
  const risks: RiskLevel[] = ["low", "moderate", "elevated", "high"];
  return {
    commodity,
    price: Number(base.toFixed(2)),
    changeAbsolute,
    changePercent,
    weeklyTrend,
    marketSummary: `${commodity.name} assessed ${changePercent >= 0 ? "higher" : "lower"} on ${pick(rng, COUNTRIES)} ${changePercent >= 0 ? "demand strength" : "demand softness"} and ${pick(rng, ["refinery activity", "freight availability", "inventory drawdowns", "export flows"])}.`,
    supplyRisk: pick(rng, risks),
    demandRisk: pick(rng, risks),
    aiCommentary: aiCommentaryFor(commodity.name, changePercent),
    relatedReportIds: [],
    updatedAt: new Date(Date.now() - randInt(rng, 2, 120) * 60_000).toISOString(),
  } satisfies MarketQuote;
});

export const COMMODITY_DETAILS: Record<string, CommodityDetail> = Object.fromEntries(
  COMMODITIES.map((commodity) => {
    const quote = MARKET_QUOTES.find((q) => q.commodity.id === commodity.id)!;
    const related = relatedEntities();
    const detail: CommodityDetail = {
      commodityId: commodity.id,
      volatility30d: Number(randRange(rng, 8, 42).toFixed(1)),
      dailyChangePercent: quote.changePercent,
      weeklyChangePercent: Number(randRange(rng, -8, 8).toFixed(2)),
      monthlyChangePercent: Number(randRange(rng, -15, 15).toFixed(2)),
      priceHistory: priceHistory(quote.price, 60),
      supplyDrivers: [
        buildDriver(SUPPLY_TEMPLATES, commodity.name, "bullish"),
        buildDriver(SUPPLY_TEMPLATES, commodity.name, "bearish"),
      ],
      demandDrivers: [
        buildDriver(DEMAND_TEMPLATES, commodity.name, "bullish"),
        buildDriver(DEMAND_TEMPLATES, commodity.name, "bearish"),
      ],
      tradeRoutes: tradeRoutesFor(commodity.id),
      inventory: inventoryFor(),
      risks: [buildRisk(commodity.id, commodity.name), buildRisk(commodity.id, commodity.name), buildRisk(commodity.id, commodity.name)],
      relatedCompanies: related.companies,
      relatedCountries: related.countries,
      relatedPorts: related.ports,
      weatherImpact: `${pick(rng, ["Monsoon", "Cyclone season", "Winter storm activity", "Heatwave conditions"])} in ${pick(rng, COUNTRIES)} is a minor factor for near-term ${commodity.shortName} logistics.`,
      shippingStatus: `${pick(rng, ["Freight rates steady", "Freight rates firming", "Vessel availability tightening", "Charter rates easing"])} on the key ${commodity.shortName} trade lanes this week.`,
      aiCommentary: quote.aiCommentary,
    };
    return [commodity.id, detail];
  })
);

const NEWS_TEMPLATES: Array<(commodityName: string) => string> = [
  (c) => `Argus ${c} assessment updated`,
  (c) => `Platts revises ${c} benchmark methodology note`,
  (c) => `${pick(rng, COUNTRIES)} refinery maintenance announced, ${c} markets watching`,
  (c) => `${pick(rng, COUNTRIES)} ${c} exports delayed amid port congestion`,
  (c) => `${c} rises after ${pick(rng, ["OPEC+ comments", "inventory data", "demand forecast revision"])}`,
  (c) => `Baltic freight index moves, ${c} logistics costs in focus`,
  (c) => `${pick(rng, COMPANIES)} announces new ${c} supply agreement`,
  (c) => `Reuters: ${c} demand outlook revised for next quarter`,
];

export const MARKET_NEWS_FEED: MarketNewsItem[] = Array.from({ length: 24 }).map((_, index) => {
  const commodity = pick(rng, COMMODITIES);
  const template = pick(rng, NEWS_TEMPLATES);
  const hour = 8 + Math.floor(index / 2);
  const minute = index % 2 === 0 ? randInt(rng, 0, 29) : randInt(rng, 30, 59);
  return {
    id: `news-${index}`,
    time: `${String(Math.min(hour, 23)).padStart(2, "0")}:${String(minute).padStart(2, "0")}`,
    headline: template(commodity.shortName),
    source: pick(rng, ["Argus", "Platts", "Reuters", "ICE", "Baltic Exchange"]),
    commodityIds: [commodity.id],
  } satisfies MarketNewsItem;
}).sort((a, b) => a.time.localeCompare(b.time));
