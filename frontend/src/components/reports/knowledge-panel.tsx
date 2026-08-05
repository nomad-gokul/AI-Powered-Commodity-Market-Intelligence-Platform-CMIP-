"use client";

import "reactflow/dist/style.css";
import { useMemo } from "react";
import ReactFlow, { Background, Controls, type Edge, type Node } from "reactflow";
import { Building2, Globe2, Anchor, Package, FileSignature, Ship, CheckCircle2, XCircle } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import type { Report, ReportEntityType } from "@/lib/types/reports";
import { ActivityTimeline } from "@/components/dashboard/activity-timeline";
import { cn } from "@/lib/utils";

// Stable empty references — React Flow warns ("error#002") if nodeTypes/
// edgeTypes receive a freshly-created object on every render; we don't use
// custom node/edge renderers here, but must still pass the same object
// identity each time.
const EMPTY_NODE_TYPES = {};
const EMPTY_EDGE_TYPES = {};

const ENTITY_ICON: Record<ReportEntityType, typeof Building2> = {
  company: Building2,
  country: Globe2,
  port: Anchor,
  commodity: Package,
  contract: FileSignature,
  ship: Ship,
};

interface KnowledgePanelProps {
  report: Report;
  highlightedEntityId: string | null;
  onSelectEntity: (entityId: string | null) => void;
}

export function KnowledgePanel({ report, highlightedEntityId, onSelectEntity }: KnowledgePanelProps) {
  return (
    <div className="glass-panel h-full rounded-xl border p-4">
      <Tabs defaultValue="entities">
        <TabsList className="h-auto w-full flex-wrap justify-start gap-1">
          <TabsTrigger value="entities">Entities</TabsTrigger>
          <TabsTrigger value="tables">Tables</TabsTrigger>
          <TabsTrigger value="relationships">Relationships</TabsTrigger>
          <TabsTrigger value="validation">Validation</TabsTrigger>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="graph">Graph</TabsTrigger>
        </TabsList>

        <div className="scrollbar-thin mt-3 max-h-[calc(100vh-16rem)] overflow-y-auto">
          <TabsContent value="entities" className="space-y-1.5">
            {report.entities.map((entity) => {
              const Icon = ENTITY_ICON[entity.type];
              const active = entity.id === highlightedEntityId;
              return (
                <button
                  key={entity.id}
                  type="button"
                  onClick={() => onSelectEntity(active ? null : entity.id)}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                    active
                      ? "border-primary/40 bg-primary/10 text-foreground"
                      : "border-border/60 text-foreground/80 hover:bg-accent/50"
                  )}
                >
                  <Icon className="size-4 shrink-0 text-primary" />
                  <span className="min-w-0 flex-1 truncate">{entity.name}</span>
                  <Badge variant="secondary" className="shrink-0 text-[10px] font-normal capitalize">
                    {entity.type}
                  </Badge>
                  <span className="w-6 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
                    {entity.mentionCount}
                  </span>
                </button>
              );
            })}
          </TabsContent>

          <TabsContent value="tables" className="space-y-2">
            {report.tables.map((table) => (
              <div key={table.id} className="rounded-lg border border-border/60 p-3">
                <p className="text-sm font-medium">{table.title}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Page {table.page} · {table.rowCount} rows × {table.columnCount} columns
                </p>
              </div>
            ))}
          </TabsContent>

          <TabsContent value="relationships" className="space-y-1.5">
            {report.relationships.map((rel) => {
              const source = report.entities.find((e) => e.id === rel.sourceEntityId);
              const target = report.entities.find((e) => e.id === rel.targetEntityId);
              return (
                <div key={rel.id} className="rounded-lg border border-border/60 p-2.5 text-sm">
                  <span className="font-medium">{source?.name ?? "Unknown"}</span>{" "}
                  <span className="text-xs text-muted-foreground">{rel.relationshipType.replace(/_/g, " ")}</span>{" "}
                  <span className="font-medium">{target?.name ?? "Unknown"}</span>
                  <div className="mt-1 text-[11px] text-muted-foreground tabular-nums">
                    confidence {Math.round(rel.confidence * 100)}%
                  </div>
                </div>
              );
            })}
          </TabsContent>

          <TabsContent value="validation" className="space-y-1.5">
            {report.validationResults.map((result) => (
              <div key={result.id} className="flex items-start gap-2.5 rounded-lg border border-border/60 p-2.5">
                {result.passed ? (
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
                ) : (
                  <XCircle className="mt-0.5 size-4 shrink-0 text-danger" />
                )}
                <div className="min-w-0">
                  <p className="text-sm font-medium capitalize">{result.rule.replace(/_/g, " ")}</p>
                  <p className="text-xs text-muted-foreground">{result.message}</p>
                </div>
              </div>
            ))}
          </TabsContent>

          <TabsContent value="timeline">
            <ActivityTimeline
              events={report.timeline.map((event) => ({
                id: event.id,
                kind: "graph_updated",
                title: event.label,
                detail: event.actor,
                actor: event.actor,
                timestamp: event.timestamp,
              }))}
            />
          </TabsContent>

          <TabsContent value="graph" className="h-80">
            <ReportGraphPreview report={report} highlightedEntityId={highlightedEntityId} onSelectEntity={onSelectEntity} />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}

function ReportGraphPreview({
  report,
  highlightedEntityId,
  onSelectEntity,
}: {
  report: Report;
  highlightedEntityId: string | null;
  onSelectEntity: (id: string | null) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    const radius = 140;
    const center = { x: 180, y: 140 };
    const flowNodes: Node[] = report.entities.map((entity, index) => {
      const angle = (index / report.entities.length) * Math.PI * 2;
      const active = entity.id === highlightedEntityId;
      return {
        id: entity.id,
        position: {
          x: center.x + radius * Math.cos(angle),
          y: center.y + radius * Math.sin(angle),
        },
        data: { label: entity.name },
        style: {
          background: active ? "color-mix(in oklch, var(--primary), transparent 80%)" : "var(--panel-elevated)",
          border: `1px solid ${active ? "var(--primary)" : "var(--border)"}`,
          borderRadius: 8,
          fontSize: 11,
          color: "var(--foreground)",
          padding: "6px 10px",
          width: 130,
        },
      };
    });
    const flowEdges: Edge[] = report.relationships.map((rel) => ({
      id: rel.id,
      source: rel.sourceEntityId,
      target: rel.targetEntityId,
      animated: rel.sourceEntityId === highlightedEntityId || rel.targetEntityId === highlightedEntityId,
      style: { stroke: "var(--border)" },
    }));
    return { nodes: flowNodes, edges: flowEdges };
  }, [report, highlightedEntityId]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={EMPTY_NODE_TYPES}
      edgeTypes={EMPTY_EDGE_TYPES}
      fitView
      proOptions={{ hideAttribution: true }}
      onNodeClick={(_, node) => onSelectEntity(node.id === highlightedEntityId ? null : node.id)}
    >
      <Background color="#27272a" gap={16} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}
