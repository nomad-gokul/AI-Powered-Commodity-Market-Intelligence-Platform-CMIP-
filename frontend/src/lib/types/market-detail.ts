import type { RiskLevel } from "./market";

export type MarketCategoryGroup = "Energy" | "Metals" | "Agriculture" | "Shipping";
export type MarketCategorySubgroup =
  | "Coal"
  | "Crude Oil"
  | "Refined Products"
  | "Natural Gas"
  | "Metals"
  | "Agriculture"
  | "Shipping";

export interface CategoryTreeNode {
  group: MarketCategoryGroup;
  subgroups: Array<{
    label: MarketCategorySubgroup;
    commodityIds: string[];
  }>;
}

export interface TrendPoint {
  timestamp: string;
  price: number;
}

export interface DriverItem {
  label: string;
  detail: string;
  impact: "bullish" | "bearish" | "neutral";
}

export interface TradeRoute {
  id: string;
  origin: string;
  destination: string;
  originCoordinates: [number, number];
  destinationCoordinates: [number, number];
  volumeIndex: number;
  status: "normal" | "congested" | "disrupted";
}

export interface InventoryPoint {
  region: string;
  level: number;
  changePercent: number;
}

export interface RelatedEntityRef {
  id: string;
  name: string;
  type: "company" | "country" | "port";
}

export interface MarketRisk {
  id: string;
  label: string;
  severity: RiskLevel;
  category: "supply" | "demand" | "weather" | "geopolitical" | "logistics";
  detail: string;
}

export interface AiCommentaryBlock {
  summary: string;
  confidence: number;
  evidenceCount: number;
  relatedReportIds: string[];
  generatedAt: string;
}

export interface CommodityDetail {
  commodityId: string;
  volatility30d: number;
  dailyChangePercent: number;
  weeklyChangePercent: number;
  monthlyChangePercent: number;
  priceHistory: TrendPoint[];
  supplyDrivers: DriverItem[];
  demandDrivers: DriverItem[];
  tradeRoutes: TradeRoute[];
  inventory: InventoryPoint[];
  risks: MarketRisk[];
  relatedCompanies: RelatedEntityRef[];
  relatedCountries: RelatedEntityRef[];
  relatedPorts: RelatedEntityRef[];
  weatherImpact: string;
  shippingStatus: string;
  aiCommentary: AiCommentaryBlock;
}

export interface MarketNewsItem {
  id: string;
  time: string;
  headline: string;
  source: string;
  commodityIds: string[];
}

export const CATEGORY_TREE: CategoryTreeNode[] = [
  {
    group: "Energy",
    subgroups: [
      { label: "Coal", commodityIds: ["thermal-coal", "coking-coal"] },
      { label: "Crude Oil", commodityIds: ["brent", "wti"] },
      {
        label: "Refined Products",
        commodityIds: ["naphtha", "gasoline", "diesel", "jet-fuel", "fuel-oil"],
      },
      { label: "Natural Gas", commodityIds: ["lng"] },
    ],
  },
  {
    group: "Metals",
    subgroups: [
      { label: "Metals", commodityIds: ["iron-ore", "steel", "aluminium", "copper"] },
    ],
  },
  {
    group: "Agriculture",
    subgroups: [{ label: "Agriculture", commodityIds: ["agriculture"] }],
  },
  {
    group: "Shipping",
    subgroups: [{ label: "Shipping", commodityIds: ["freight"] }],
  },
];
