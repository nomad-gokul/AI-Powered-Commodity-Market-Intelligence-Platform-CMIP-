"use client";

import ReactECharts from "echarts-for-react";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";
import { cn } from "@/lib/utils";

/**
 * One theme, registered once, shared by every chart on every page.
 * Colors are the same hex values as the CSS design tokens in
 * globals.css — echarts themes are plain JS objects and can't read CSS
 * custom properties, so this is a disclosed manual sync point (same
 * tradeoff as the shared/backend type mirrors).
 */
let themeRegistered = false;
function ensureTheme() {
  if (themeRegistered) return;
  echarts.registerTheme("argus-dark", {
    color: ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b8b93"],
    backgroundColor: "transparent",
    textStyle: { color: "#9a9aa2", fontFamily: "var(--font-geist-sans)" },
    title: { textStyle: { color: "#fafafa" } },
    legend: { textStyle: { color: "#d4d4d8" } },
    tooltip: {
      backgroundColor: "#17171a",
      borderColor: "#27272a",
      textStyle: { color: "#fafafa" },
    },
    categoryAxis: {
      axisLine: { lineStyle: { color: "#27272a" } },
      axisTick: { lineStyle: { color: "#27272a" } },
      axisLabel: { color: "#9a9aa2" },
      splitLine: { lineStyle: { color: "#1c1c1f" } },
    },
    valueAxis: {
      axisLine: { lineStyle: { color: "#27272a" } },
      axisTick: { lineStyle: { color: "#27272a" } },
      axisLabel: { color: "#9a9aa2" },
      splitLine: { lineStyle: { color: "#1c1c1f" } },
    },
  });
  themeRegistered = true;
}

interface EChartProps {
  option: EChartsOption;
  className?: string;
  height?: number | string;
}

export function EChart({ option, className, height = 280 }: EChartProps) {
  ensureTheme();
  return (
    <ReactECharts
      echarts={echarts}
      theme="argus-dark"
      option={option}
      notMerge
      lazyUpdate
      opts={{ renderer: "svg" }}
      style={{ height, width: "100%" }}
      className={cn(className)}
    />
  );
}
