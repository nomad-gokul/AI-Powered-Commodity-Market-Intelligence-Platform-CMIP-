"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Bell, Search, ChevronDown, LogOut, Settings, UserRound } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { COMMODITIES } from "@/lib/types/market";
import { RECENT_ACTIVITY } from "@/lib/mock-data/dashboard";
import { cn } from "@/lib/utils";

const DATE_RANGES = ["Today", "7D", "30D", "90D", "YTD"] as const;

export function TopNav() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [dateRange, setDateRange] = useState<(typeof DATE_RANGES)[number]>("30D");

  function submitSearch() {
    if (!query.trim()) return;
    router.push(`/search?q=${encodeURIComponent(query.trim())}`);
  }

  return (
    <header className="glass-panel sticky top-0 z-30 flex h-16 shrink-0 items-center gap-3 border-b px-5">
      <div className="relative w-full max-w-md">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && submitSearch()}
          placeholder='Search reports, entities, "Naphtha market outlook India"…'
          className="h-9 border-border/80 bg-background/60 pl-9 text-sm"
        />
        <kbd className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
          ⌘K
        </kbd>
      </div>

      <Select defaultValue="all">
        <SelectTrigger size="sm" className="w-44 shrink-0">
          <SelectValue placeholder="All Commodities" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Commodities</SelectItem>
          {COMMODITIES.map((commodity) => (
            <SelectItem key={commodity.id} value={commodity.id}>
              {commodity.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={dateRange} onValueChange={(value) => setDateRange(value as typeof dateRange)}>
        <SelectTrigger size="sm" className="w-24 shrink-0">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {DATE_RANGES.map((range) => (
            <SelectItem key={range} value={range}>
              {range}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <div className="ml-auto flex shrink-0 items-center gap-2">
        <AiStatusPill />

        <Popover>
          <PopoverTrigger
            render={
              <Button variant="ghost" size="icon" className="relative">
                <Bell className="size-4" />
                <span className="absolute top-1 right-1 flex size-2">
                  <span className="absolute inline-flex size-full animate-ping rounded-full bg-danger opacity-75" />
                  <span className="relative inline-flex size-2 rounded-full bg-danger" />
                </span>
              </Button>
            }
          />
          <PopoverContent align="end" className="w-80 p-0">
            <div className="border-b border-border px-3 py-2.5 text-sm font-medium">
              Notifications
            </div>
            <div className="scrollbar-thin max-h-72 overflow-y-auto">
              {RECENT_ACTIVITY.slice(0, 5).map((event) => (
                <div key={event.id} className="border-b border-border/60 px-3 py-2.5 text-sm last:border-0">
                  <p className="font-medium text-foreground">{event.title}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">{event.detail}</p>
                </div>
              ))}
            </div>
          </PopoverContent>
        </Popover>

        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <button className="flex items-center gap-2 rounded-lg px-1.5 py-1 transition-colors hover:bg-accent">
                <Avatar className="size-7">
                  <AvatarFallback className="bg-primary/15 text-xs text-primary">DM</AvatarFallback>
                </Avatar>
                <ChevronDown className="size-3.5 text-muted-foreground" />
              </button>
            }
          />
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel className="font-normal">
              <p className="text-sm font-medium">Dhruv Mohanty</p>
              <p className="text-xs text-muted-foreground">Commodity Analyst · Enterprise</p>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem>
              <UserRound /> Profile
            </DropdownMenuItem>
            <DropdownMenuItem>
              <Settings /> Settings
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive">
              <LogOut /> Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}

function AiStatusPill() {
  return (
    <Badge
      variant="secondary"
      className={cn(
        "hidden h-8 items-center gap-1.5 rounded-full border border-border/80 bg-background/60 px-3 text-xs font-normal text-muted-foreground sm:flex"
      )}
    >
      <span className="relative flex size-1.5">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-75" />
        <span className="relative inline-flex size-1.5 rounded-full bg-success" />
      </span>
      AI Operational
    </Badge>
  );
}
