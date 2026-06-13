"use client";

import { useState } from "react";
import { ChevronRight, Search, Telescope } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Block } from "@/lib/chat-types";
import { ThinkingBlock } from "./blocks";

type ActivityBlock = Extract<Block, { kind: "thinking" | "tool" }>;

/**
 * The agent's reasoning/tool timeline, rendered as a live "working" box
 * (Claude-Code / Mike feel): a header that narrates current state while the run
 * is in flight, then collapses to a one-line summary you can re-open. Each tool
 * step shows a status dot, its deterministic label (→ summary when done) and
 * duration; evidence found is surfaced as a running count.
 */
export function AgentActivity({
  steps,
  running,
  evidenceCount,
}: {
  steps: ActivityBlock[];
  running: boolean;
  evidenceCount: number;
}) {
  const [open, setOpen] = useState(true);
  // auto-collapse once the run finishes; stays open if the user opened it
  const [touched, setTouched] = useState(false);
  const expanded = touched ? open : running;

  const tools = steps.filter((s): s is Extract<Block, { kind: "tool" }> => s.kind === "tool");
  const doneCount = tools.filter((t) => t.done).length;

  const headline = running
    ? tools.length === 0
      ? "Thinking…"
      : (tools.find((t) => !t.done)?.label ?? "Reading sources…")
    : `Searched ${tools.length} ${tools.length === 1 ? "step" : "steps"}` +
      (evidenceCount > 0 ? ` · ${evidenceCount} passage${evidenceCount === 1 ? "" : "s"}` : "");

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card/40">
      <button
        onClick={() => {
          setTouched(true);
          setOpen((v) => (touched ? !v : !running));
        }}
        className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm transition-colors hover:bg-accent/40"
      >
        <span className="flex size-4 shrink-0 items-center justify-center text-brand">
          {running ? (
            <span className="size-3.5 animate-spin rounded-full border-[1.5px] border-brand/30 border-t-brand" />
          ) : (
            <Telescope className="h-4 w-4" />
          )}
        </span>
        <span className={cn("min-w-0 flex-1 truncate", running ? "text-foreground" : "text-muted-foreground")}>
          {headline}
        </span>
        {running && tools.length > 0 && (
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground/70">
            {doneCount}/{tools.length}
          </span>
        )}
        <ChevronRight
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform",
            expanded && "rotate-90",
          )}
        />
      </button>

      {expanded && steps.length > 0 && (
        <div className="space-y-1.5 border-t border-border/60 px-3 py-2.5">
          {steps.map((block, i) =>
            block.kind === "thinking" ? (
              <ThinkingBlock key={i} text={block.text} />
            ) : (
              <ActivityRow key={i} block={block} />
            ),
          )}
          {evidenceCount > 0 && (
            <div className="flex items-center gap-2.5 pt-0.5 text-sm text-muted-foreground">
              <span className="flex size-3.5 shrink-0 items-center justify-center">
                <Search className="h-3 w-3 text-brand/70" />
              </span>
              <span>
                {evidenceCount} passage{evidenceCount === 1 ? "" : "s"} gathered as evidence
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** One tool step inside the activity box: animated dot → green when done. */
function ActivityRow({ block }: { block: Extract<Block, { kind: "tool" }> }) {
  return (
    <div className="flex items-center gap-2.5 py-0.5 text-sm text-muted-foreground">
      <span className="flex size-3.5 shrink-0 items-center justify-center">
        {block.done ? (
          <span className="size-1.5 rounded-full bg-emerald-500" />
        ) : (
          <span className="size-3 animate-spin rounded-full border border-muted-foreground/40 border-t-transparent" />
        )}
      </span>
      <span className="min-w-0 flex-1 truncate">
        {block.done && block.summary ? block.summary : block.label}
      </span>
      {block.done && block.durationMs != null && (
        <span className="shrink-0 text-xs tabular-nums opacity-50">
          {(block.durationMs / 1000).toFixed(1)}s
        </span>
      )}
    </div>
  );
}
