import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { motion } from "framer-motion";
import type { GraphNodeData } from "@/lib/types/graph";
import { NODE_VISUALS } from "@/lib/graph/node-visuals";
import { cn } from "@/lib/utils";

export interface EntityNodeData {
  node: GraphNodeData;
  faded: boolean;
  glow: boolean;
  isNew: boolean;
  onContextMenu?: (event: React.MouseEvent, node: GraphNodeData) => void;
}

const SHAPE_CLASS: Record<string, string> = {
  rect: "rounded-lg",
  circle: "rounded-full aspect-square",
  card: "rounded-2xl",
  capsule: "rounded-full",
  document: "rounded-md",
};

function EntityNodeInner({ data, selected }: NodeProps<EntityNodeData>) {
  const { node, faded, glow, isNew } = data;
  const visual = NODE_VISUALS[node.type];
  const Icon = visual.icon;
  const isGeometric = visual.shape === "hexagon" || visual.shape === "diamond";

  return (
    <motion.div
      initial={isNew ? { opacity: 0, scale: 0.4 } : false}
      animate={{
        opacity: faded ? 0.18 : 1,
        scale: selected ? 1.08 : 1,
      }}
      whileHover={{ scale: selected ? 1.1 : 1.05 }}
      transition={{ type: "spring", stiffness: 300, damping: 24 }}
      onContextMenu={(event) => {
        event.preventDefault();
        data.onContextMenu?.(event, node);
      }}
      className="relative"
      style={{ filter: glow ? `drop-shadow(0 0 14px ${visual.color}aa)` : undefined }}
    >
      <Handle type="target" position={Position.Top} className="!size-1.5 !border-0 !bg-transparent" />
      <Handle type="source" position={Position.Bottom} className="!size-1.5 !border-0 !bg-transparent" />

      <div
        className={cn(
          "flex items-center gap-2 border px-3 py-2 backdrop-blur-sm transition-colors",
          !isGeometric && (SHAPE_CLASS[visual.shape] ?? "rounded-lg"),
          isGeometric && "aspect-square flex-col justify-center px-2 py-2 text-center",
          selected ? "border-2" : "border"
        )}
        style={{
          clipPath: visual.clipPath,
          background: `color-mix(in oklch, ${visual.color}, transparent 82%)`,
          borderColor: selected ? visual.color : `${visual.color}55`,
          width: visual.shape === "capsule" ? 168 : isGeometric ? 96 : 172,
        }}
      >
        <Icon className="size-4 shrink-0" style={{ color: visual.color }} />
        <div className={cn("min-w-0 flex-1", isGeometric && "flex-none")}>
          <p
            className={cn(
              "truncate text-xs font-medium text-foreground",
              isGeometric && "line-clamp-2 text-[10px] leading-tight whitespace-normal"
            )}
          >
            {node.name}
          </p>
          {!isGeometric && (
            <p className="text-[10px] tabular-nums" style={{ color: visual.color }}>
              {Math.round(node.confidence * 100)}%
            </p>
          )}
        </div>
        {node.status === "watch" && (
          <span className="absolute -top-1 -right-1 size-2 rounded-full bg-warning ring-2 ring-background" />
        )}
      </div>

      {visual.shape === "document" && (
        <div
          className="absolute top-0 right-0 size-2.5 border-t border-r border-border bg-background"
          style={{ clipPath: "polygon(0 0, 100% 0, 100% 100%)" }}
        />
      )}
    </motion.div>
  );
}

export const EntityNode = memo(EntityNodeInner);
