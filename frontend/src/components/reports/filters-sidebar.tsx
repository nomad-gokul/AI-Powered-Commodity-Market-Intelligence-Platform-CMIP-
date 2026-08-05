"use client";

import { X } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { REPORT_SOURCES, type ReportFilters, type ReportSource } from "@/lib/types/reports";
import { COMMODITIES } from "@/lib/types/market";

interface FiltersSidebarProps {
  filters: ReportFilters;
  onChange: (filters: ReportFilters) => void;
  countries: string[];
  tags: string[];
}

export function FiltersSidebar({ filters, onChange, countries, tags }: FiltersSidebarProps) {
  function toggleSource(source: ReportSource) {
    const active = filters.sources.includes(source);
    onChange({
      ...filters,
      sources: active ? filters.sources.filter((s) => s !== source) : [...filters.sources, source],
    });
  }

  const hasActiveFilters =
    filters.sources.length > 0 || filters.commodityId || filters.country || filters.tag || filters.query;

  return (
    <div className="glass-panel scrollbar-thin h-full space-y-5 overflow-y-auto rounded-xl border p-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium tracking-wider text-muted-foreground uppercase">Filters</p>
        {hasActiveFilters && (
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-1.5 text-xs text-muted-foreground"
            onClick={() =>
              onChange({ sources: [], commodityId: null, country: null, tag: null, query: "" })
            }
          >
            <X className="size-3" /> Clear
          </Button>
        )}
      </div>

      <Input
        value={filters.query}
        onChange={(event) => onChange({ ...filters, query: event.target.value })}
        placeholder="Search reports…"
        className="h-9 text-sm"
      />

      <div>
        <p className="mb-2 text-xs font-medium text-foreground/80">Source</p>
        <div className="space-y-1.5">
          {REPORT_SOURCES.map((source) => (
            <label key={source} className="flex cursor-pointer items-center gap-2 text-sm text-foreground/80">
              <Checkbox
                checked={filters.sources.includes(source)}
                onCheckedChange={() => toggleSource(source)}
              />
              {source}
            </label>
          ))}
        </div>
      </div>

      <div>
        <p className="mb-2 text-xs font-medium text-foreground/80">Commodity</p>
        <Select
          value={filters.commodityId ?? "all"}
          onValueChange={(value) => onChange({ ...filters, commodityId: value === "all" ? null : value })}
        >
          <SelectTrigger size="sm" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All commodities</SelectItem>
            {COMMODITIES.map((commodity) => (
              <SelectItem key={commodity.id} value={commodity.id}>
                {commodity.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <p className="mb-2 text-xs font-medium text-foreground/80">Country</p>
        <Select
          value={filters.country ?? "all"}
          onValueChange={(value) => onChange({ ...filters, country: value === "all" ? null : value })}
        >
          <SelectTrigger size="sm" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All countries</SelectItem>
            {countries.map((country) => (
              <SelectItem key={country} value={country}>
                {country}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <p className="mb-2 text-xs font-medium text-foreground/80">Tags</p>
        <div className="flex flex-wrap gap-1.5">
          {tags.map((tag) => {
            const active = filters.tag === tag;
            return (
              <Badge
                key={tag}
                variant={active ? "default" : "secondary"}
                className="cursor-pointer text-[11px] font-normal capitalize"
                onClick={() => onChange({ ...filters, tag: active ? null : tag })}
              >
                {tag}
              </Badge>
            );
          })}
        </div>
      </div>
    </div>
  );
}
