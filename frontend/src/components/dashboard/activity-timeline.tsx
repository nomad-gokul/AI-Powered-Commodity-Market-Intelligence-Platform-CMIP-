import {
  FileUp,
  ScanText,
  ShieldAlert,
  Share2,
  Search,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import type { ActivityEvent, ActivityEventKind } from "@/lib/types/dashboard";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const KIND_META: Record<ActivityEventKind, { icon: LucideIcon; tone: string }> = {
  document_ingested: { icon: FileUp, tone: "text-info bg-info/10" },
  extraction_completed: { icon: ScanText, tone: "text-info bg-info/10" },
  validation_flagged: { icon: ShieldAlert, tone: "text-warning bg-warning/10" },
  graph_updated: { icon: Share2, tone: "text-success bg-success/10" },
  retrieval_run: { icon: Search, tone: "text-info bg-info/10" },
  alert_raised: { icon: TriangleAlert, tone: "text-danger bg-danger/10" },
};

export function ActivityTimeline({ events }: { events: ActivityEvent[] }) {
  return (
    <ol className="space-y-0.5">
      {events.map((event, index) => {
        const meta = KIND_META[event.kind];
        const Icon = meta.icon;
        const isLast = index === events.length - 1;
        return (
          <li key={event.id} className="relative flex gap-3 pb-4 last:pb-0">
            {!isLast && (
              <span className="absolute top-8 left-[15px] h-[calc(100%-1.75rem)] w-px bg-border" />
            )}
            <div
              className={cn(
                "z-10 flex size-8 shrink-0 items-center justify-center rounded-full",
                meta.tone
              )}
            >
              <Icon className="size-3.5" />
            </div>
            <div className="min-w-0 flex-1 pt-1">
              <div className="flex items-baseline justify-between gap-2">
                <p className="truncate text-sm font-medium text-foreground">{event.title}</p>
                <time
                  className="shrink-0 text-[11px] text-muted-foreground tabular-nums"
                  suppressHydrationWarning
                >
                  {formatRelativeTime(event.timestamp)}
                </time>
              </div>
              <p className="mt-0.5 truncate text-xs text-muted-foreground">{event.detail}</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground/70">{event.actor}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
