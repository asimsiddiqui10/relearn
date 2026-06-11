"use client";

import { useState } from "react";
import { Check, ChevronRight, Loader2, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Block } from "@/lib/chat-types";

export function ThinkingBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="text-sm text-muted-foreground">
      <button onClick={() => setOpen((v) => !v)} className="flex items-center gap-1 hover:text-foreground">
        <Sparkles className="h-3.5 w-3.5" />
        <span>Thinking</span>
        <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-90")} />
      </button>
      {open && <p className="mt-1 whitespace-pre-wrap pl-5 italic opacity-80">{text}</p>}
    </div>
  );
}

export function ToolBlock({ block }: { block: Extract<Block, { kind: "tool" }> }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      {block.done ? (
        <Check className="h-4 w-4 text-green-600" />
      ) : (
        <Loader2 className="h-4 w-4 animate-spin" />
      )}
      <span>{block.done && block.summary ? block.summary : block.label}</span>
      {block.done && block.durationMs != null && (
        <span className="text-xs opacity-60">{(block.durationMs / 1000).toFixed(1)}s</span>
      )}
    </div>
  );
}

export function ConfidenceChip({ level, reason }: { level: string; reason: string }) {
  const color =
    level === "high"
      ? "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300"
      : level === "medium"
        ? "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
        : "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300";
  return (
    <span
      className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", color)}
      title={reason}
    >
      {level} confidence
    </span>
  );
}
