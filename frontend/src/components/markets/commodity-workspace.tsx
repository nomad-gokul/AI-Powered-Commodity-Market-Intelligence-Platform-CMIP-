"use client";

import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import type { CommodityDetail } from "@/lib/types/market-detail";
import type { MarketQuote } from "@/lib/types/market";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PriceChart } from "./price-chart";
import { LiveMarketFeed } from "./live-market-feed";
import {
  AiCommentaryTab,
  DemandTab,
  NewsTab,
  OverviewTab,
  RelatedReportsTab,
  SupplyTab,
  TradeFlowTab,
} from "./workspace-tabs";
import { MARKET_NEWS_FEED } from "@/lib/mock-data/markets";
import { cn } from "@/lib/utils";
import { formatSigned } from "@/lib/format";

const TABS = [
  { value: "overview", label: "Overview" },
  { value: "supply", label: "Supply" },
  { value: "demand", label: "Demand" },
  { value: "trade-flow", label: "Trade Flow" },
  { value: "news", label: "News" },
  { value: "related-reports", label: "Related Reports" },
  { value: "ai-commentary", label: "AI Commentary" },
];

interface CommodityWorkspaceProps {
  quote: MarketQuote | null | undefined;
  detail: CommodityDetail | null | undefined;
  isLoading: boolean;
}

export function CommodityWorkspace({ quote, detail, isLoading }: CommodityWorkspaceProps) {
  if (isLoading || !quote || !detail) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-20 rounded-xl" />
        <Skeleton className="h-72 rounded-xl" />
        <Skeleton className="h-40 rounded-xl" />
      </div>
    );
  }

  const positive = quote.changePercent >= 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium text-muted-foreground">{quote.commodity.category.replace("_", " ").toUpperCase()}</p>
          <h1 className="font-heading text-2xl font-semibold tracking-tight sm:text-3xl">
            {quote.commodity.name}
          </h1>
          <p className="mt-0.5 text-xs text-muted-foreground">{quote.commodity.unit}</p>
        </div>
        <div className="flex items-baseline gap-4">
          <span className="font-mono text-3xl font-semibold tabular-nums">{quote.price.toLocaleString("en-US")}</span>
          <span
            className={cn(
              "flex items-center gap-0.5 font-mono text-sm font-medium tabular-nums",
              positive ? "text-success" : "text-danger"
            )}
          >
            {positive ? <ArrowUpRight className="size-4" /> : <ArrowDownRight className="size-4" />}
            {formatSigned(quote.changeAbsolute)} ({formatSigned(quote.changePercent)}%)
          </span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <ChangeStat label="Daily" value={detail.dailyChangePercent} />
        <ChangeStat label="Weekly" value={detail.weeklyChangePercent} />
        <ChangeStat label="Monthly" value={detail.monthlyChangePercent} />
      </div>

      <Card className="glass-panel gap-3 p-4">
        <PriceChart history={detail.priceHistory} unit={quote.commodity.unit} />
      </Card>

      <LiveMarketFeed items={MARKET_NEWS_FEED.slice(0, 8)} />

      <Card className="glass-panel gap-3 p-4">
        <Tabs defaultValue="overview">
          <TabsList className="w-full justify-start overflow-x-auto">
            {TABS.map((tab) => (
              <TabsTrigger key={tab.value} value={tab.value} className="shrink-0">
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
          <CardContent className="px-0 pt-4">
            <TabsContent value="overview">
              <OverviewTab quote={quote} detail={detail} />
            </TabsContent>
            <TabsContent value="supply">
              <SupplyTab detail={detail} />
            </TabsContent>
            <TabsContent value="demand">
              <DemandTab detail={detail} />
            </TabsContent>
            <TabsContent value="trade-flow">
              <TradeFlowTab detail={detail} commodityName={quote.commodity.name} />
            </TabsContent>
            <TabsContent value="news">
              <NewsTab commodityId={quote.commodity.id} />
            </TabsContent>
            <TabsContent value="related-reports">
              <RelatedReportsTab commodityId={quote.commodity.id} />
            </TabsContent>
            <TabsContent value="ai-commentary">
              <AiCommentaryTab quote={quote} detail={detail} />
            </TabsContent>
          </CardContent>
        </Tabs>
      </Card>
    </div>
  );
}

function ChangeStat({ label, value }: { label: string; value: number }) {
  const positive = value >= 0;
  return (
    <div className="glass-panel rounded-xl border p-3">
      <p className="text-xs text-muted-foreground">{label} Trend</p>
      <p className={cn("mt-1 font-mono text-lg font-semibold tabular-nums", positive ? "text-success" : "text-danger")}>
        {formatSigned(value)}%
      </p>
    </div>
  );
}
