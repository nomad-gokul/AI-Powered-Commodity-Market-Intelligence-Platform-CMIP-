"use client";

import { useQuery } from "@tanstack/react-query";
import { simulateLatency } from "./client";
import { REPORTS } from "@/lib/mock-data/reports";
import type { ReportFilters } from "@/lib/types/reports";

export function useReports(filters: ReportFilters) {
  return useQuery({
    queryKey: ["reports", "list", filters],
    queryFn: async () => {
      await simulateLatency(350);
      return REPORTS.filter((report) => {
        if (filters.sources.length > 0 && !filters.sources.includes(report.source)) return false;
        if (filters.commodityId && !report.commodityIds.includes(filters.commodityId)) return false;
        if (filters.country && report.country !== filters.country) return false;
        if (filters.tag && !report.tags.includes(filters.tag)) return false;
        if (filters.query) {
          const haystack = `${report.title} ${report.summary}`.toLowerCase();
          if (!haystack.includes(filters.query.toLowerCase())) return false;
        }
        return true;
      });
    },
  });
}

export function useReport(id: string | null) {
  return useQuery({
    queryKey: ["reports", "detail", id],
    queryFn: async () => {
      await simulateLatency(250);
      return REPORTS.find((report) => report.id === id) ?? null;
    },
    enabled: Boolean(id),
  });
}
