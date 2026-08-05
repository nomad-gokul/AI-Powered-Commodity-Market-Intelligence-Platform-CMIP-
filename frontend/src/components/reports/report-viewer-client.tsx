"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { PageTransition } from "@/components/motion/page-transition";
import { FadeIn } from "@/components/motion/fade-in";
import { DocumentViewer } from "./document-viewer";
import { KnowledgePanel } from "./knowledge-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { useReport } from "@/lib/api/reports";

export function ReportViewerClient({ reportId }: { reportId: string }) {
  const { data: report, isPending } = useReport(reportId);
  const [highlightedEntityId, setHighlightedEntityId] = useState<string | null>(null);

  if (isPending || !report) {
    return (
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <Skeleton className="h-[calc(100vh-8rem)] rounded-xl" />
        <Skeleton className="h-[calc(100vh-8rem)] rounded-xl" />
      </div>
    );
  }

  const highlightedEntity = report.entities.find((entity) => entity.id === highlightedEntityId);

  return (
    <PageTransition>
      <div className="flex h-[calc(100vh-8rem)] flex-col gap-3">
        <FadeIn className="flex items-center gap-3">
          <Link
            href="/reports"
            className="flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="size-4" /> Reports
          </Link>
          <span className="text-muted-foreground">/</span>
          <h1 className="truncate text-sm font-medium">{report.title}</h1>
          <Badge variant="secondary" className="ml-auto shrink-0 text-xs font-normal">
            {report.source}
          </Badge>
        </FadeIn>

        <FadeIn delay={0.05} className="min-h-0 flex-1">
          <div className="grid h-full grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
            <DocumentViewer report={report} highlightedEntityName={highlightedEntity?.name ?? null} />
            <KnowledgePanel
              report={report}
              highlightedEntityId={highlightedEntityId}
              onSelectEntity={setHighlightedEntityId}
            />
          </div>
        </FadeIn>
      </div>
    </PageTransition>
  );
}
