"use client";

import { useMemo, useState } from "react";
import { Search, ZoomIn, ZoomOut } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import type { Report } from "@/lib/types/reports";
import { cn } from "@/lib/utils";

interface DocumentViewerProps {
  report: Report;
  highlightedEntityName: string | null;
}

function buildPages(report: Report): string[] {
  const base = [
    report.summary,
    `This assessment draws on ${report.entities.length} identified entities across ${report.tables.length} extracted tables, covering ${report.country} market conditions for ${report.commodityIds.join(", ")}.`,
    ...report.entities.map((entity) => entity.sampleSnippet),
    `Validation completed with ${report.validationResults.filter((v) => v.passed).length} of ${report.validationResults.length} automated checks passing. Findings have been cross-referenced against the knowledge graph for consistency.`,
  ];
  const pageCount = Math.min(Math.max(report.tables.length + 2, 4), 6);
  const pages: string[] = [];
  for (let i = 0; i < pageCount; i += 1) {
    pages.push(base.filter((_, index) => index % pageCount === i).join(" ") || base[i % base.length]);
  }
  return pages;
}

function highlightText(text: string, needle: string | null): React.ReactNode {
  if (!needle || needle.trim().length < 2) return text;
  const parts = text.split(new RegExp(`(${needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"));
  return parts.map((part, index) =>
    part.toLowerCase() === needle.toLowerCase() ? (
      <mark key={index} className="rounded bg-primary/30 text-foreground">
        {part}
      </mark>
    ) : (
      part
    )
  );
}

export function DocumentViewer({ report, highlightedEntityName }: DocumentViewerProps) {
  const [zoom, setZoom] = useState(1);
  const [query, setQuery] = useState("");
  const pages = useMemo(() => buildPages(report), [report]);
  const activeHighlight = query || highlightedEntityName;

  return (
    <div className="glass-panel flex h-full flex-col rounded-xl border">
      <div className="flex items-center gap-2 border-b border-border/70 p-2.5">
        <div className="relative max-w-56 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search document…"
            className="h-8 pl-8 text-xs"
          />
        </div>
        <div className="ml-auto flex items-center gap-1">
          <Button variant="ghost" size="icon-sm" onClick={() => setZoom((z) => Math.max(0.75, z - 0.1))}>
            <ZoomOut className="size-3.5" />
          </Button>
          <span className="w-10 text-center text-xs text-muted-foreground tabular-nums">
            {Math.round(zoom * 100)}%
          </span>
          <Button variant="ghost" size="icon-sm" onClick={() => setZoom((z) => Math.min(1.5, z + 0.1))}>
            <ZoomIn className="size-3.5" />
          </Button>
        </div>
      </div>

      <div className="scrollbar-thin flex-1 space-y-4 overflow-y-auto bg-black/20 p-6">
        {pages.map((pageText, index) => (
          <div
            key={index}
            style={{ transform: `scale(${zoom})`, transformOrigin: "top center" }}
            className={cn(
              "mx-auto max-w-xl rounded-sm border border-border/60 bg-card p-8 shadow-lg transition-transform"
            )}
          >
            <p className="mb-4 text-[11px] text-muted-foreground">
              {report.source} · Page {index + 1} of {pages.length}
            </p>
            <p className="text-sm leading-relaxed text-foreground/85">
              {highlightText(pageText, activeHighlight)}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
