import type { EChartsOption } from "echarts";
import Link from "next/link";
import { EChart } from "@/components/charts/echart";
import { Card } from "@/components/ui/card";
import type { CommoditySnapshot } from "@/lib/types/dashboard";
import { cn } from "@/lib/utils";
import { formatSigned } from "@/lib/format";

function sparklineOption(data: number[], color: string): EChartsOption {
  return {
    grid: { left: 0, right: 0, top: 4, bottom: 0 },
    xAxis: { type: "category", show: false, data: data.map((_, index) => index) },
    yAxis: { type: "value", show: false, min: "dataMin", max: "dataMax" },
    tooltip: { show: false },
    series: [
      {
        type: "line",
        data,
        showSymbol: false,
        lineStyle: { width: 1.5, color },
        areaStyle: { color, opacity: 0.1 },
        animationDuration: 500,
      },
    ],
  };
}

export function TopCommoditiesGrid({ commodities }: { commodities: CommoditySnapshot[] }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {commodities.map((commodity) => {
        const positive = commodity.changePercent >= 0;
        const color = positive ? "#10b981" : "#ef4444";
        return (
          <Link key={commodity.commodityId} href="/markets">
            <Card className="glass-panel gap-2 p-4 transition-colors hover:border-border">
              <div className="flex items-start justify-between">
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium text-muted-foreground">
                    {commodity.shortName}
                  </p>
                  <p className="mt-0.5 font-mono text-base font-semibold tabular-nums">
                    {commodity.price.toLocaleString("en-US", { maximumFractionDigits: 2 })}
                  </p>
                </div>
                <span
                  className={cn(
                    "shrink-0 rounded-md px-1.5 py-0.5 text-[11px] font-medium tabular-nums",
                    positive ? "bg-success/10 text-success" : "bg-danger/10 text-danger"
                  )}
                >
                  {formatSigned(commodity.changePercent)}%
                </span>
              </div>
              <EChart option={sparklineOption(commodity.sparkline, color)} height={36} />
            </Card>
          </Link>
        );
      })}
    </div>
  );
}
