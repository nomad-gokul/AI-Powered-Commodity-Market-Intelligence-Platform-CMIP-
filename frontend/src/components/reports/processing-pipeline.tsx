"use client";

import { motion } from "framer-motion";
import { Check, Loader2 } from "lucide-react";
import { PROCESSING_STAGES, type ProcessingStageStatus } from "@/lib/types/reports";
import { cn } from "@/lib/utils";

export function ProcessingPipeline({
  stages,
  title = "Processing Pipeline",
}: {
  stages: ProcessingStageStatus[];
  title?: string;
}) {
  return (
    <div className="glass-panel rounded-xl border p-4">
      <p
        title={title}
        className="mb-4 truncate text-xs font-medium tracking-wider text-muted-foreground uppercase"
      >
        {title}
      </p>
      <ol>
        {PROCESSING_STAGES.map((stage, index) => {
          const status = stages.find((s) => s.stage === stage.id)?.status ?? "pending";
          const isLast = index === PROCESSING_STAGES.length - 1;
          return (
            <li key={stage.id} className="relative flex gap-3 pb-6 last:pb-0">
              {!isLast && (
                <span className="absolute top-6 left-[11px] h-[calc(100%-1.25rem)] w-px overflow-hidden bg-border">
                  <motion.span
                    initial={{ height: 0 }}
                    animate={{ height: status === "completed" ? "100%" : "0%" }}
                    transition={{ duration: 0.4 }}
                    className="block w-full bg-success"
                  />
                </span>
              )}
              <div
                className={cn(
                  "z-10 flex size-6 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
                  status === "completed" && "border-success bg-success/15 text-success",
                  status === "in_progress" && "border-primary bg-primary/15 text-primary",
                  status === "pending" && "border-border bg-transparent text-muted-foreground",
                  status === "failed" && "border-danger bg-danger/15 text-danger"
                )}
              >
                {status === "completed" && <Check className="size-3.5" />}
                {status === "in_progress" && <Loader2 className="size-3.5 animate-spin" />}
              </div>
              <div className="pt-0.5">
                <p
                  className={cn(
                    "text-sm font-medium",
                    status === "pending" ? "text-muted-foreground" : "text-foreground"
                  )}
                >
                  {stage.label}
                </p>
                {status === "in_progress" && (
                  <p className="text-xs text-primary">In progress…</p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
