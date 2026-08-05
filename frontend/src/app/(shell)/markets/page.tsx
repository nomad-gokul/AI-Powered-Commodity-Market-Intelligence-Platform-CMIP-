"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { PageTransition } from "@/components/motion/page-transition";
import { FadeIn } from "@/components/motion/fade-in";
import { CategorySidebar } from "@/components/markets/category-sidebar";
import { CommodityWorkspace } from "@/components/markets/commodity-workspace";
import { AiIntelligencePanel } from "@/components/markets/ai-intelligence-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { useCommodityDetail, useMarketQuote } from "@/lib/api/markets";

function MarketsPageInner() {
  const searchParams = useSearchParams();
  const initial = searchParams.get("commodity") ?? "naphtha";
  const [selected, setSelected] = useState(initial);

  const quote = useMarketQuote(selected);
  const detail = useCommodityDetail(selected);
  const isLoading = quote.isPending || detail.isPending;

  return (
    <PageTransition>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[240px_minmax(0,1fr)_300px]">
        <FadeIn className="xl:h-[calc(100vh-8rem)]">
          <CategorySidebar selectedCommodityId={selected} onSelect={setSelected} />
        </FadeIn>

        <FadeIn delay={0.05} className="min-w-0">
          <CommodityWorkspace quote={quote.data} detail={detail.data} isLoading={isLoading} />
        </FadeIn>

        <FadeIn delay={0.1} className="xl:h-[calc(100vh-8rem)]">
          {isLoading || !quote.data || !detail.data ? (
            <Skeleton className="h-full rounded-xl" />
          ) : (
            <AiIntelligencePanel quote={quote.data} detail={detail.data} />
          )}
        </FadeIn>
      </div>
    </PageTransition>
  );
}

export default function MarketsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 rounded-xl" />}>
      <MarketsPageInner />
    </Suspense>
  );
}
