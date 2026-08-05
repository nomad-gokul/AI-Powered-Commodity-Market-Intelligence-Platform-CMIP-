"use client";

import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { EChart } from "@/components/charts/echart";
import type { GraphDataset } from "@/lib/types/graph";
import {
  confidenceDistribution,
  entityGrowth,
  mostActivePorts,
  relationshipDistribution,
  topCommodities,
  topConnectedCompanies,
} from "@/lib/graph/analytics";
import { EDGE_COLORS } from "@/lib/graph/node-visuals";

function barOption(data: Array<{ name: string; value: number }>, color: string): EChartsOption {
  return {
    grid: { left: 90, right: 20, top: 10, bottom: 10 },
    xAxis: { type: "value", axisLabel: { fontSize: 10 } },
    yAxis: { type: "category", data: data.map((d) => d.name).reverse(), axisLabel: { fontSize: 10 } },
    tooltip: { trigger: "item" },
    series: [
      {
        type: "bar",
        data: data.map((d) => d.value).reverse(),
        itemStyle: { color, borderRadius: [0, 4, 4, 0] },
        barWidth: 14,
      },
    ],
  };
}

export function GraphAnalyticsPanel({ dataset, open, onOpenChange }: { dataset: GraphDataset; open: boolean; onOpenChange: (open: boolean) => void }) {
  const companies = useMemo(() => topConnectedCompanies(dataset), [dataset]);
  const ports = useMemo(() => mostActivePorts(dataset), [dataset]);
  const commodities = useMemo(() => topCommodities(dataset), [dataset]);
  const relDistribution = useMemo(() => relationshipDistribution(dataset), [dataset]);
  const growth = useMemo(() => entityGrowth(dataset), [dataset]);
  const confidence = useMemo(() => confidenceDistribution(dataset), [dataset]);

  const relOption: EChartsOption = {
    tooltip: { trigger: "item" },
    legend: { show: false },
    series: [
      {
        type: "pie",
        radius: ["45%", "72%"],
        label: { fontSize: 10, color: "#9a9aa2" },
        data: relDistribution.map((d) => ({
          name: d.name.replace(/_/g, " "),
          value: d.value,
          itemStyle: { color: EDGE_COLORS[d.name as keyof typeof EDGE_COLORS] },
        })),
      },
    ],
  };

  const growthOption: EChartsOption = {
    grid: { left: 36, right: 12, top: 12, bottom: 28 },
    xAxis: { type: "category", data: growth.map((g) => g.label), axisLabel: { fontSize: 9, interval: 1 } },
    yAxis: { type: "value", axisLabel: { fontSize: 10 } },
    tooltip: { trigger: "axis" },
    series: [
      {
        type: "line",
        data: growth.map((g) => g.cumulative),
        smooth: 0.2,
        showSymbol: false,
        lineStyle: { color: "#3b82f6", width: 2 },
        areaStyle: {
          color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "#3b82f633" }, { offset: 1, color: "#3b82f600" }] },
        },
      },
    ],
  };

  const confidenceOption: EChartsOption = {
    grid: { left: 36, right: 12, top: 12, bottom: 24 },
    xAxis: { type: "category", data: confidence.map((c) => c.name), axisLabel: { fontSize: 10 } },
    yAxis: { type: "value", axisLabel: { fontSize: 10 } },
    tooltip: { trigger: "axis" },
    series: [{ type: "bar", data: confidence.map((c) => c.value), itemStyle: { color: "#10b981", borderRadius: [4, 4, 0, 0] }, barWidth: 28 }],
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full max-w-xl overflow-y-auto">
        <SheetHeader>
          <SheetTitle>Graph Analytics</SheetTitle>
          <SheetDescription>Computed live from the entities and relationships currently in view.</SheetDescription>
        </SheetHeader>
        <div className="grid grid-cols-1 gap-4 px-4 pb-6 sm:grid-cols-2">
          <ChartCard title="Top Connected Companies">
            <EChart option={barOption(companies, "#3b82f6")} height={180} />
          </ChartCard>
          <ChartCard title="Most Active Ports">
            <EChart option={barOption(ports, "#10b981")} height={180} />
          </ChartCard>
          <ChartCard title="Top Commodities">
            <EChart option={barOption(commodities, "#f97316")} height={180} />
          </ChartCard>
          <ChartCard title="Relationship Distribution">
            <EChart option={relOption} height={180} />
          </ChartCard>
          <ChartCard title="Entity Growth">
            <EChart option={growthOption} height={180} />
          </ChartCard>
          <ChartCard title="Confidence Distribution">
            <EChart option={confidenceOption} height={180} />
          </ChartCard>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border/70 p-3">
      <p className="mb-1 text-xs font-medium text-muted-foreground">{title}</p>
      {children}
    </div>
  );
}
