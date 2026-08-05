import type { EChartsOption } from "echarts";
import { EChart } from "@/components/charts/echart";
import type { TrendPoint } from "@/lib/types/market-detail";

export function PriceChart({ history, unit }: { history: TrendPoint[]; unit: string }) {
  const dates = history.map((point) =>
    new Date(point.timestamp).toLocaleDateString("en-US", { month: "short", day: "numeric" })
  );
  const prices = history.map((point) => point.price);
  const positive = prices[prices.length - 1] >= prices[0];
  const color = positive ? "#10b981" : "#ef4444";

  const option: EChartsOption = {
    grid: { left: 48, right: 16, top: 16, bottom: 28 },
    xAxis: {
      type: "category",
      data: dates,
      boundaryGap: false,
      axisLabel: { fontSize: 10, interval: Math.floor(dates.length / 8) },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { fontSize: 10, formatter: `{value} ${unit.split("/")[0]}` },
    },
    tooltip: {
      trigger: "axis",
      valueFormatter: (value) => `${value} ${unit}`,
    },
    series: [
      {
        type: "line",
        data: prices,
        showSymbol: false,
        smooth: 0.15,
        lineStyle: { width: 2, color },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: `${color}33` },
              { offset: 1, color: `${color}00` },
            ],
          },
        },
      },
    ],
  };

  return <EChart option={option} height={280} />;
}
