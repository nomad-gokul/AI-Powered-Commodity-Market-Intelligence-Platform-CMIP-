"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { UploadCloud, FileCheck2, RotateCcw } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ProcessingPipeline } from "./processing-pipeline";
import { PROCESSING_STAGES, type ProcessingStageStatus } from "@/lib/types/reports";
import { cn } from "@/lib/utils";

type Phase = "idle" | "uploading" | "processing" | "done";

const SUPPORTED = ["PDF", "DOCX", "CSV"];

export function UploadDropzone() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [fileName, setFileName] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [stageIndex, setStageIndex] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (phase !== "uploading") return;
    setProgress(0);
    const interval = setInterval(() => {
      setProgress((prev) => {
        if (prev >= 100) {
          clearInterval(interval);
          setPhase("processing");
          return 100;
        }
        return prev + Math.random() * 18 + 6;
      });
    }, 180);
    return () => clearInterval(interval);
  }, [phase]);

  useEffect(() => {
    if (phase !== "processing") return;
    setStageIndex(0);
    const interval = setInterval(() => {
      setStageIndex((prev) => {
        if (prev >= PROCESSING_STAGES.length - 1) {
          clearInterval(interval);
          setPhase("done");
          return prev;
        }
        return prev + 1;
      });
    }, 550);
    return () => clearInterval(interval);
  }, [phase]);

  function startUpload(name: string) {
    setFileName(name);
    setPhase("uploading");
  }

  function reset() {
    setPhase("idle");
    setFileName(null);
    setProgress(0);
    setStageIndex(0);
  }

  const stages: ProcessingStageStatus[] = PROCESSING_STAGES.map((stage, index) => ({
    stage: stage.id,
    status: index < stageIndex ? "completed" : index === stageIndex ? "in_progress" : "pending",
  }));

  return (
    <div className="glass-panel rounded-xl border p-4">
      <p className="mb-3 text-xs font-medium tracking-wider text-muted-foreground uppercase">Upload Report</p>

      <AnimatePresence mode="wait">
        {phase === "idle" && (
          <motion.div
            key="idle"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onDragOver={(event) => {
              event.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setIsDragging(false);
              const file = event.dataTransfer.files?.[0];
              startUpload(file?.name ?? "document.pdf");
            }}
            onClick={() => inputRef.current?.click()}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors",
              isDragging ? "border-primary bg-primary/5" : "border-border hover:border-border/80 hover:bg-accent/30"
            )}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,.docx,.csv"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) startUpload(file.name);
              }}
            />
            <div className="flex size-11 items-center justify-center rounded-full bg-primary/10 text-primary">
              <UploadCloud className="size-5" />
            </div>
            <div>
              <p className="text-sm font-medium">Drag &amp; drop a report, or click to browse</p>
              <p className="mt-1 text-xs text-muted-foreground">Simulated pipeline — no file leaves your browser</p>
            </div>
            <div className="flex gap-1.5">
              {SUPPORTED.map((type) => (
                <Badge key={type} variant="secondary" className="text-[10px] font-normal">
                  {type}
                </Badge>
              ))}
            </div>
          </motion.div>
        )}

        {phase === "uploading" && (
          <motion.div
            key="uploading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="space-y-3 py-4"
          >
            <p className="truncate text-sm font-medium">{fileName}</p>
            <Progress value={Math.min(progress, 100)} className="h-1.5" />
            <p className="text-xs text-muted-foreground tabular-nums">{Math.round(Math.min(progress, 100))}% uploaded</p>
          </motion.div>
        )}

        {phase === "processing" && (
          <motion.div key="processing" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <p className="mb-3 truncate text-sm font-medium">{fileName}</p>
            <ProcessingPipeline stages={stages} title="" />
          </motion.div>
        )}

        {phase === "done" && (
          <motion.div
            key="done"
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            className="flex flex-col items-center gap-3 py-6 text-center"
          >
            <div className="flex size-12 items-center justify-center rounded-full bg-success/15 text-success">
              <FileCheck2 className="size-6" />
            </div>
            <div>
              <p className="text-sm font-medium">Indexed successfully</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {fileName} is now searchable across Reports and the Intelligence Graph
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={reset}>
              <RotateCcw /> Upload another
            </Button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
