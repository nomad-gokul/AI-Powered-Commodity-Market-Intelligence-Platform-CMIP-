"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Radio } from "lucide-react";
import type { MarketNewsItem } from "@/lib/types/market-detail";
import { Badge } from "@/components/ui/badge";

export function LiveMarketFeed({ items }: { items: MarketNewsItem[] }) {
  return (
    <div className="glass-panel rounded-xl border p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="relative flex size-2">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-danger opacity-75" />
          <span className="relative inline-flex size-2 rounded-full bg-danger" />
        </span>
        <h3 className="text-sm font-semibold tracking-tight">Live Market Feed</h3>
        <Radio className="ml-auto size-3.5 text-muted-foreground" />
      </div>
      <div className="scrollbar-thin max-h-56 space-y-1.5 overflow-y-auto">
        <AnimatePresence initial={false}>
          {items.map((item) => (
            <motion.div
              key={item.id}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="flex items-center gap-3 rounded-lg px-2 py-1.5 text-sm hover:bg-accent/60"
            >
              <span className="w-11 shrink-0 font-mono text-xs text-muted-foreground tabular-nums">
                {item.time}
              </span>
              <span className="min-w-0 flex-1 truncate text-foreground/90">{item.headline}</span>
              <Badge variant="outline" className="shrink-0 text-[10px] font-normal text-muted-foreground">
                {item.source}
              </Badge>
            </motion.div>
          ))}
        </AnimatePresence>
        {items.length === 0 && (
          <p className="px-2 py-4 text-center text-sm text-muted-foreground">
            No recent news for this commodity.
          </p>
        )}
      </div>
    </div>
  );
}
