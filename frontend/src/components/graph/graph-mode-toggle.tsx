"use client";

import { LayoutGrid } from "lucide-react";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { GRAPH_MODES, type GraphMode } from "@/lib/graph/layout";

export function GraphModeToggle({ value, onChange }: { value: GraphMode; onChange: (mode: GraphMode) => void }) {
  return (
    <div className="glass-panel flex items-center gap-2 rounded-xl border px-3 py-2">
      <LayoutGrid className="size-3.5 shrink-0 text-muted-foreground" />
      <ToggleGroup
        value={[value]}
        onValueChange={(next) => {
          // Base UI's ToggleGroup is multi-select by design (no single/
          // multiple `type` prop) — we only ever want one active mode, so
          // pick whichever entry is newly pressed and ignore toggle-off
          // events entirely (a mode toggle should never end up with zero
          // selection).
          const added = next.find((entry) => entry !== value);
          if (added) onChange(added as GraphMode);
        }}
      >
        {GRAPH_MODES.map((mode) => (
          <ToggleGroupItem key={mode.value} value={mode.value} className="h-7 px-2.5 text-xs">
            {mode.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  );
}
