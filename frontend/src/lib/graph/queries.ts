import type { GraphDataset, GraphEdgeData, GraphNodeData } from "@/lib/types/graph";

export function edgesForNode(dataset: GraphDataset, nodeId: string): GraphEdgeData[] {
  return dataset.edges.filter((e) => e.source === nodeId || e.target === nodeId);
}

export function connectedNode(dataset: GraphDataset, edge: GraphEdgeData, fromNodeId: string): GraphNodeData | undefined {
  const otherId = edge.source === fromNodeId ? edge.target : edge.source;
  return dataset.nodes.find((n) => n.id === otherId);
}

export function nodeById(dataset: GraphDataset, id: string): GraphNodeData | undefined {
  return dataset.nodes.find((n) => n.id === id);
}

export function allEvidenceForNode(dataset: GraphDataset, nodeId: string) {
  return edgesForNode(dataset, nodeId).flatMap((edge) =>
    edge.evidence.map((evidence) => ({ evidence, edge }))
  );
}
