import { Building2, CloudRain, Globe2, Sparkles, Anchor } from "lucide-react";
import type { CommodityDetail } from "@/lib/types/market-detail";
import type { MarketQuote } from "@/lib/types/market";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { RiskBadge } from "./risk-badge";

function EntityChips({ label, icon: Icon, items }: { label: string; icon: typeof Building2; items: Array<{ id: string; name: string }> }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <Icon className="size-3.5" /> {label}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <Badge key={item.id} variant="secondary" className="text-xs font-normal">
            {item.name}
          </Badge>
        ))}
      </div>
    </div>
  );
}

export function AiIntelligencePanel({ quote, detail }: { quote: MarketQuote; detail: CommodityDetail }) {
  return (
    <div className="glass-panel flex h-full flex-col gap-5 overflow-y-auto rounded-xl border p-4">
      <div>
        <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-primary">
          <Sparkles className="size-3.5" /> Today&rsquo;s Summary
        </p>
        <p className="text-sm leading-relaxed text-foreground/90">{detail.aiCommentary.summary}</p>
        <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
          <span>{detail.aiCommentary.evidenceCount} evidence sources</span>
        </div>
        <div className="mt-2">
          <div className="mb-1 flex items-center justify-between text-xs">
            <span className="text-muted-foreground">AI Confidence</span>
            <span className="font-mono font-medium tabular-nums">{detail.aiCommentary.confidence}%</span>
          </div>
          <Progress value={detail.aiCommentary.confidence} className="h-1.5" />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg border border-border/70 p-2.5">
          <p className="text-xs text-muted-foreground">Supply Risk</p>
          <RiskBadge level={quote.supplyRisk} className="mt-1" />
        </div>
        <div className="rounded-lg border border-border/70 p-2.5">
          <p className="text-xs text-muted-foreground">Demand Risk</p>
          <RiskBadge level={quote.demandRisk} className="mt-1" />
        </div>
      </div>

      <div>
        <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <CloudRain className="size-3.5" /> Weather Impact
        </p>
        <p className="text-sm text-foreground/80">{detail.weatherImpact}</p>
      </div>

      <div>
        <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <Anchor className="size-3.5" /> Shipping Status
        </p>
        <p className="text-sm text-foreground/80">{detail.shippingStatus}</p>
      </div>

      <EntityChips label="Related Companies" icon={Building2} items={detail.relatedCompanies} />
      <EntityChips label="Related Countries" icon={Globe2} items={detail.relatedCountries} />
      <EntityChips label="Related Ports" icon={Anchor} items={detail.relatedPorts} />
    </div>
  );
}
