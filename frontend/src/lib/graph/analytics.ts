import type { GraphDataset, GraphEdgeType, GraphNodeType } from "@/lib/types/graph";
import { GRAPH_EDGE_TYPES } from "@/lib/types/graph";

function degreeByType(dataset: GraphDataset, type: GraphNodeType, top = 6) {
  const degree = new Map<string, number>();
  dataset.edges.forEach((edge) => {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  });
  return dataset.nodes
    .filter((n) => n.type === type)
    .map((n) => ({ name: n.name, value: degree.get(n.id) ?? 0 }))
    .sort((a, b) => b.value - a.value)
    .slice(0, top);
}

export function topConnectedCompanies(dataset: GraphDataset) {
  return degreeByType(dataset, "company");
}

export function mostActivePorts(dataset: GraphDataset) {
  return degreeByType(dataset, "port");
}

export function topCommodities(dataset: GraphDataset) {
  return degreeByType(dataset, "commodity");
}

export function relationshipDistribution(dataset: GraphDataset) {
  const counts = new Map<GraphEdgeType, number>();
  GRAPH_EDGE_TYPES.forEach((type) => counts.set(type, 0));
  dataset.edges.forEach((edge) => counts.set(edge.type, (counts.get(edge.type) ?? 0) + 1));
  return Array.from(counts.entries()).map(([name, value]) => ({ name, value }));
}

export function entityGrowth(dataset: GraphDataset) {
  const sorted = [...dataset.nodes].sort(
    (a, b) => new Date(a.firstSeen).getTime() - new Date(b.firstSeen).getTime()
  );
  const bucketCount = 12;
  if (sorted.length === 0) return [];
  const start = new Date(sorted[0].firstSeen).getTime();
  const end = Date.now();
  const bucketMs = Math.max(1, (end - start) / bucketCount);
  const buckets = Array.from({ length: bucketCount + 1 }, (_, i) => ({
    label: new Date(start + i * bucketMs).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    cumulative: 0,
  }));
  sorted.forEach((node) => {
    const t = new Date(node.firstSeen).getTime();
    const bucketIndex = Math.min(bucketCount, Math.floor((t - start) / bucketMs));
    for (let i = bucketIndex; i <= bucketCount; i += 1) buckets[i].cumulative += 1;
  });
  return buckets;
}

export function confidenceDistribution(dataset: GraphDataset) {
  const buckets = [
    { label: "60-70%", min: 0.6, max: 0.7, count: 0 },
    { label: "70-80%", min: 0.7, max: 0.8, count: 0 },
    { label: "80-90%", min: 0.8, max: 0.9, count: 0 },
    { label: "90-100%", min: 0.9, max: 1.01, count: 0 },
  ];
  dataset.nodes.forEach((node) => {
    const bucket = buckets.find((b) => node.confidence >= b.min && node.confidence < b.max);
    if (bucket) bucket.count += 1;
  });
  return buckets.map((b) => ({ name: b.label, value: b.count }));
}
