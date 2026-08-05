import { ArrowDownRight, ArrowUpRight, type LucideIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { CountUp } from "@/components/motion/count-up";
import { cn } from "@/lib/utils";
import { formatSigned } from "@/lib/format";

interface KpiCardProps {
  label: string;
  value: number;
  delta: number;
  icon: LucideIcon;
  decimals?: number;
  suffix?: string;
}

export function KpiCard({ label, value, delta, icon: Icon, decimals = 0, suffix = "" }: KpiCardProps) {
  const positive = delta >= 0;
  return (
    <Card className="glass-panel gap-3 transition-colors hover:border-border">
      <CardContent className="flex items-start justify-between">
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-muted-foreground">{label}</span>
          <span className="font-mono text-2xl font-semibold tracking-tight tabular-nums">
            <CountUp value={value} decimals={decimals} suffix={suffix} />
          </span>
          <span
            className={cn(
              "flex items-center gap-0.5 text-xs font-medium tabular-nums",
              positive ? "text-success" : "text-danger"
            )}
          >
            {positive ? <ArrowUpRight className="size-3.5" /> : <ArrowDownRight className="size-3.5" />}
            {formatSigned(delta)}% vs last period
          </span>
        </div>
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="size-5" />
        </div>
      </CardContent>
    </Card>
  );
}
