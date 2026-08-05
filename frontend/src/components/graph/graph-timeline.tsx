"use client";

import { History } from "lucide-react";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

export type TimelineWindow = "week" | "month" | "quarter" | "year";

export const TIMELINE_WINDOWS: Array<{ value: TimelineWindow; label: string; days: number }> = [
  { value: "week", label: "Week", days: 7 },
  { value: "month", label: "Month", days: 30 },
  { value: "quarter", label: "Quarter", days: 91 },
  { value: "year", label: "Year", days: 365 },
];

interface GraphTimelineProps {
  value: TimelineWindow;
  onChange: (value: TimelineWindow) => void;
  visibleCount: number;
  totalCount: number;
}

export function GraphTimeline({ value, onChange, visibleCount, totalCount }: GraphTimelineProps) {
  return (
    <div className="glass-panel flex items-center gap-3 rounded-xl border px-3 py-2">
      <History className="size-3.5 shrink-0 text-muted-foreground" />
      <p className="shrink-0 text-xs text-muted-foreground">
        Graph as of <span className="font-medium text-foreground">{visibleCount}</span> of {totalCount} entities
      </p>
      <ToggleGroup
        value={[value]}
        onValueChange={(next) => {
          const added = next.find((entry) => entry !== value);
          if (added) onChange(added as TimelineWindow);
        }}
        className="ml-auto"
      >
        {TIMELINE_WINDOWS.map((window) => (
          <ToggleGroupItem key={window.value} value={window.value} className="h-7 px-2.5 text-xs">
            {window.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  );
}
