import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import type { GraphEdgeData, GraphNodeData, GraphNodeType } from "@/lib/types/graph";
import { GRAPH_NODE_TYPES } from "@/lib/types/graph";
import { PORT_COORDINATES } from "@/lib/geo/ports";
import { NODE_DIMENSIONS } from "@/lib/graph/node-visuals";

export type GraphMode = "business" | "logistics" | "trade-flow" | "commodity" | "geographic";

export const GRAPH_MODES: Array<{ value: GraphMode; label: string }> = [
  { value: "business", label: "Business View" },
  { value: "logistics", label: "Logistics View" },
  { value: "trade-flow", label: "Trade Flow View" },
  { value: "commodity", label: "Commodity View" },
  { value: "geographic", label: "Geographic View" },
];

export interface LayoutPosition {
  x: number;
  y: number;
}

interface SimNode extends SimulationNodeDatum {
  id: string;
  type: GraphNodeType;
}

type SimLink = SimulationLinkDatum<SimNode>;

const COUNTRY_COORDINATES: Record<string, [number, number]> = {
  India: [78.96, 20.59],
  Indonesia: [113.92, -0.79],
  China: [104.2, 35.86],
  Singapore: [103.82, 1.35],
  "Saudi Arabia": [45.08, 23.89],
  "United Arab Emirates": [53.85, 23.42],
  Netherlands: [5.29, 52.13],
  "United Kingdom": [-3.44, 55.38],
  Switzerland: [8.23, 46.82],
  "South Africa": [22.94, -30.56],
  Qatar: [51.18, 25.35],
};

const GEO_SCALE = 5.2;

function geoToCanvas([lon, lat]: [number, number]): LayoutPosition {
  return { x: lon * GEO_SCALE, y: -lat * GEO_SCALE * 1.4 };
}

/** Evenly spaced cluster centers, one per node type, around a ring — used
 * by Business View so clustering generalizes instead of hand-placed. */
function typeClusterCenters(radius: number): Record<GraphNodeType, LayoutPosition> {
  const centers = {} as Record<GraphNodeType, LayoutPosition>;
  GRAPH_NODE_TYPES.forEach((type, index) => {
    const angle = (index / GRAPH_NODE_TYPES.length) * Math.PI * 2 - Math.PI / 2;
    centers[type] = { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
  });
  return centers;
}

const FLOW_STAGE_ORDER: Record<GraphMode, Partial<Record<GraphNodeType, number>>> = {
  logistics: { country: 0, port: 1, ship: 2, company: 3, contract: 4, commodity: 4, report: 4 },
  "trade-flow": { commodity: 0, company: 1, contract: 2, ship: 3, port: 4, country: 5, report: 5 },
  business: {},
  commodity: {},
  geographic: {},
};

function anchorFor(
  mode: GraphMode,
  node: GraphNodeData,
  nodesById: Map<string, GraphNodeData>,
  edges: GraphEdgeData[],
  clusterCenters: Record<GraphNodeType, LayoutPosition>
): { anchor: LayoutPosition | null; strength: number; fixed?: boolean } {
  if (mode === "business") {
    return { anchor: clusterCenters[node.type], strength: 0.22 };
  }

  if (mode === "logistics" || mode === "trade-flow") {
    const stage = FLOW_STAGE_ORDER[mode][node.type] ?? 3;
    const stageCount = mode === "logistics" ? 5 : 6;
    const x = (stage - (stageCount - 1) / 2) * 260;
    return { anchor: { x, y: 0 }, strength: 0.35 };
  }

  if (mode === "commodity") {
    // Handled entirely by the two-pass logic in computeGraphLayout (a
    // commodity node's own position must be resolved before every other
    // node can be pulled toward the commodity it's linked to) — this
    // branch only covers the "no linked commodity" fallback.
    return { anchor: { x: 0, y: 0 }, strength: 0.05 };
  }

  if (mode === "geographic") {
    if (node.type === "country" && COUNTRY_COORDINATES[node.name]) {
      return { anchor: geoToCanvas(COUNTRY_COORDINATES[node.name]), strength: 0.9, fixed: true };
    }
    if (node.type === "port" && PORT_COORDINATES[node.name]) {
      return { anchor: geoToCanvas(PORT_COORDINATES[node.name]), strength: 0.8 };
    }
    if (node.type === "company" && COUNTRY_COORDINATES[node.facts.Headquarters]) {
      return { anchor: geoToCanvas(COUNTRY_COORDINATES[node.facts.Headquarters]), strength: 0.5 };
    }
    return { anchor: { x: 0, y: 0 }, strength: 0.04 };
  }

  return { anchor: null, strength: 0 };
}

export function computeGraphLayout(
  nodes: GraphNodeData[],
  edges: GraphEdgeData[],
  mode: GraphMode
): Map<string, LayoutPosition> {
  const nodesById = new Map(nodes.map((n) => [n.id, n]));
  const clusterCenters = typeClusterCenters(mode === "business" ? 340 : 300);

  const simNodes: SimNode[] = nodes.map((node, index) => {
    const angle = (index / nodes.length) * Math.PI * 2;
    return { id: node.id, type: node.type, x: Math.cos(angle) * 200, y: Math.sin(angle) * 200 };
  });
  const simNodesById = new Map(simNodes.map((n) => [n.id, n]));

  const simLinks: SimLink[] = edges
    .filter((e) => simNodesById.has(e.source) && simNodesById.has(e.target))
    .map((e) => ({ source: e.source, target: e.target }));

  // Two-pass for "commodity" mode: first resolve commodity anchor positions
  // via the cluster ring, then pull every other node toward the commodity
  // it's connected to (rather than a generic type center).
  const commodityAnchorById = new Map<string, LayoutPosition>();
  if (mode === "commodity") {
    nodes
      .filter((n) => n.type === "commodity")
      .forEach((n, i, arr) => {
        const angle = (i / arr.length) * Math.PI * 2;
        commodityAnchorById.set(n.id, { x: Math.cos(angle) * 260, y: Math.sin(angle) * 260 });
      });
  }

  const simulation = forceSimulation<SimNode>(simNodes)
    .force(
      "link",
      forceLink<SimNode, SimLink>(simLinks)
        .id((d) => d.id)
        .distance(mode === "geographic" ? 60 : 110)
        .strength(0.35)
    )
    .force("charge", forceManyBody<SimNode>().strength(mode === "geographic" ? -80 : -260))
    .force(
      "collide",
      forceCollide<SimNode>().radius((d) => {
        const dims = NODE_DIMENSIONS[d.type];
        return Math.max(dims.width, dims.height) / 2 + 26;
      })
    )
    .force("center", forceCenter(0, 0))
    .stop();

  nodes.forEach((node) => {
    const simNode = simNodesById.get(node.id);
    if (!simNode) return;

    if (mode === "commodity" && node.type !== "commodity") {
      const linked = edges.find(
        (e) =>
          (e.source === node.id && commodityAnchorById.has(e.target)) ||
          (e.target === node.id && commodityAnchorById.has(e.source))
      );
      const target = linked
        ? commodityAnchorById.get(linked.source === node.id ? linked.target : linked.source)
        : null;
      if (target) {
        simulation.force(`x-${node.id}`, forceX<SimNode>(target.x).strength(0.25));
      }
      return;
    }
    if (mode === "commodity" && node.type === "commodity") {
      const anchor = commodityAnchorById.get(node.id);
      if (anchor) {
        simNode.fx = anchor.x;
        simNode.fy = anchor.y;
      }
      return;
    }

    const { anchor, fixed } = anchorFor(mode, node, nodesById, edges, clusterCenters);
    if (anchor && fixed) {
      simNode.fx = anchor.x;
      simNode.fy = anchor.y;
    }
  });

  // Soft per-node pull toward its mode anchor (skipped for fixed/commodity
  // nodes, already handled above).
  nodes.forEach((node) => {
    if (mode === "commodity") return;
    const simNode = simNodesById.get(node.id);
    if (!simNode || simNode.fx != null) return;
    const { anchor, strength } = anchorFor(mode, node, nodesById, edges, clusterCenters);
    if (anchor) {
      simulation.force(`ax-${node.id}`, forceX<SimNode>(anchor.x).strength(strength));
      simulation.force(`ay-${node.id}`, forceY<SimNode>(anchor.y).strength(strength));
    }
  });

  for (let i = 0; i < 260; i += 1) simulation.tick();

  const positions = new Map<string, LayoutPosition>();
  simNodes.forEach((n) => positions.set(n.id, { x: n.x ?? 0, y: n.y ?? 0 }));
  return positions;
}
