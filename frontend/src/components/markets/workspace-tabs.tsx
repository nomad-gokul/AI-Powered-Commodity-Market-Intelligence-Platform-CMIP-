import Link from "next/link";
import { TrendingUp, TrendingDown, Sparkles, FileText } from "lucide-react";
import type { CommodityDetail } from "@/lib/types/market-detail";
import type { MarketQuote } from "@/lib/types/market";
import type { Report } from "@/lib/types/reports";
import { REPORTS } from "@/lib/mock-data/reports";
import { MARKET_NEWS_FEED } from "@/lib/mock-data/markets";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { RiskBadge } from "./risk-badge";
import { MarketMap } from "./market-map";
import { LiveMarketFeed } from "./live-market-feed";
import { formatRelativeTime, formatSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

function DriverList({ drivers }: { drivers: CommodityDetail["supplyDrivers"] }) {
  return (
    <div className="space-y-2">
      {drivers.map((driver, index) => (
        <div key={index} className="flex items-start gap-2.5 rounded-lg border border-border/70 p-3">
          {driver.impact === "bullish" ? (
            <TrendingUp className="mt-0.5 size-4 shrink-0 text-success" />
          ) : driver.impact === "bearish" ? (
            <TrendingDown className="mt-0.5 size-4 shrink-0 text-danger" />
          ) : (
            <Sparkles className="mt-0.5 size-4 shrink-0 text-info" />
          )}
          <p className="text-sm text-foreground/90">{driver.detail}</p>
        </div>
      ))}
    </div>
  );
}

export function OverviewTab({ quote, detail }: { quote: MarketQuote; detail: CommodityDetail }) {
  return (
    <div className="space-y-4">
      <p className="text-sm leading-relaxed text-foreground/90">{quote.marketSummary}</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="30D Volatility" value={`${detail.volatility30d}%`} />
        <StatCard label="Weekly Change" value={`${formatSigned(detail.weeklyChangePercent)}%`} tone={detail.weeklyChangePercent >= 0 ? "success" : "danger"} />
        <StatCard label="Monthly Change" value={`${formatSigned(detail.monthlyChangePercent)}%`} tone={detail.monthlyChangePercent >= 0 ? "success" : "danger"} />
        <StatCard label="Evidence Sources" value={String(detail.aiCommentary.evidenceCount)} />
      </div>
      <div>
        <p className="mb-2 text-xs font-medium text-muted-foreground">Inventory by Region</p>
        <div className="space-y-2">
          {detail.inventory.map((point) => (
            <div key={point.region} className="flex items-center gap-3">
              <span className="w-32 shrink-0 text-xs text-muted-foreground">{point.region}</span>
              <Progress value={point.level} className="h-1.5 flex-1" />
              <span
                className={cn(
                  "w-14 shrink-0 text-right text-xs tabular-nums",
                  point.changePercent >= 0 ? "text-success" : "text-danger"
                )}
              >
                {formatSigned(point.changePercent)}%
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, tone }: { label: string; value: string; tone?: "success" | "danger" }) {
  return (
    <div className="rounded-lg border border-border/70 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1 font-mono text-lg font-semibold tabular-nums",
          tone === "success" && "text-success",
          tone === "danger" && "text-danger"
        )}
      >
        {value}
      </p>
    </div>
  );
}

export function SupplyTab({ detail }: { detail: CommodityDetail }) {
  return <DriverList drivers={detail.supplyDrivers} />;
}

export function DemandTab({ detail }: { detail: CommodityDetail }) {
  return <DriverList drivers={detail.demandDrivers} />;
}

export function TradeFlowTab({ detail, commodityName }: { detail: CommodityDetail; commodityName: string }) {
  return (
    <div className="space-y-4">
      <MarketMap routes={detail.tradeRoutes} commodityName={commodityName} />
      <div className="space-y-1.5">
        {detail.tradeRoutes.map((route) => (
          <div key={route.id} className="flex items-center gap-3 rounded-lg border border-border/70 px-3 py-2 text-sm">
            <span className="flex-1 truncate">
              {route.origin} <span className="text-muted-foreground">→</span> {route.destination}
            </span>
            <span className="w-20 text-xs text-muted-foreground tabular-nums">vol {route.volumeIndex}</span>
            <Badge
              variant="secondary"
              className={cn(
                "text-[11px] font-normal capitalize",
                route.status === "disrupted" && "bg-danger/10 text-danger",
                route.status === "congested" && "bg-warning/10 text-warning"
              )}
            >
              {route.status}
            </Badge>
          </div>
        ))}
      </div>
    </div>
  );
}

export function NewsTab({ commodityId }: { commodityId: string }) {
  const filtered = MARKET_NEWS_FEED.filter((item) => item.commodityIds.includes(commodityId));
  return <LiveMarketFeed items={filtered} />;
}

export function RelatedReportsTab({ commodityId }: { commodityId: string }) {
  const reports: Report[] = REPORTS.filter((report) => report.commodityIds.includes(commodityId)).slice(0, 8);
  if (reports.length === 0) {
    return <p className="text-sm text-muted-foreground">No related reports indexed for this commodity yet.</p>;
  }
  return (
    <div className="space-y-2">
      {reports.map((report) => (
        <Link
          key={report.id}
          href={`/reports/${report.id}`}
          className="flex items-start gap-3 rounded-lg border border-border/70 p-3 transition-colors hover:border-border hover:bg-accent/40"
        >
          <FileText className="mt-0.5 size-4 shrink-0 text-primary" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-foreground">{report.title}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {report.source} · {report.country} · {formatRelativeTime(report.uploadedAt)}
            </p>
          </div>
          <Badge variant="secondary" className="shrink-0 text-[11px] font-normal">
            {report.confidence}%
          </Badge>
        </Link>
      ))}
    </div>
  );
}

export function AiCommentaryTab({ quote, detail }: { quote: MarketQuote; detail: CommodityDetail }) {
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-primary/20 bg-primary/5 p-4">
        <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-primary">
          <Sparkles className="size-3.5" /> AI-Generated Commentary
        </p>
        <p className="text-sm leading-relaxed text-foreground/90">{detail.aiCommentary.summary}</p>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <StatCard label="Confidence" value={`${detail.aiCommentary.confidence}%`} tone="success" />
        <StatCard label="Evidence" value={String(detail.aiCommentary.evidenceCount)} />
        <StatCard label="Generated" value={formatRelativeTime(detail.aiCommentary.generatedAt)} />
      </div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        Supply risk <RiskBadge level={quote.supplyRisk} /> · Demand risk <RiskBadge level={quote.demandRisk} />
      </div>
    </div>
  );
}
