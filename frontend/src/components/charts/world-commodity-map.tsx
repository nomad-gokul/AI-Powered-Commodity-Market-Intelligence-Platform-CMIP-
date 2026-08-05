"use client";

import type { EChartsOption } from "echarts";
import { EChart } from "./echart";
import { ensureWorldMapRegistered } from "@/lib/geo/world-map";
import type { WorldMapRegion } from "@/lib/types/dashboard";

const RISK_COLOR_STOPS: Array<{ max: number; color: string }> = [
  { max: 33, color: "#10b981" },
  { max: 66, color: "#f59e0b" },
  { max: 101, color: "#ef4444" },
];

function riskColor(riskScore: number): string {
  return RISK_COLOR_STOPS.find((stop) => riskScore < stop.max)?.color ?? "#ef4444";
}

export function WorldCommodityMap({ regions }: { regions: WorldMapRegion[] }) {
  ensureWorldMapRegistered();

  const option: EChartsOption = {
    tooltip: {
      trigger: "item",
      formatter: (params: unknown) => {
        const point = params as { data?: WorldMapRegion & { value: number[] } };
        const region = point.data;
        if (!region) return "";
        return `<div style="font-weight:600;margin-bottom:4px">${region.countryName}</div>
          <div>Dominant: ${region.dominantCommodity}</div>
          <div>Activity: ${region.activityScore}</div>
          <div>Risk: ${region.riskScore}</div>`;
      },
    },
    geo: {
      map: "world",
      roam: true,
      silent: true,
      itemStyle: {
        areaColor: "#141417",
        borderColor: "#232326",
        borderWidth: 0.6,
      },
      emphasis: { disabled: true },
      left: 8,
      right: 8,
      top: 8,
      bottom: 8,
    },
    series: [
      {
        name: "Commodity activity",
        type: "effectScatter",
        coordinateSystem: "geo",
        symbolSize: (rawValue: unknown) => {
          const value = rawValue as number[];
          return 8 + (value[2] ?? 0) / 6;
        },
        rippleEffect: { period: 3.2, scale: 2.5, brushType: "stroke" },
        showEffectOn: "render",
        data: regions.map((region) => ({
          ...region,
          name: region.countryName,
          value: [...region.coordinates, region.activityScore],
          itemStyle: { color: riskColor(region.riskScore) },
        })),
        label: {
          show: true,
          formatter: (params: unknown) => (params as { data: WorldMapRegion }).data.countryCode,
          position: "top",
          color: "#d4d4d8",
          fontSize: 10,
          distance: 6,
        },
      },
    ],
  };

  return <EChart option={option} height={420} />;
}
