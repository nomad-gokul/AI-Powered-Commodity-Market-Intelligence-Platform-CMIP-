"use client";

import { useMemo } from "react";
import { motion } from "framer-motion";
import { ChevronUp, ChevronDown, FileStack } from "lucide-react";
import type { GraphDataset, GraphEdgeData, GraphNodeData } from "@/lib/types/graph";
import { edgesForNode } from "@/lib/graph/queries";
import { EDGE_COLORS } from "@/lib/graph/node-visuals";
import { Badge } from "@/components/ui/badge";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

interface EvidenceExplorerProps {
  dataset: GraphDataset;
  selectedNode: GraphNodeData | null;
  selectedEdge: GraphEdgeData | null;
  provenanceMode: boolean;
  expanded: boolean;
  onToggleExpanded: () => void;
  onSelectEdge: (edge: GraphEdgeData) => void;
}

export function EvidenceExplorer({
  dataset,
  selectedNode,
  selectedEdge,
  provenanceMode,
  expanded,
  onToggleExpanded,
  onSelectEdge,
}: EvidenceExplorerProps) {
  const scopedEdges = useMemo(() => {
    if (selectedEdge) return [selectedEdge];
    if (selectedNode) return edgesForNode(dataset, selectedNode.id);
    return dataset.edges;
  }, [dataset, selectedNode, selectedEdge]);

  const cards = useMemo(
    () =>
      scopedEdges.flatMap((edge) =>
        edge.evidence.map((evidence) => ({ edge, evidence }))
      ).slice(0, 60),
    [scopedEdges]
  );

  const scopeLabel = selectedEdge
    ? `${selectedEdge.type.replace(/_/g, " ")} relationship`
    : selectedNode
      ? selectedNode.name
      : "entire graph";

  return (
    <motion.div
      animate={{ height: expanded ? 240 : 44 }}
      transition={{ type: "spring", stiffness: 260, damping: 30 }}
      className="glass-panel overflow-hidden rounded-xl border"
    >
      <button
        onClick={onToggleExpanded}
        className="flex h-11 w-full items-center gap-2 px-4 text-left hover:bg-accent/40"
      >
        <FileStack className="size-4 text-primary" />
        <p className="text-xs font-medium tracking-wider text-muted-foreground uppercase">Evidence Explorer</p>
        <span className="text-xs text-muted-foreground">— {scopeLabel}</span>
        <Badge variant="secondary" className="text-[10px] font-normal">
          {cards.length}
        </Badge>
        {provenanceMode && (
          <Badge className="bg-primary/15 text-[10px] font-normal text-primary">Provenance mode</Badge>
        )}
        <span className="ml-auto text-muted-foreground">
          {expanded ? <ChevronDown className="size-4" /> : <ChevronUp className="size-4" />}
        </span>
      </button>

      {expanded && (
        <div className="scrollbar-thin flex h-[196px] gap-2 overflow-x-auto p-3 pt-0">
          {cards.length === 0 && (
            <p className="flex w-full items-center justify-center text-xs text-muted-foreground">
              No evidence in scope.
            </p>
          )}
          {cards.map(({ edge, evidence }) => (
            <button
              key={evidence.id}
              onClick={() => onSelectEdge(edge)}
              className={cn(
                "flex w-64 shrink-0 flex-col gap-1.5 rounded-lg border p-3 text-left transition-colors hover:border-border",
                selectedEdge?.id === edge.id ? "border-primary/50 bg-primary/5" : "border-border/60"
              )}
            >
              <div className="flex items-center gap-1.5">
                <span className="size-1.5 rounded-full" style={{ background: EDGE_COLORS[edge.type] }} />
                <span className="text-[10px] font-medium text-muted-foreground">
                  {edge.type.replace(/_/g, " ")}
                </span>
                <Badge variant="secondary" className="ml-auto text-[10px] font-normal">
                  {Math.round(evidence.confidence * 100)}%
                </Badge>
              </div>
              <p className="truncate text-xs font-medium text-foreground">{evidence.documentTitle}</p>
              <p className="text-[11px] text-muted-foreground">
                Page {evidence.page} · Chunk {evidence.chunkId.slice(-6)}
              </p>
              <p className="line-clamp-2 text-[11px] text-muted-foreground/80">{evidence.snippet}</p>
              {provenanceMode && (
                <div className="mt-1 space-y-0.5 border-t border-border/60 pt-1.5 text-[10px] text-muted-foreground">
                  <p className="truncate">Pipeline: {evidence.pipeline}</p>
                  <p className="truncate">Prompt: {evidence.promptVersion}</p>
                </div>
              )}
              <p className="mt-auto text-[10px] text-muted-foreground tabular-nums">
                {formatRelativeTime(evidence.timestamp)}
              </p>
            </button>
          ))}
        </div>
      )}
    </motion.div>
  );
}
