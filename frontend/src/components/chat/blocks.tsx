"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Block } from "@/lib/chat-types";

export function ThinkingBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="font-serif text-sm text-muted-foreground">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 transition-colors hover:text-foreground"
      >
        <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-90")} />
        <span className="italic">Thinking</span>
      </button>
      {open && (
        <p className="mt-1 whitespace-pre-wrap border-l border-border pl-3 leading-relaxed opacity-80">
          {text}
        </p>
      )}
    </div>
  );
}

/** Tool rows read as a quiet timeline: a status dot + the deterministic label,
 *  flipping to the summary + duration when done (MikeOSS working-state feel). */
export function ToolBlock({ block }: { block: Extract<Block, { kind: "tool" }> }) {
  return (
    <div className="flex items-center gap-2.5 py-0.5 text-sm text-muted-foreground">
      <span className="flex size-3.5 shrink-0 items-center justify-center">
        {block.done ? (
          <span className="size-1.5 rounded-full bg-emerald-500" />
        ) : (
          <span className="size-3 animate-spin rounded-full border border-muted-foreground/40 border-t-transparent" />
        )}
      </span>
      <span className="min-w-0 truncate">
        {block.done && block.summary ? block.summary : block.label}
      </span>
      {block.done && block.durationMs != null && (
        <span className="shrink-0 text-xs opacity-50">{(block.durationMs / 1000).toFixed(1)}s</span>
      )}
    </div>
  );
}

export function ConfidenceChip({ level, reason }: { level: string; reason: string }) {
  const tone =
    level === "high"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300"
      : level === "medium"
        ? "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300"
        : "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium",
        tone,
      )}
      title={reason}
    >
      <span className="size-1.5 rounded-full bg-current opacity-70" />
      {level} confidence
    </span>
  );
}
