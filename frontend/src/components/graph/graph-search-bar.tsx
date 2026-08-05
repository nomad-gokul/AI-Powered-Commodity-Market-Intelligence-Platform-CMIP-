"use client";

import { Search, X, Command } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

interface GraphSearchBarProps {
  value: string;
  onChange: (value: string) => void;
  matchCount: number;
  onOpenCommandPalette: () => void;
}

export function GraphSearchBar({ value, onChange, matchCount, onOpenCommandPalette }: GraphSearchBarProps) {
  return (
    <div className="relative mx-auto w-full max-w-2xl">
      <Search className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder='Search entities — "Naphtha India", "Adani", "Coal Indonesia"…'
        className="h-11 rounded-xl border-border/80 bg-background/70 pl-11 text-sm shadow-lg shadow-black/20"
      />
      <div className="absolute top-1/2 right-2 flex -translate-y-1/2 items-center gap-1.5">
        {value && (
          <>
            <Badge variant="secondary" className="text-[10px] font-normal">
              {matchCount} match{matchCount === 1 ? "" : "es"}
            </Badge>
            <button
              onClick={() => onChange("")}
              className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <X className="size-3.5" />
            </button>
          </>
        )}
        <button
          onClick={onOpenCommandPalette}
          className="flex items-center gap-1 rounded-md border border-border bg-muted px-1.5 py-1 text-[10px] text-muted-foreground hover:bg-accent"
        >
          <Command className="size-3" />K
        </button>
      </div>
    </div>
  );
}
