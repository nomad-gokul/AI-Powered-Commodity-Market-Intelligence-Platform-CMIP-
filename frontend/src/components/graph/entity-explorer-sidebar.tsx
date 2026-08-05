"use client";

import { useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";
import { GRAPH_NODE_TYPES, type GraphNodeData } from "@/lib/types/graph";
import { NODE_VISUALS } from "@/lib/graph/node-visuals";
import { cn } from "@/lib/utils";

interface EntityExplorerSidebarProps {
  nodes: GraphNodeData[];
  selectedNodeId: string | null;
  matchedNodeIds: Set<string> | null;
  onSelectNode: (node: GraphNodeData) => void;
}

const STATUS_DOT: Record<GraphNodeData["status"], string> = {
  active: "bg-success",
  watch: "bg-warning",
  dormant: "bg-muted-foreground",
};

export function EntityExplorerSidebar({ nodes, selectedNodeId, matchedNodeIds, onSelectNode }: EntityExplorerSidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [width, setWidth] = useState(268);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(GRAPH_NODE_TYPES));
  const resizing = useRef(false);

  const grouped = useMemo(() => {
    return GRAPH_NODE_TYPES.map((type) => ({
      type,
      items: nodes.filter((n) => n.type === type),
    })).filter((group) => group.items.length > 0);
  }, [nodes]);

  function toggleGroup(type: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  function startResize(event: React.PointerEvent) {
    resizing.current = true;
    const startX = event.clientX;
    const startWidth = width;
    function onMove(moveEvent: PointerEvent) {
      if (!resizing.current) return;
      setWidth(Math.min(420, Math.max(220, startWidth + (moveEvent.clientX - startX))));
    }
    function onUp() {
      resizing.current = false;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  if (collapsed) {
    return (
      <div className="glass-panel flex h-full w-12 flex-col items-center gap-2 rounded-xl border py-3">
        <button
          onClick={() => setCollapsed(false)}
          className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <ChevronsRight className="size-4" />
        </button>
        {GRAPH_NODE_TYPES.map((type) => {
          const visual = NODE_VISUALS[type];
          const Icon = visual.icon;
          return (
            <span key={type} className="rounded-md p-1.5" style={{ color: visual.color }}>
              <Icon className="size-4" />
            </span>
          );
        })}
      </div>
    );
  }

  return (
    <div className="glass-panel relative flex h-full flex-col rounded-xl border" style={{ width }}>
      <div className="flex items-center justify-between border-b border-border/70 px-3 py-2.5">
        <p className="text-xs font-medium tracking-wider text-muted-foreground uppercase">Entity Explorer</p>
        <button onClick={() => setCollapsed(true)} className="text-muted-foreground hover:text-foreground">
          <ChevronsLeft className="size-4" />
        </button>
      </div>

      <div className="scrollbar-thin flex-1 space-y-1 overflow-y-auto p-2">
        {grouped.map((group) => {
          const visual = NODE_VISUALS[group.type];
          const Icon = visual.icon;
          const isOpen = expanded.has(group.type);
          const avgConfidence = Math.round(
            (group.items.reduce((sum, n) => sum + n.confidence, 0) / group.items.length) * 100
          );

          return (
            <div key={group.type}>
              <button
                onClick={() => toggleGroup(group.type)}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-accent/60"
              >
                <motion.span animate={{ rotate: isOpen ? 90 : 0 }} transition={{ duration: 0.15 }}>
                  <ChevronRight className="size-3.5 text-muted-foreground" />
                </motion.span>
                <Icon className="size-3.5" style={{ color: visual.color }} />
                <span className="flex-1 text-sm font-medium">{visual.label}s</span>
                <span className="text-[10px] text-muted-foreground tabular-nums">{avgConfidence}%</span>
                <span className="min-w-5 rounded-full bg-muted px-1.5 py-0.5 text-center text-[10px] tabular-nums text-muted-foreground">
                  {group.items.length}
                </span>
              </button>
              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.16 }}
                    className="overflow-hidden pl-8"
                  >
                    {group.items.map((node) => {
                      const dimmed = matchedNodeIds ? !matchedNodeIds.has(node.id) : false;
                      const active = node.id === selectedNodeId;
                      return (
                        <button
                          key={node.id}
                          onClick={() => onSelectNode(node)}
                          className={cn(
                            "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-all",
                            active ? "bg-primary/15 text-primary" : "text-foreground/75 hover:bg-accent/60",
                            dimmed && "opacity-30"
                          )}
                        >
                          <span className={cn("size-1.5 shrink-0 rounded-full", STATUS_DOT[node.status])} />
                          <span className="min-w-0 flex-1 truncate">{node.name}</span>
                        </button>
                      );
                    })}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>

      <div
        onPointerDown={startResize}
        className="absolute top-0 right-0 h-full w-1 cursor-col-resize hover:bg-primary/40"
      />
    </div>
  );
}
