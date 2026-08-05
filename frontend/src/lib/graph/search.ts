import type { GraphNodeData } from "@/lib/types/graph";

function searchableText(node: GraphNodeData): string {
  return [node.name, node.type, ...node.aliases, node.summary, ...Object.values(node.facts)]
    .join(" ")
    .toLowerCase();
}

/**
 * Keyword/substring matching, not true natural-language understanding — a
 * node matches if ANY whitespace-separated token in the query appears in
 * its name/aliases/type/summary/facts. This deliberately over-matches (a
 * multi-word query like "Naphtha India" highlights everything related to
 * either term, not just nodes mentioning both) to mirror the "everything
 * relevant glows" behavior described in the brief.
 */
export function matchGraphNodes(query: string, nodes: GraphNodeData[]): Set<string> {
  const tokens = query
    .toLowerCase()
    .split(/\s+/)
    .map((t) => t.trim())
    .filter(Boolean);
  if (tokens.length === 0) return new Set(nodes.map((n) => n.id));

  const matched = new Set<string>();
  nodes.forEach((node) => {
    const text = searchableText(node);
    if (tokens.some((token) => text.includes(token))) matched.add(node.id);
  });
  return matched;
}
