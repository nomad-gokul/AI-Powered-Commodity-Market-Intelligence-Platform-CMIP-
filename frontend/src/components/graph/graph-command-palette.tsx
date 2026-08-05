"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search, LayoutDashboard, LineChart, FileText, Search as SearchIcon, Sparkles, Bot } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { GraphDataset, GraphNodeData } from "@/lib/types/graph";
import { NODE_VISUALS } from "@/lib/graph/node-visuals";
import { GRAPH_MODES, type GraphMode } from "@/lib/graph/layout";
import { cn } from "@/lib/utils";

interface GraphCommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  dataset: GraphDataset;
  onSelectNode: (node: GraphNodeData) => void;
  onSetMode: (mode: GraphMode) => void;
}

const NAV_SHORTCUTS = [
  { label: "Dashboard", href: "/", icon: LayoutDashboard },
  { label: "Markets", href: "/markets", icon: LineChart },
  { label: "Reports", href: "/reports", icon: FileText },
  { label: "Search", href: "/search", icon: SearchIcon },
  { label: "Executive Intelligence", href: "/executive-intelligence", icon: Sparkles },
  { label: "AI Analyst", href: "/ai-analyst", icon: Bot },
];

type PaletteAction =
  | { kind: "mode"; label: string; group: string; mode: GraphMode }
  | { kind: "nav"; label: string; group: string; href: string; icon: typeof LayoutDashboard }
  | { kind: "node"; label: string; group: string; node: GraphNodeData };

/**
 * Deliberately not built on cmdk — cmdk 1.1.1 throws a confirmed,
 * unresolved "Cannot read properties of undefined (reading 'subscribe')"
 * crash under React 19 in this exact CommandDialog-in-a-Dialog shape (see
 * cmdk#346 / shadcn-ui#1939, reproduced live here). A small hand-rolled
 * filterable list avoids the broken dependency entirely rather than
 * shipping a command palette that crashes the page on open.
 */
export function GraphCommandPalette({ open, onOpenChange, dataset, onSelectNode, onSetMode }: GraphCommandPaletteProps) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const actions = useMemo<PaletteAction[]>(() => {
    const modeActions: PaletteAction[] = GRAPH_MODES.map((m) => ({
      kind: "mode",
      label: m.label,
      group: "Graph Modes",
      mode: m.value,
    }));
    const navActions: PaletteAction[] = NAV_SHORTCUTS.map((n) => ({
      kind: "nav",
      label: n.label,
      group: "Navigate",
      href: n.href,
      icon: n.icon,
    }));
    const nodeActions: PaletteAction[] = dataset.nodes.map((node) => ({
      kind: "node",
      label: node.name,
      group: "Jump to Entity",
      node,
    }));
    return [...modeActions, ...navActions, ...nodeActions];
  }, [dataset.nodes]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return actions.slice(0, 60);
    return actions.filter((a) => a.label.toLowerCase().includes(q)).slice(0, 60);
  }, [actions, query]);

  const groups = useMemo(() => {
    const map = new Map<string, PaletteAction[]>();
    filtered.forEach((action) => {
      const list = map.get(action.group) ?? [];
      list.push(action);
      map.set(action.group, list);
    });
    return Array.from(map.entries());
  }, [filtered]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query, open]);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50);
    else setQuery("");
  }, [open]);

  function runAction(action: PaletteAction) {
    if (action.kind === "mode") onSetMode(action.mode);
    if (action.kind === "nav") router.push(action.href);
    if (action.kind === "node") onSelectNode(action.node);
    onOpenChange(false);
  }

  function handleKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((i) => Math.min(filtered.length - 1, i + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((i) => Math.max(0, i - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const action = filtered[activeIndex];
      if (action) runAction(action);
    }
  }

  let runningIndex = -1;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader className="sr-only">
        <DialogTitle>Command Palette</DialogTitle>
        <DialogDescription>Search or navigate</DialogDescription>
      </DialogHeader>
      <DialogContent className="top-1/3 max-w-lg translate-y-0 gap-0 overflow-hidden rounded-xl! p-0" showCloseButton={false}>
        <div className="flex items-center gap-2 border-b border-border/70 px-3">
          <Search className="size-4 shrink-0 text-muted-foreground" />
          <Input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Find a company, port, commodity, report…"
            className="h-11 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0"
          />
        </div>
        <div className="scrollbar-thin max-h-80 overflow-y-auto p-1.5">
          {filtered.length === 0 && (
            <p className="py-8 text-center text-sm text-muted-foreground">No results found.</p>
          )}
          {groups.map(([group, items]) => (
            <div key={group} className="mb-1">
              <p className="px-2 py-1 text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
                {group}
              </p>
              {items.map((action) => {
                runningIndex += 1;
                const index = runningIndex;
                const active = index === activeIndex;
                return (
                  <button
                    key={`${action.group}-${action.label}-${index}`}
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => runAction(action)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm",
                      active ? "bg-accent text-foreground" : "text-foreground/80"
                    )}
                  >
                    {action.kind === "nav" && <action.icon className="size-4 text-muted-foreground" />}
                    {action.kind === "node" &&
                      (() => {
                        const Icon = NODE_VISUALS[action.node.type].icon;
                        return <Icon className="size-4" style={{ color: NODE_VISUALS[action.node.type].color }} />;
                      })()}
                    <span className="min-w-0 flex-1 truncate">{action.label}</span>
                    {action.kind === "node" && (
                      <span className="text-xs text-muted-foreground">{NODE_VISUALS[action.node.type].label}</span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
