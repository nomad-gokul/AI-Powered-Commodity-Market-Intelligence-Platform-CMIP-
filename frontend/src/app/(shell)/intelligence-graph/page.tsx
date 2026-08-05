"use client";

import { useEffect, useMemo, useState } from "react";
import { BarChart3 } from "lucide-react";
import { PageTransition } from "@/components/motion/page-transition";
import { FadeIn } from "@/components/motion/fade-in";
import { Button } from "@/components/ui/button";
import { GraphSearchBar } from "@/components/graph/graph-search-bar";
import { GraphTimeline, TIMELINE_WINDOWS, type TimelineWindow } from "@/components/graph/graph-timeline";
import { GraphModeToggle } from "@/components/graph/graph-mode-toggle";
import { EntityExplorerSidebar } from "@/components/graph/entity-explorer-sidebar";
import { GraphCanvas } from "@/components/graph/graph-canvas";
import { IntelligenceInspector } from "@/components/graph/intelligence-inspector";
import { EvidenceExplorer } from "@/components/graph/evidence-explorer";
import { GraphAnalyticsPanel } from "@/components/graph/graph-analytics-panel";
import { GraphCommandPalette } from "@/components/graph/graph-command-palette";
import { GraphContextMenu, type ContextMenuState } from "@/components/graph/graph-context-menu";
import { GRAPH_DATASET } from "@/lib/mock-data/graph";
import { matchGraphNodes } from "@/lib/graph/search";
import type { GraphDataset, GraphEdgeData, GraphNodeData } from "@/lib/types/graph";
import type { GraphMode } from "@/lib/graph/layout";

function filterByTimeline(dataset: GraphDataset, window: TimelineWindow): GraphDataset {
  const days = TIMELINE_WINDOWS.find((w) => w.value === window)!.days;
  const cutoff = Date.now() - days * 86_400_000;
  const nodes = dataset.nodes.filter((n) => new Date(n.firstSeen).getTime() >= cutoff);
  const nodeIds = new Set(nodes.map((n) => n.id));
  const edges = dataset.edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target));
  return { nodes, edges };
}

export default function IntelligenceGraphPage() {
  const [timelineWindow, setTimelineWindow] = useState<TimelineWindow>("year");
  const [mode, setMode] = useState<GraphMode>("business");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedNode, setSelectedNode] = useState<GraphNodeData | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdgeData | null>(null);
  const [provenanceMode, setProvenanceMode] = useState(false);
  const [evidenceExpanded, setEvidenceExpanded] = useState(false);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [analyticsOpen, setAnalyticsOpen] = useState(false);
  const [centerToken, setCenterToken] = useState<{ nodeId: string; nonce: number } | null>(null);

  const filteredDataset = useMemo(() => filterByTimeline(GRAPH_DATASET, timelineWindow), [timelineWindow]);

  const matchedNodeIds = useMemo(
    () => (searchQuery.trim() ? matchGraphNodes(searchQuery, filteredDataset.nodes) : null),
    [searchQuery, filteredDataset.nodes]
  );

  function selectNode(node: GraphNodeData) {
    setSelectedNode(node);
    setSelectedEdge(null);
    setCenterToken({ nodeId: node.id, nonce: Date.now() });
  }

  function selectEdge(edge: GraphEdgeData) {
    setSelectedEdge(edge);
    setSelectedNode(null);
    setEvidenceExpanded(true);
  }

  function closeInspector() {
    setSelectedNode(null);
    setSelectedEdge(null);
  }

  useEffect(() => {
    if (selectedNode || provenanceMode) setEvidenceExpanded(true);
  }, [selectedNode, provenanceMode]);

  // If the timeline scrubber narrows the visible graph past the current
  // selection (e.g. jumping to "Week"), drop the stale selection instead
  // of leaving the Inspector pointed at a node that's no longer on screen.
  useEffect(() => {
    if (selectedNode && !filteredDataset.nodes.some((n) => n.id === selectedNode.id)) {
      setSelectedNode(null);
    }
    if (selectedEdge && !filteredDataset.edges.some((e) => e.id === selectedEdge.id)) {
      setSelectedEdge(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filteredDataset]);

  useEffect(() => {
    function handleKeydown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandPaletteOpen((v) => !v);
        return;
      }
      if (event.key === "Escape") {
        setCommandPaletteOpen(false);
        setContextMenu(null);
        closeInspector();
      }
    }
    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  }, []);

  return (
    <PageTransition>
      <div className="flex h-[calc(100vh-8rem)] flex-col gap-3">
        <FadeIn className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-medium tracking-wider text-primary uppercase">Flagship Workspace</p>
              <h1 className="font-heading text-2xl font-semibold tracking-tight sm:text-3xl">Intelligence Graph</h1>
            </div>
            <Button variant="outline" size="sm" onClick={() => setAnalyticsOpen(true)}>
              <BarChart3 /> Analytics
            </Button>
          </div>
          <GraphSearchBar
            value={searchQuery}
            onChange={setSearchQuery}
            matchCount={matchedNodeIds?.size ?? 0}
            onOpenCommandPalette={() => setCommandPaletteOpen(true)}
          />
          <div className="flex flex-wrap items-center gap-3">
            <GraphTimeline
              value={timelineWindow}
              onChange={setTimelineWindow}
              visibleCount={filteredDataset.nodes.length}
              totalCount={GRAPH_DATASET.nodes.length}
            />
            <GraphModeToggle value={mode} onChange={setMode} />
          </div>
        </FadeIn>

        <FadeIn delay={0.05} className="flex min-h-0 flex-1 gap-3">
          <EntityExplorerSidebar
            nodes={filteredDataset.nodes}
            selectedNodeId={selectedNode?.id ?? null}
            matchedNodeIds={matchedNodeIds}
            onSelectNode={selectNode}
          />

          <div className="min-w-0 flex-1">
            <GraphCanvas
              dataset={filteredDataset}
              mode={mode}
              selectedNodeId={selectedNode?.id ?? null}
              selectedEdgeId={selectedEdge?.id ?? null}
              matchedNodeIds={matchedNodeIds}
              provenanceMode={provenanceMode}
              onToggleProvenance={() => setProvenanceMode((v) => !v)}
              onSelectNode={(node) => (node ? selectNode(node) : closeInspector())}
              onSelectEdge={(edge) => (edge ? selectEdge(edge) : undefined)}
              onContextMenuNode={(event, node) => setContextMenu({ x: event.clientX, y: event.clientY, node })}
              centerToken={centerToken}
            />
          </div>

          <IntelligenceInspector
            dataset={filteredDataset}
            selectedNode={selectedNode}
            selectedEdge={selectedEdge}
            onSelectNode={selectNode}
            onClose={closeInspector}
          />
        </FadeIn>

        <FadeIn delay={0.1}>
          <EvidenceExplorer
            dataset={filteredDataset}
            selectedNode={selectedNode}
            selectedEdge={selectedEdge}
            provenanceMode={provenanceMode}
            expanded={evidenceExpanded}
            onToggleExpanded={() => setEvidenceExpanded((v) => !v)}
            onSelectEdge={selectEdge}
          />
        </FadeIn>
      </div>

      <GraphAnalyticsPanel dataset={filteredDataset} open={analyticsOpen} onOpenChange={setAnalyticsOpen} />
      <GraphCommandPalette
        open={commandPaletteOpen}
        onOpenChange={setCommandPaletteOpen}
        dataset={filteredDataset}
        onSelectNode={selectNode}
        onSetMode={setMode}
      />
      {contextMenu && (
        <GraphContextMenu
          state={contextMenu}
          onClose={() => setContextMenu(null)}
          onCenter={selectNode}
          onExpand={selectNode}
          onViewEvidence={(node) => {
            selectNode(node);
            setEvidenceExpanded(true);
          }}
        />
      )}
    </PageTransition>
  );
}
