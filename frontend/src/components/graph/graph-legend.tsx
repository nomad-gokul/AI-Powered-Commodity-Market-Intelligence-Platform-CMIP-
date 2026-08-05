import { motion } from "framer-motion";
import { GRAPH_NODE_TYPES, GRAPH_EDGE_TYPES } from "@/lib/types/graph";
import { NODE_VISUALS, EDGE_COLORS } from "@/lib/graph/node-visuals";

export function GraphLegend({ onClose }: { onClose: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 8, scale: 0.98 }}
      className="glass-panel absolute right-3 bottom-3 z-20 w-56 rounded-xl border p-3 text-xs"
    >
      <div className="mb-2 flex items-center justify-between">
        <p className="font-medium text-foreground">Legend</p>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
          ×
        </button>
      </div>
      <div className="space-y-1.5">
        {GRAPH_NODE_TYPES.map((type) => {
          const visual = NODE_VISUALS[type];
          const Icon = visual.icon;
          return (
            <div key={type} className="flex items-center gap-2">
              <span
                className="flex size-3.5 shrink-0 items-center justify-center"
                style={{ background: visual.color, clipPath: visual.clipPath, borderRadius: visual.clipPath ? 0 : 3 }}
              />
              <Icon className="size-3 text-muted-foreground" />
              <span className="text-muted-foreground">{visual.label}</span>
            </div>
          );
        })}
      </div>
      <div className="my-2 h-px bg-border" />
      <div className="grid grid-cols-2 gap-x-2 gap-y-1">
        {GRAPH_EDGE_TYPES.map((type) => (
          <div key={type} className="flex items-center gap-1.5">
            <span className="h-0.5 w-3 shrink-0 rounded-full" style={{ background: EDGE_COLORS[type] }} />
            <span className="truncate text-[10px] text-muted-foreground">{type.replace(/_/g, " ")}</span>
          </div>
        ))}
      </div>
    </motion.div>
  );
}
