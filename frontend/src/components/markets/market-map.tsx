"use client";

import type { EChartsOption } from "echarts";
import { EChart } from "@/components/charts/echart";
import { ensureWorldMapRegistered } from "@/lib/geo/world-map";
import { PORT_COORDINATES, PORT_COUNTRY } from "@/lib/geo/ports";
import type { TradeRoute } from "@/lib/types/market-detail";

const STATUS_COLOR: Record<TradeRoute["status"], string> = {
  normal: "#3b82f6",
  congested: "#f59e0b",
  disrupted: "#ef4444",
};

interface MarketMapProps {
  routes: TradeRoute[];
  commodityName: string;
  latestReportTitle?: string;
}

export function MarketMap({ routes, commodityName, latestReportTitle }: MarketMapProps) {
  ensureWorldMapRegistered();

  const hubNames = Array.from(new Set(routes.flatMap((route) => [route.origin, route.destination])));

  const option: EChartsOption = {
    tooltip: {
      trigger: "item",
      formatter: (params: unknown) => {
        const point = params as { seriesType: string; data?: { name?: string; status?: string } };
        if (point.seriesType === "lines") {
          return `<div style="font-weight:600">${commodityName} trade route</div><div>Status: ${point.data?.status}</div>`;
        }
        const name = point.data?.name ?? "";
        return `<div style="font-weight:600;margin-bottom:4px">${name}</div>
          <div>Country: ${PORT_COUNTRY[name] ?? "—"}</div>
          <div>Commodity: ${commodityName}</div>
          ${latestReportTitle ? `<div>Latest report: ${latestReportTitle}</div>` : ""}`;
      },
    },
    geo: {
      map: "world",
      roam: true,
      silent: true,
      itemStyle: { areaColor: "#141417", borderColor: "#232326", borderWidth: 0.6 },
      emphasis: { disabled: true },
      left: 8,
      right: 8,
      top: 8,
      bottom: 8,
    },
    series: [
      {
        name: "Trade routes",
        type: "lines",
        coordinateSystem: "geo",
        polyline: false,
        effect: { show: true, period: 4, symbolSize: 4 },
        lineStyle: {
          width: 1.5,
          curveness: 0.2,
          opacity: 0.6,
        },
        data: routes.map((route) => ({
          coords: [route.originCoordinates, route.destinationCoordinates],
          status: route.status,
          lineStyle: { color: STATUS_COLOR[route.status] },
        })),
      },
      {
        name: "Trade hubs",
        type: "effectScatter",
        coordinateSystem: "geo",
        symbolSize: 8,
        rippleEffect: { period: 3, scale: 2.2, brushType: "stroke" },
        itemStyle: { color: "#3b82f6" },
        label: {
          show: true,
          formatter: "{b}",
          position: "top",
          color: "#d4d4d8",
          fontSize: 10,
          distance: 6,
        },
        data: hubNames.map((name) => ({
          name,
          value: PORT_COORDINATES[name],
        })),
      },
    ],
  };

  return <EChart option={option} height={360} />;
}
