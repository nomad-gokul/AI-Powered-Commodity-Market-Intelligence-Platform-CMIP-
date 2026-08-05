import Link from "next/link";
import { FileText, Layers, Table2, ShieldCheck } from "lucide-react";
import type { Report } from "@/lib/types/reports";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const SOURCE_COLOR: Record<Report["source"], string> = {
  Argus: "from-blue-500/25",
  Platts: "from-emerald-500/25",
  Reuters: "from-amber-500/25",
  ICE: "from-violet-500/25",
  CME: "from-cyan-500/25",
  "Baltic Exchange": "from-rose-500/25",
  Internal: "from-zinc-500/25",
};

export function ReportCard({ report }: { report: Report }) {
  return (
    <Link href={`/reports/${report.id}`}>
      <Card className="glass-panel h-full gap-0 overflow-hidden p-0 transition-colors hover:border-border">
        <div
          className={cn(
            "flex h-20 items-start justify-between bg-gradient-to-br to-transparent p-3",
            SOURCE_COLOR[report.source]
          )}
        >
          <Badge variant="secondary" className="bg-background/70 text-[11px] font-medium backdrop-blur">
            {report.source}
          </Badge>
          {report.status === "processing" ? (
            <Badge className="bg-warning/15 text-[11px] font-normal text-warning">Processing</Badge>
          ) : (
            <FileText className="size-5 text-foreground/40" />
          )}
        </div>
        <div className="flex flex-1 flex-col gap-2.5 p-4">
          <div>
            <p className="line-clamp-2 text-sm font-medium text-foreground">{report.title}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {report.country} · {formatRelativeTime(report.uploadedAt)}
            </p>
          </div>
          <p className="line-clamp-2 text-xs text-muted-foreground">{report.summary}</p>
          <div className="mt-auto flex items-center justify-between border-t border-border/60 pt-2.5 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <ShieldCheck className="size-3.5 text-success" /> {report.confidence}%
            </span>
            <span className="flex items-center gap-1">
              <FileText className="size-3.5" /> {report.pageCount}p
            </span>
            <span className="flex items-center gap-1">
              <Layers className="size-3.5" /> {report.entities.length}
            </span>
            <span className="flex items-center gap-1">
              <Table2 className="size-3.5" /> {report.tables.length}
            </span>
          </div>
        </div>
      </Card>
    </Link>
  );
}
