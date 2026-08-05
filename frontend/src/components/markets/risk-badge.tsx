import type { RiskLevel } from "@/lib/types/market";
import { cn } from "@/lib/utils";

const RISK_STYLES: Record<RiskLevel, string> = {
  low: "bg-success/10 text-success",
  moderate: "bg-info/10 text-info",
  elevated: "bg-warning/10 text-warning",
  high: "bg-danger/10 text-danger",
};

const RISK_LABELS: Record<RiskLevel, string> = {
  low: "Low",
  moderate: "Moderate",
  elevated: "Elevated",
  high: "High",
};

export const RISK_DOT_COLOR: Record<RiskLevel, string> = {
  low: "#10b981",
  moderate: "#3b82f6",
  elevated: "#f59e0b",
  high: "#ef4444",
};

export function RiskBadge({ level, className }: { level: RiskLevel; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-medium",
        RISK_STYLES[level],
        className
      )}
    >
      {RISK_LABELS[level]}
    </span>
  );
}
