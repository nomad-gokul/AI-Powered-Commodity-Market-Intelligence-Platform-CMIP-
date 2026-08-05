import { useState } from "react";
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from "reactflow";
import type { GraphEdgeData } from "@/lib/types/graph";
import { EDGE_COLORS } from "@/lib/graph/node-visuals";
import { cn } from "@/lib/utils";

export interface EntityEdgeData {
  edge: GraphEdgeData;
  faded: boolean;
  highlighted: boolean;
  provenanceMode: boolean;
}

export function EntityEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
  markerEnd,
}: EdgeProps<EntityEdgeData>) {
  const [hovered, setHovered] = useState(false);
  if (!data) return null;
  const { edge, faded, highlighted, provenanceMode } = data;
  const color = EDGE_COLORS[edge.type];
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  const active = selected || highlighted || hovered;

  return (
    <>
      <BaseEdge
        path={path}
        markerEnd={markerEnd}
        style={{
          stroke: color,
          strokeWidth: active ? 2.2 : 1.3,
          opacity: faded ? 0.08 : active ? 1 : 0.45,
          transition: "opacity 0.25s ease, stroke-width 0.2s ease",
        }}
      />
      {!faded && (
        <path
          d={path}
          fill="none"
          stroke={color}
          strokeWidth={active ? 2.2 : 1.3}
          strokeDasharray="1 9"
          className="graph-edge-flow"
          opacity={0.9}
        />
      )}
      <EdgeLabelRenderer>
        <div
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          style={{
            position: "absolute",
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            pointerEvents: "all",
            background: "color-mix(in oklch, var(--panel-elevated), transparent 8%)",
            borderColor: `${color}66`,
            color,
          }}
          className={cn(
            "nodrag nopan flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[9px] font-medium whitespace-nowrap backdrop-blur-sm transition-opacity",
            faded ? "opacity-0" : active || provenanceMode ? "opacity-100" : "opacity-0 hover:opacity-100"
          )}
        >
          {edge.type.replace(/_/g, " ")}
          <span className="text-muted-foreground">{Math.round(edge.confidence * 100)}%</span>
        </div>
      </EdgeLabelRenderer>
    </>
  );
}
