export type GraphNodeType =
  | "company"
  | "port"
  | "country"
  | "commodity"
  | "contract"
  | "ship"
  | "report";

export const GRAPH_NODE_TYPES: GraphNodeType[] = [
  "company",
  "port",
  "country",
  "commodity",
  "contract",
  "ship",
  "report",
];

export type GraphEdgeType =
  | "OWNS"
  | "OPERATES"
  | "LOCATED_IN"
  | "SHIPPED_FROM"
  | "SHIPPED_TO"
  | "REFERENCES"
  | "SUPPLIES"
  | "CONNECTED_TO";

export const GRAPH_EDGE_TYPES: GraphEdgeType[] = [
  "OWNS",
  "OPERATES",
  "LOCATED_IN",
  "SHIPPED_FROM",
  "SHIPPED_TO",
  "REFERENCES",
  "SUPPLIES",
  "CONNECTED_TO",
];

export type EntityStatus = "active" | "watch" | "dormant";
export type RiskTier = "low" | "moderate" | "elevated" | "high";

export interface GraphNodeData {
  id: string;
  type: GraphNodeType;
  name: string;
  canonicalId: string;
  aliases: string[];
  confidence: number;
  status: EntityStatus;
  risk: RiskTier;
  /** ISO timestamp this node first appeared in the graph — drives the
   * timeline scrubber's "new node" animation. */
  firstSeen: string;
  lastActivity: string;
  summary: string;
  /** Free-form per-type facts shown in the Inspector (e.g. country for a
   * company, capacity for a port). */
  facts: Record<string, string>;
}

export interface GraphEdgeEvidence {
  id: string;
  documentId: string;
  documentTitle: string;
  page: number;
  chunkId: string;
  confidence: number;
  timestamp: string;
  pipeline: string;
  promptVersion: string;
  snippet: string;
}

export interface GraphEdgeData {
  id: string;
  source: string;
  target: string;
  type: GraphEdgeType;
  confidence: number;
  createdAt: string;
  evidence: GraphEdgeEvidence[];
}

export interface GraphDataset {
  nodes: GraphNodeData[];
  edges: GraphEdgeData[];
}
