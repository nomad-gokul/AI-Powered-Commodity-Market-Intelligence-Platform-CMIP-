"use client";

import { useMemo, useState } from "react";
import { PageTransition } from "@/components/motion/page-transition";
import { FadeIn } from "@/components/motion/fade-in";
import { StaggerList, StaggerItem } from "@/components/motion/stagger-list";
import { FiltersSidebar } from "@/components/reports/filters-sidebar";
import { ReportCard } from "@/components/reports/report-card";
import { ProcessingPipeline } from "@/components/reports/processing-pipeline";
import { UploadDropzone } from "@/components/reports/upload-dropzone";
import { Skeleton } from "@/components/ui/skeleton";
import { REPORTS } from "@/lib/mock-data/reports";
import { useReports } from "@/lib/api/reports";
import type { ReportFilters } from "@/lib/types/reports";

const EMPTY_FILTERS: ReportFilters = { sources: [], commodityId: null, country: null, tag: null, query: "" };

export default function ReportsPage() {
  const [filters, setFilters] = useState<ReportFilters>(EMPTY_FILTERS);
  const reports = useReports(filters);

  const countries = useMemo(() => Array.from(new Set(REPORTS.map((r) => r.country))).sort(), []);
  const tags = useMemo(() => Array.from(new Set(REPORTS.flatMap((r) => r.tags))).sort(), []);
  const processingReport = useMemo(() => REPORTS.find((r) => r.status === "processing"), []);

  return (
    <PageTransition>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[260px_minmax(0,1fr)_300px]">
        <FadeIn className="xl:h-[calc(100vh-8rem)]">
          <FiltersSidebar filters={filters} onChange={setFilters} countries={countries} tags={tags} />
        </FadeIn>

        <FadeIn delay={0.05} className="min-w-0">
          <div className="mb-4 flex items-baseline justify-between">
            <div>
              <h1 className="font-heading text-2xl font-semibold tracking-tight">Reports</h1>
              <p className="mt-0.5 text-sm text-muted-foreground">
                {reports.data?.length ?? "…"} documents across Argus, Platts, Reuters, ICE, CME &amp; Baltic Exchange
              </p>
            </div>
          </div>

          {reports.isPending || !reports.data ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, index) => (
                <Skeleton key={index} className="h-56 rounded-xl" />
              ))}
            </div>
          ) : reports.data.length === 0 ? (
            <div className="glass-panel rounded-xl border p-10 text-center text-sm text-muted-foreground">
              No reports match the current filters.
            </div>
          ) : (
            <StaggerList className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {reports.data.map((report) => (
                <StaggerItem key={report.id}>
                  <ReportCard report={report} />
                </StaggerItem>
              ))}
            </StaggerList>
          )}
        </FadeIn>

        <FadeIn delay={0.1} className="space-y-4 xl:h-[calc(100vh-8rem)] xl:overflow-y-auto xl:pr-1">
          {processingReport && (
            <ProcessingPipeline
              stages={processingReport.processingStages}
              title={`Processing — ${processingReport.title}`}
            />
          )}
          <UploadDropzone />
        </FadeIn>
      </div>
    </PageTransition>
  );
}
