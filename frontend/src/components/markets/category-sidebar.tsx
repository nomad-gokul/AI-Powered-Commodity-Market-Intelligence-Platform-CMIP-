"use client";

import { useState } from "react";
import { ChevronRight, Flame, Gem, Ship, Wheat } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { CATEGORY_TREE, type MarketCategoryGroup } from "@/lib/types/market-detail";
import { COMMODITIES } from "@/lib/types/market";
import { cn } from "@/lib/utils";

const GROUP_ICONS: Record<MarketCategoryGroup, typeof Flame> = {
  Energy: Flame,
  Metals: Gem,
  Agriculture: Wheat,
  Shipping: Ship,
};

const commodityById = new Map(COMMODITIES.map((commodity) => [commodity.id, commodity]));

interface CategorySidebarProps {
  selectedCommodityId: string;
  onSelect: (commodityId: string) => void;
}

export function CategorySidebar({ selectedCommodityId, onSelect }: CategorySidebarProps) {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(
    () => new Set(CATEGORY_TREE.map((node) => node.group))
  );

  function toggleGroup(group: string) {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(group)) next.delete(group);
      else next.add(group);
      return next;
    });
  }

  return (
    <div className="glass-panel scrollbar-thin h-full overflow-y-auto rounded-xl border p-3">
      <p className="px-1.5 pb-2 text-xs font-medium tracking-wider text-muted-foreground uppercase">
        Market Categories
      </p>
      <div className="space-y-1">
        {CATEGORY_TREE.map((node) => {
          const Icon = GROUP_ICONS[node.group];
          const expanded = expandedGroups.has(node.group);
          return (
            <div key={node.group}>
              <button
                type="button"
                onClick={() => toggleGroup(node.group)}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-sm font-medium text-foreground/90 transition-colors hover:bg-accent"
              >
                <motion.span animate={{ rotate: expanded ? 90 : 0 }} transition={{ duration: 0.15 }}>
                  <ChevronRight className="size-3.5 text-muted-foreground" />
                </motion.span>
                <Icon className="size-3.5 text-primary" />
                {node.group}
              </button>
              <AnimatePresence initial={false}>
                {expanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.18 }}
                    className="overflow-hidden pl-6"
                  >
                    {node.subgroups.map((subgroup) => (
                      <div key={subgroup.label} className="py-1">
                        {node.subgroups.length > 1 && (
                          <p className="px-2 pt-1 pb-0.5 text-[11px] font-medium text-muted-foreground">
                            {subgroup.label}
                          </p>
                        )}
                        {subgroup.commodityIds.map((id) => {
                          const commodity = commodityById.get(id);
                          if (!commodity) return null;
                          const active = id === selectedCommodityId;
                          return (
                            <button
                              key={id}
                              type="button"
                              onClick={() => onSelect(id)}
                              className={cn(
                                "block w-full rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                                active
                                  ? "bg-primary/15 font-medium text-primary"
                                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
                              )}
                            >
                              {commodity.name}
                            </button>
                          );
                        })}
                      </div>
                    ))}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </div>
  );
}
