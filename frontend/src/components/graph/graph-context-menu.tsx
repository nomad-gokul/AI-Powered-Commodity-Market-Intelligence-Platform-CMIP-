"use client";

import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { Crosshair, Share2, FileStack, Copy, FileText } from "lucide-react";
import type { GraphNodeData } from "@/lib/types/graph";

export interface ContextMenuState {
  x: number;
  y: number;
  node: GraphNodeData;
}

interface GraphContextMenuProps {
  state: ContextMenuState;
  onClose: () => void;
  onCenter: (node: GraphNodeData) => void;
  onExpand: (node: GraphNodeData) => void;
  onViewEvidence: (node: GraphNodeData) => void;
}

export function GraphContextMenu({ state, onClose, onCenter, onExpand, onViewEvidence }: GraphContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) onClose();
    }
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("mousedown", handleClick);
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.removeEventListener("mousedown", handleClick);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [onClose]);

  const items = [
    { label: "Center on node", icon: Crosshair, onClick: () => onCenter(state.node) },
    { label: "Expand connections", icon: Share2, onClick: () => onExpand(state.node) },
    { label: "View evidence", icon: FileStack, onClick: () => onViewEvidence(state.node) },
    {
      label: "Copy canonical ID",
      icon: Copy,
      onClick: () => navigator.clipboard?.writeText(state.node.canonicalId),
    },
    ...(state.node.type === "report"
      ? [{ label: "Open full report", icon: FileText, onClick: () => window.open(`/reports/${state.node.canonicalId}`, "_self") }]
      : []),
  ];

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.12 }}
      style={{ left: state.x, top: state.y }}
      className="glass-panel fixed z-50 w-56 rounded-lg border p-1 shadow-xl"
    >
      <p className="truncate px-2 py-1.5 text-xs font-medium text-muted-foreground">{state.node.name}</p>
      <div className="h-px bg-border" />
      {items.map((item) => (
        <button
          key={item.label}
          onClick={() => {
            item.onClick();
            onClose();
          }}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-foreground/85 hover:bg-accent"
        >
          <item.icon className="size-3.5 text-muted-foreground" />
          {item.label}
        </button>
      ))}
    </motion.div>
  );
}
