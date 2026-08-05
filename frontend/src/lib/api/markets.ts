"use client";

import { useQuery } from "@tanstack/react-query";
import { simulateLatency } from "./client";
import { COMMODITY_DETAILS, MARKET_NEWS_FEED, MARKET_QUOTES } from "@/lib/mock-data/markets";

export function useMarketQuotes() {
  return useQuery({
    queryKey: ["markets", "quotes"],
    queryFn: async () => {
      await simulateLatency(300);
      return MARKET_QUOTES;
    },
  });
}

export function useMarketQuote(commodityId: string | null) {
  return useQuery({
    queryKey: ["markets", "quote", commodityId],
    queryFn: async () => {
      await simulateLatency(200);
      return MARKET_QUOTES.find((quote) => quote.commodity.id === commodityId) ?? null;
    },
    enabled: Boolean(commodityId),
  });
}

export function useCommodityDetail(commodityId: string | null) {
  return useQuery({
    queryKey: ["markets", "detail", commodityId],
    queryFn: async () => {
      await simulateLatency(350);
      return commodityId ? (COMMODITY_DETAILS[commodityId] ?? null) : null;
    },
    enabled: Boolean(commodityId),
  });
}

export function useMarketNewsFeed(commodityId?: string | null) {
  return useQuery({
    queryKey: ["markets", "news-feed", commodityId ?? "all"],
    queryFn: async () => {
      await simulateLatency(300);
      if (!commodityId) return MARKET_NEWS_FEED;
      return MARKET_NEWS_FEED.filter((item) => item.commodityIds.includes(commodityId));
    },
  });
}
