"use client";

import { useQuery } from "@tanstack/react-query";
import { simulateLatency } from "./client";
import {
  KPI_SUMMARY,
  RECENT_ACTIVITY,
  TOP_COMMODITIES,
  WORLD_MAP_REGIONS,
} from "@/lib/mock-data/dashboard";

export function useKpiSummary() {
  return useQuery({
    queryKey: ["dashboard", "kpi-summary"],
    queryFn: async () => {
      await simulateLatency(300);
      return KPI_SUMMARY;
    },
  });
}

export function useRecentActivity() {
  return useQuery({
    queryKey: ["dashboard", "recent-activity"],
    queryFn: async () => {
      await simulateLatency(400);
      return RECENT_ACTIVITY;
    },
  });
}

export function useWorldMapRegions() {
  return useQuery({
    queryKey: ["dashboard", "world-map"],
    queryFn: async () => {
      await simulateLatency(450);
      return WORLD_MAP_REGIONS;
    },
  });
}

export function useTopCommodities() {
  return useQuery({
    queryKey: ["dashboard", "top-commodities"],
    queryFn: async () => {
      await simulateLatency(350);
      return TOP_COMMODITIES;
    },
  });
}
