"use client";

import "reactflow/dist/style.css";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { toPng } from "html-to-image";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
} from "reactflow";
import {
  Expand,
  Camera,
  Maximize2,
  Minimize2,
  Plus,
  Minus,
  Info,
  Radar,
} from "lucide-react";
import { EntityNode, type EntityNodeData } from "./entity-node";
import { EntityEdge, type EntityEdgeData } from "./entity-edge";
import { GraphLegend } from "./graph-legend";
import type { GraphDataset, GraphEdgeData, GraphNodeData } from "@/lib/types/graph";
import { NODE_DIMENSIONS, EDGE_COLORS } from "@/lib/graph/node-visuals";
import { computeGraphLayout, type GraphMode } from "@/lib/graph/layout";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const NODE_TYPES = { entity: EntityNode };
const EDGE_TYPES = { entity: EntityEdge };

interface GraphCanvasProps {
  dataset: GraphDataset;
  mode: GraphMode;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  matchedNodeIds: Set<string> | null;
  provenanceMode: boolean;
  onToggleProvenance: () => void;
  onSelectNode: (node: GraphNodeData | null) => void;
  onSelectEdge: (edge: GraphEdgeData | null) => void;
  onContextMenuNode: (event: React.MouseEvent, node: GraphNodeData) => void;
  centerToken: { nodeId: string; nonce: number } | null;
}

function GraphCanvasInner({
  dataset,
  mode,
  selectedNodeId,
  selectedEdgeId,
  matchedNodeIds,
  provenanceMode,
  onToggleProvenance,
  onSelectNode,
  onSelectEdge,
  onContextMenuNode,
  centerToken,
}: GraphCanvasProps) {
  const reactFlow = useReactFlow();
  const wrapperRef = useRef<HTMLDivElement>(null);
  const seenIds = useRef<Set<string>>(new Set());
  const [nodes, setNodes] = useState<Node<EntityNodeData>[]>([]);
  const [edges, setEdges] = useState<Edge<EntityEdgeData>[]>([]);
  const [showLegend, setShowLegend] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const nodesById = useMemo(() => new Map(dataset.nodes.map((n) => [n.id, n])), [dataset.nodes]);

  // Layout pass — only when mode or the node/edge set itself changes.
  const datasetKey = useMemo(
    () => `${mode}:${dataset.nodes.map((n) => n.id).join(",")}`,
    [mode, dataset.nodes]
  );

  useEffect(() => {
    const positions = computeGraphLayout(dataset.nodes, dataset.edges, mode);
    const newlySeen: string[] = [];
    const flowNodes: Node<EntityNodeData>[] = dataset.nodes.map((node) => {
      const isNew = !seenIds.current.has(node.id);
      if (isNew) newlySeen.push(node.id);
      const position = positions.get(node.id) ?? { x: 0, y: 0 };
      const dimensions = NODE_DIMENSIONS[node.type];
      return {
        id: node.id,
        type: "entity",
        position,
        width: dimensions.width,
        height: dimensions.height,
        data: {
          node,
          faded: false,
          glow: false,
          isNew,
          onContextMenu: onContextMenuNode,
        },
      };
    });
    newlySeen.forEach((id) => seenIds.current.add(id));

    const flowEdges: Edge<EntityEdgeData>[] = dataset.edges
      .filter((e) => nodesById.has(e.source) && nodesById.has(e.target))
      .map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: "entity",
        markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLORS[edge.type], width: 12, height: 12 },
        data: { edge, faded: false, highlighted: false, provenanceMode },
      }));

    setNodes(flowNodes);
    setEdges(flowEdges);
    const timer = setTimeout(() => reactFlow.fitView({ duration: 600, padding: 0.2 }), 80);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetKey]);

  // Data-only pass — search / selection / provenance, no position change.
  useEffect(() => {
    setNodes((current) =>
      current.map((n) => {
        const faded = matchedNodeIds ? !matchedNodeIds.has(n.id) : false;
        const glow = matchedNodeIds ? matchedNodeIds.has(n.id) : n.id === selectedNodeId;
        if (n.data.faded === faded && n.data.glow === glow) return n;
        return { ...n, data: { ...n.data, faded, glow } };
      })
    );
    setEdges((current) =>
      current.map((e) => {
        const faded = matchedNodeIds
          ? !(matchedNodeIds.has(e.source) && matchedNodeIds.has(e.target))
          : false;
        const highlighted =
          e.id === selectedEdgeId || e.source === selectedNodeId || e.target === selectedNodeId;
        if (e.data?.faded === faded && e.data?.highlighted === highlighted && e.data?.provenanceMode === provenanceMode) {
          return e;
        }
        return { ...e, data: { ...(e.data as EntityEdgeData), faded, highlighted, provenanceMode } };
      })
    );
  }, [matchedNodeIds, selectedNodeId, selectedEdgeId, provenanceMode]);

  useEffect(() => {
    if (!centerToken) return;
    const target = nodes.find((n) => n.id === centerToken.nodeId);
    if (!target) return;
    reactFlow.setCenter(target.position.x + 80, target.position.y + 20, { zoom: 1.1, duration: 550 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [centerToken]);

  const handleFullscreen = useCallback(() => {
    if (!wrapperRef.current) return;
    if (!document.fullscreenElement) {
      wrapperRef.current.requestFullscreen();
      setIsFullscreen(true);
    } else {
      document.exitFullscreen();
      setIsFullscreen(false);
    }
  }, []);

  const handleScreenshot = useCallback(() => {
    const viewport = wrapperRef.current?.querySelector(".react-flow__viewport") as HTMLElement | null;
    if (!viewport) return;
    toPng(viewport, { backgroundColor: "#09090b", pixelRatio: 2 }).then((dataUrl) => {
      const link = document.createElement("a");
      link.download = `argus-intelligence-graph-${Date.now()}.png`;
      link.href = dataUrl;
      link.click();
    });
  }, []);

  return (
    <div
      ref={wrapperRef}
      className="argus-graph relative h-full w-full overflow-hidden rounded-xl border border-border bg-[#0b0b0d]"
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        nodesDraggable={false}
        nodesConnectable={false}
        onNodeClick={(_, node) => onSelectNode((node.data as EntityNodeData).node)}
        onEdgeClick={(_, edge) => onSelectEdge((edge.data as EntityEdgeData).edge)}
        onPaneClick={() => {
          onSelectNode(null);
          onSelectEdge(null);
        }}
        minZoom={0.15}
        maxZoom={2.2}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{ type: "entity" }}
      >
        {/* MiniMap deliberately omitted: react-flow's MiniMap rendered a
            corrupted checkerboard of misaligned rects in this reactflow@11
            + React 19 environment regardless of styling (reproduced with
            zero customization, so it isn't caused by our nodeColor/CSS
            overrides) — shipping a visibly broken minimap was worse than
            not having one. Fit view + zoom controls below cover the same
            navigation need. */}
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#232326" />
        <Controls showInteractive={false} position="bottom-left" />
      </ReactFlow>

      {/* Toolbar */}
      <div className="glass-panel absolute top-3 left-3 z-20 flex items-center gap-1 rounded-lg border p-1">
        <ToolbarButton label="Fit view" icon={Expand} onClick={() => reactFlow.fitView({ duration: 500, padding: 0.2 })} />
        <ToolbarButton label="Zoom in" icon={Plus} onClick={() => reactFlow.zoomIn({ duration: 200 })} />
        <ToolbarButton label="Zoom out" icon={Minus} onClick={() => reactFlow.zoomOut({ duration: 200 })} />
        <div className="mx-0.5 h-4 w-px bg-border" />
        <ToolbarButton label="Screenshot" icon={Camera} onClick={handleScreenshot} />
        <ToolbarButton
          label={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
          icon={isFullscreen ? Minimize2 : Maximize2}
          onClick={handleFullscreen}
        />
        <div className="mx-0.5 h-4 w-px bg-border" />
        <ToolbarButton
          label={provenanceMode ? "Hide evidence" : "Show evidence"}
          icon={Radar}
          active={provenanceMode}
          onClick={onToggleProvenance}
        />
        <ToolbarButton label="Legend" icon={Info} active={showLegend} onClick={() => setShowLegend((v) => !v)} />
      </div>

      <AnimatePresence>{showLegend && <GraphLegend onClose={() => setShowLegend(false)} />}</AnimatePresence>
    </div>
  );
}

function ToolbarButton({
  label,
  icon: Icon,
  onClick,
  active,
}: {
  label: string;
  icon: typeof Expand;
  onClick: () => void;
  active?: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onClick}
            className={cn(active && "bg-primary/15 text-primary")}
          >
            <Icon className="size-3.5" />
          </Button>
        }
      />
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  );
}

export function GraphCanvas(props: GraphCanvasProps) {
  return (
    <ReactFlowProvider>
      <GraphCanvasInner {...props} />
    </ReactFlowProvider>
  );
}
