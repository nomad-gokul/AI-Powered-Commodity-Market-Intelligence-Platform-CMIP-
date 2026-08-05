"use client";

import { useMemo } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { X, ArrowUpRight, FileText } from "lucide-react";
import type { EChartsOption } from "echarts";
import type { GraphDataset, GraphEdgeData, GraphNodeData } from "@/lib/types/graph";
import { NODE_VISUALS, EDGE_COLORS } from "@/lib/graph/node-visuals";
import { edgesForNode, connectedNode } from "@/lib/graph/queries";
import { RiskBadge } from "@/components/markets/risk-badge";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { EChart } from "@/components/charts/echart";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

interface IntelligenceInspectorProps {
  dataset: GraphDataset;
  selectedNode: GraphNodeData | null;
  selectedEdge: GraphEdgeData | null;
  onSelectNode: (node: GraphNodeData) => void;
  onClose: () => void;
}

export function IntelligenceInspector({ dataset, selectedNode, selectedEdge, onSelectNode, onClose }: IntelligenceInspectorProps) {
  const hasContent = selectedNode || selectedEdge;

  return (
    <div className="glass-panel h-full w-[320px] shrink-0 overflow-hidden rounded-xl border">
      <AnimatePresence mode="wait">
        {!hasContent && (
          <motion.div
            key="empty"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center"
          >
            <p className="text-xs font-medium tracking-wider text-muted-foreground uppercase">
              Intelligence Inspector
            </p>
            <p className="text-sm text-muted-foreground">
              Select a node or relationship to inspect its evidence, connections, and activity.
            </p>
          </motion.div>
        )}

        {selectedEdge && (
          <motion.div
            key={`edge-${selectedEdge.id}`}
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0 }}
            className="scrollbar-thin h-full overflow-y-auto p-4"
          >
            <RelationshipInspector dataset={dataset} edge={selectedEdge} onClose={onClose} onSelectNode={onSelectNode} />
          </motion.div>
        )}

        {selectedNode && !selectedEdge && (
          <motion.div
            key={`node-${selectedNode.id}`}
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0 }}
            className="scrollbar-thin h-full overflow-y-auto p-4"
          >
            <NodeInspector dataset={dataset} node={selectedNode} onClose={onClose} onSelectNode={onSelectNode} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function NodeInspector({
  dataset,
  node,
  onClose,
  onSelectNode,
}: {
  dataset: GraphDataset;
  node: GraphNodeData;
  onClose: () => void;
  onSelectNode: (node: GraphNodeData) => void;
}) {
  const visual = NODE_VISUALS[node.type];
  const Icon = visual.icon;
  const edges = useMemo(() => edgesForNode(dataset, node.id), [dataset, node.id]);
  const connections = useMemo(
    () => edges.map((edge) => ({ edge, other: connectedNode(dataset, edge, node.id) })).filter((c) => c.other),
    [edges, dataset, node.id]
  );
  const evidenceCount = edges.reduce((sum, e) => sum + e.evidence.length, 0);
  const reportConnections = connections.filter((c) => c.other!.type === "report");

  const typeBreakdown = useMemo(() => {
    const counts = new Map<string, number>();
    connections.forEach(({ other }) => counts.set(other!.type, (counts.get(other!.type) ?? 0) + 1));
    return Array.from(counts.entries());
  }, [connections]);

  const donutOption: EChartsOption = {
    tooltip: { trigger: "item" },
    series: [
      {
        type: "pie",
        radius: ["55%", "80%"],
        label: { show: false },
        data: typeBreakdown.map(([type, count]) => ({
          name: NODE_VISUALS[type as GraphNodeData["type"]].label,
          value: count,
          itemStyle: { color: NODE_VISUALS[type as GraphNodeData["type"]].color },
        })),
      },
    ],
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <span
            className="flex size-8 items-center justify-center rounded-lg"
            style={{ background: `${visual.color}22`, color: visual.color }}
          >
            <Icon className="size-4" />
          </span>
          <div>
            <p className="text-[10px] font-medium text-muted-foreground uppercase">{visual.label}</p>
            <p className="text-sm font-semibold text-foreground">{node.name}</p>
          </div>
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
          <X className="size-4" />
        </button>
      </div>

      {node.type === "report" && (
        <Link
          href={`/reports/${node.canonicalId}`}
          className="flex items-center justify-between rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-xs font-medium text-primary hover:bg-primary/10"
        >
          Open full report <ArrowUpRight className="size-3.5" />
        </Link>
      )}

      <p className="text-sm leading-relaxed text-foreground/85">{node.summary}</p>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <InfoStat label="Confidence" value={`${Math.round(node.confidence * 100)}%`} />
        <InfoStat label="Status" value={node.status} capitalize />
        <InfoStat label="Risk" value={<RiskBadge level={node.risk} />} />
        <InfoStat label="Evidence" value={String(evidenceCount)} />
      </div>

      {node.aliases.length > 0 && (
        <div>
          <p className="mb-1.5 text-[10px] font-medium text-muted-foreground uppercase">Aliases</p>
          <div className="flex flex-wrap gap-1">
            {node.aliases.map((alias) => (
              <Badge key={alias} variant="secondary" className="text-[10px] font-normal">
                {alias}
              </Badge>
            ))}
          </div>
        </div>
      )}

      <div>
        <p className="mb-1.5 text-[10px] font-medium text-muted-foreground uppercase">Facts</p>
        <div className="space-y-1 rounded-lg border border-border/60 p-2.5">
          {Object.entries(node.facts).map(([key, value]) => (
            <div key={key} className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">{key}</span>
              <span className="font-medium text-foreground">{value}</span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <p className="text-[10px] font-medium text-muted-foreground uppercase">
            Connected Entities ({connections.length})
          </p>
        </div>
        <div className="space-y-1">
          {connections.slice(0, 8).map(({ edge, other }) => (
            <button
              key={edge.id}
              onClick={() => onSelectNode(other!)}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-accent/60"
            >
              <span className="size-1.5 shrink-0 rounded-full" style={{ background: EDGE_COLORS[edge.type] }} />
              <span className="text-muted-foreground">{edge.type.replace(/_/g, " ").toLowerCase()}</span>
              <span className="min-w-0 flex-1 truncate font-medium text-foreground">{other!.name}</span>
            </button>
          ))}
        </div>
      </div>

      {typeBreakdown.length > 1 && (
        <div>
          <p className="mb-1.5 text-[10px] font-medium text-muted-foreground uppercase">Relationship Mix</p>
          <EChart option={donutOption} height={140} />
        </div>
      )}

      {reportConnections.length > 0 && (
        <div>
          <p className="mb-1.5 text-[10px] font-medium text-muted-foreground uppercase">Reports</p>
          <div className="space-y-1">
            {reportConnections.slice(0, 4).map(({ other }) => (
              <Link
                key={other!.id}
                href={`/reports/${other!.canonicalId}`}
                className="flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-accent/60 hover:text-foreground"
              >
                <FileText className="size-3.5 shrink-0" />
                <span className="truncate">{other!.name}</span>
              </Link>
            ))}
          </div>
        </div>
      )}

      <div>
        <p className="mb-1.5 text-[10px] font-medium text-muted-foreground uppercase">Timeline</p>
        <div className="space-y-1 text-xs text-muted-foreground">
          <div className="flex justify-between">
            <span>First seen</span>
            <span className="tabular-nums">{formatRelativeTime(node.firstSeen)}</span>
          </div>
          <div className="flex justify-between">
            <span>Latest activity</span>
            <span className="tabular-nums">{formatRelativeTime(node.lastActivity)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function RelationshipInspector({
  dataset,
  edge,
  onClose,
  onSelectNode,
}: {
  dataset: GraphDataset;
  edge: GraphEdgeData;
  onClose: () => void;
  onSelectNode: (node: GraphNodeData) => void;
}) {
  const source = dataset.nodes.find((n) => n.id === edge.source);
  const target = dataset.nodes.find((n) => n.id === edge.target);
  const color = EDGE_COLORS[edge.type];

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <p className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
          Relationship Explorer
        </p>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
          <X className="size-4" />
        </button>
      </div>

      <div className="rounded-lg border p-3" style={{ borderColor: `${color}55`, background: `${color}0d` }}>
        <p className="text-xs font-semibold" style={{ color }}>
          {edge.type.replace(/_/g, " ")}
        </p>
        <div className="mt-2 flex items-center gap-2 text-sm">
          {source && (
            <button onClick={() => onSelectNode(source)} className="truncate font-medium text-foreground hover:underline">
              {source.name}
            </button>
          )}
          <ArrowUpRight className="size-3.5 shrink-0 text-muted-foreground" />
          {target && (
            <button onClick={() => onSelectNode(target)} className="truncate font-medium text-foreground hover:underline">
              {target.name}
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <InfoStat label="Confidence" value={`${Math.round(edge.confidence * 100)}%`} />
        <InfoStat label="Evidence" value={String(edge.evidence.length)} />
      </div>
      <Progress value={edge.confidence * 100} className="h-1.5" />

      <div>
        <p className="mb-1.5 text-[10px] font-medium text-muted-foreground uppercase">
          Evidence ({edge.evidence.length})
        </p>
        <div className="space-y-2">
          {edge.evidence.map((item) => (
            <div key={item.id} className="rounded-lg border border-border/60 p-2.5 text-xs">
              <div className="flex items-center justify-between">
                <span className="truncate font-medium text-foreground">{item.documentTitle}</span>
                <Badge variant="secondary" className="shrink-0 text-[10px] font-normal">
                  {Math.round(item.confidence * 100)}%
                </Badge>
              </div>
              <p className="mt-1 text-muted-foreground">
                Page {item.page} · {formatRelativeTime(item.timestamp)}
              </p>
            </div>
          ))}
        </div>
      </div>

      <div>
        <p className="mb-1.5 text-[10px] font-medium text-muted-foreground uppercase">Timeline</p>
        <p className="text-xs text-muted-foreground">Established {formatRelativeTime(edge.createdAt)}</p>
      </div>
    </div>
  );
}

function InfoStat({ label, value, capitalize }: { label: string; value: React.ReactNode; capitalize?: boolean }) {
  return (
    <div className="rounded-lg border border-border/60 p-2">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className={cn("mt-0.5 text-sm font-medium text-foreground", capitalize && "capitalize")}>{value}</p>
    </div>
  );
}
