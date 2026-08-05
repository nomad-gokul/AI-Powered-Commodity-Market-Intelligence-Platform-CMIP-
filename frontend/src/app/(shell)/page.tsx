"use client";

import Link from "next/link";
import { FileText, Share2, ShieldCheck, Search, Sparkles } from "lucide-react";
import { PageTransition } from "@/components/motion/page-transition";
import { FadeIn } from "@/components/motion/fade-in";
import { StaggerList, StaggerItem } from "@/components/motion/stagger-list";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { ActivityTimeline } from "@/components/dashboard/activity-timeline";
import { TopCommoditiesGrid } from "@/components/dashboard/top-commodities-grid";
import { WorldCommodityMap } from "@/components/charts/world-commodity-map";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useKpiSummary,
  useRecentActivity,
  useTopCommodities,
  useWorldMapRegions,
} from "@/lib/api/dashboard";

export default function DashboardPage() {
  const kpi = useKpiSummary();
  const activity = useRecentActivity();
  const commodities = useTopCommodities();
  const worldMap = useWorldMapRegions();

  return (
    <PageTransition>
      <div className="flex flex-col gap-6">
        <FadeIn>
          <div>
            <p className="text-xs font-medium tracking-wider text-primary uppercase">Overview</p>
            <h1 className="mt-1 font-heading text-2xl font-semibold tracking-tight sm:text-3xl">
              Commodity Market Intelligence
            </h1>
            <p className="mt-1.5 max-w-2xl text-sm text-muted-foreground">
              Real-time visibility across ingestion, knowledge graph, and hybrid retrieval —
              powered by ARGUS AI&rsquo;s document intelligence pipeline.
            </p>
          </div>
        </FadeIn>

        {kpi.isPending || !kpi.data ? (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-5">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-[104px] rounded-xl" />
            ))}
          </div>
        ) : (
          <StaggerList className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-5">
            <StaggerItem>
              <KpiCard
                label="Total Reports"
                value={kpi.data.totalReports}
                delta={kpi.data.totalReportsDelta}
                icon={FileText}
              />
            </StaggerItem>
            <StaggerItem>
              <KpiCard
                label="Intelligence Graph Nodes"
                value={kpi.data.knowledgeGraphNodes}
                delta={kpi.data.knowledgeGraphNodesDelta}
                icon={Share2}
              />
            </StaggerItem>
            <StaggerItem>
              <KpiCard
                label="Validated Entities"
                value={kpi.data.validatedEntities}
                delta={kpi.data.validatedEntitiesDelta}
                icon={ShieldCheck}
              />
            </StaggerItem>
            <StaggerItem>
              <KpiCard
                label="Retrieval Runs"
                value={kpi.data.retrievalRuns}
                delta={kpi.data.retrievalRunsDelta}
                icon={Search}
              />
            </StaggerItem>
            <StaggerItem>
              <KpiCard
                label="AI Confidence"
                value={kpi.data.aiConfidence}
                delta={kpi.data.aiConfidenceDelta}
                icon={Sparkles}
                decimals={1}
                suffix="%"
              />
            </StaggerItem>
          </StaggerList>
        )}

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <FadeIn delay={0.05} className="xl:col-span-2">
            <Card className="glass-panel h-full gap-4">
              <CardHeader>
                <CardTitle>World Commodity Map</CardTitle>
                <CardDescription>Activity and supply/demand risk by trading hub</CardDescription>
              </CardHeader>
              <CardContent>
                {worldMap.isPending || !worldMap.data ? (
                  <Skeleton className="h-[420px] rounded-lg" />
                ) : (
                  <WorldCommodityMap regions={worldMap.data} />
                )}
              </CardContent>
            </Card>
          </FadeIn>

          <FadeIn delay={0.1}>
            <Card className="glass-panel h-full gap-4">
              <CardHeader>
                <CardTitle>Recent Activity</CardTitle>
                <CardDescription>Live pipeline &amp; retrieval events</CardDescription>
              </CardHeader>
              <CardContent className="scrollbar-thin max-h-[420px] overflow-y-auto">
                {activity.isPending || !activity.data ? (
                  <div className="space-y-3">
                    {Array.from({ length: 5 }).map((_, index) => (
                      <Skeleton key={index} className="h-10 rounded-lg" />
                    ))}
                  </div>
                ) : (
                  <ActivityTimeline events={activity.data} />
                )}
              </CardContent>
            </Card>
          </FadeIn>
        </div>

        <FadeIn delay={0.15}>
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="font-heading text-lg font-semibold tracking-tight">Top Commodities</h2>
            <Link href="/markets" className="text-xs font-medium text-primary hover:underline">
              View all markets →
            </Link>
          </div>
          {commodities.isPending || !commodities.data ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {Array.from({ length: 8 }).map((_, index) => (
                <Skeleton key={index} className="h-[104px] rounded-xl" />
              ))}
            </div>
          ) : (
            <TopCommoditiesGrid commodities={commodities.data} />
          )}
        </FadeIn>
      </div>
    </PageTransition>
  );
}
