export type RiskLevel = "low" | "moderate" | "elevated" | "high";

export type CommodityCategory =
  | "coal"
  | "crude_oil"
  | "lng"
  | "refined_products"
  | "metals"
  | "freight"
  | "agriculture";

export interface Commodity {
  id: string;
  name: string;
  shortName: string;
  category: CommodityCategory;
  unit: string;
}

export const COMMODITIES: Commodity[] = [
  { id: "thermal-coal", name: "Thermal Coal", shortName: "Coal", category: "coal", unit: "USD/t" },
  { id: "coking-coal", name: "Coking Coal", shortName: "Coking Coal", category: "coal", unit: "USD/t" },
  { id: "brent", name: "Brent Crude", shortName: "Brent", category: "crude_oil", unit: "USD/bbl" },
  { id: "wti", name: "WTI Crude", shortName: "WTI", category: "crude_oil", unit: "USD/bbl" },
  { id: "lng", name: "LNG (JKM)", shortName: "LNG", category: "lng", unit: "USD/MMBtu" },
  { id: "naphtha", name: "Naphtha", shortName: "Naphtha", category: "refined_products", unit: "USD/t" },
  { id: "gasoline", name: "Gasoline (RON95)", shortName: "Gasoline", category: "refined_products", unit: "USD/bbl" },
  { id: "diesel", name: "Diesel (ULSD)", shortName: "Diesel", category: "refined_products", unit: "USD/bbl" },
  { id: "jet-fuel", name: "Jet Fuel", shortName: "Jet Fuel", category: "refined_products", unit: "USD/bbl" },
  { id: "fuel-oil", name: "Fuel Oil (380cst)", shortName: "Fuel Oil", category: "refined_products", unit: "USD/t" },
  { id: "iron-ore", name: "Iron Ore (62% Fe)", shortName: "Iron Ore", category: "metals", unit: "USD/t" },
  { id: "steel", name: "Steel (HRC)", shortName: "Steel", category: "metals", unit: "USD/t" },
  { id: "aluminium", name: "Aluminium", shortName: "Aluminium", category: "metals", unit: "USD/t" },
  { id: "copper", name: "Copper", shortName: "Copper", category: "metals", unit: "USD/t" },
  { id: "freight", name: "Baltic Dry Freight", shortName: "Freight", category: "freight", unit: "Index" },
  { id: "agriculture", name: "Agriculture (Wheat)", shortName: "Agriculture", category: "agriculture", unit: "USD/bu" },
];

export interface MarketQuote {
  commodity: Commodity;
  price: number;
  changeAbsolute: number;
  changePercent: number;
  weeklyTrend: number[];
  marketSummary: string;
  supplyRisk: RiskLevel;
  demandRisk: RiskLevel;
  /** F2 integration touch: F1 scaffolded this as a plain string, but no F1
   * component ever consumed MarketQuote (the Dashboard reads the separate
   * CommoditySnapshot type) — the Markets workspace needs the full
   * confidence/evidence-count/generatedAt block, so this was widened
   * rather than left as a dead, unused string field. */
  aiCommentary: import("./market-detail").AiCommentaryBlock;
  relatedReportIds: string[];
  updatedAt: string;
}
