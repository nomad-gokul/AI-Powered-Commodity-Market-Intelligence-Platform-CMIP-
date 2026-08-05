import {
  Building2,
  Anchor,
  Globe2,
  Diamond,
  FileSignature,
  Ship,
  FileText,
  type LucideIcon,
} from "lucide-react";
import type { GraphEdgeType, GraphNodeType } from "@/lib/types/graph";

export type NodeShape = "rect" | "hexagon" | "circle" | "diamond" | "card" | "capsule" | "document";

interface NodeVisual {
  label: string;
  shape: NodeShape;
  color: string;
  icon: LucideIcon;
  clipPath?: string;
}

export const NODE_VISUALS: Record<GraphNodeType, NodeVisual> = {
  company: { label: "Company", shape: "rect", color: "#3b82f6", icon: Building2 },
  port: {
    label: "Port",
    shape: "hexagon",
    color: "#10b981",
    icon: Anchor,
    clipPath: "polygon(25% 6%, 75% 6%, 96% 50%, 75% 94%, 25% 94%, 4% 50%)",
  },
  country: { label: "Country", shape: "circle", color: "#f59e0b", icon: Globe2 },
  commodity: {
    label: "Commodity",
    shape: "diamond",
    color: "#f97316",
    icon: Diamond,
    clipPath: "polygon(50% 2%, 98% 50%, 50% 98%, 2% 50%)",
  },
  contract: { label: "Contract", shape: "card", color: "#a855f7", icon: FileSignature },
  ship: { label: "Ship", shape: "capsule", color: "#14b8a6", icon: Ship },
  report: { label: "Report", shape: "document", color: "#9a9aa2", icon: FileText },
};

/** Matches the actual rendered footprint of each shape in entity-node.tsx.
 * Passed through to React Flow's Node.width/height so it can measure
 * layout bounds *before* the DOM paints — without this, MiniMap and
 * fitView briefly compute against zero-size nodes and render garbage. */
export const NODE_DIMENSIONS: Record<GraphNodeType, { width: number; height: number }> = {
  company: { width: 172, height: 56 },
  port: { width: 96, height: 96 },
  country: { width: 172, height: 172 },
  commodity: { width: 96, height: 96 },
  contract: { width: 172, height: 56 },
  ship: { width: 168, height: 56 },
  report: { width: 172, height: 56 },
};

export const EDGE_COLORS: Record<GraphEdgeType, string> = {
  OWNS: "#3b82f6",
  OPERATES: "#10b981",
  LOCATED_IN: "#f59e0b",
  SHIPPED_FROM: "#14b8a6",
  SHIPPED_TO: "#06b6d4",
  REFERENCES: "#9a9aa2",
  SUPPLIES: "#f97316",
  CONNECTED_TO: "#a855f7",
};
