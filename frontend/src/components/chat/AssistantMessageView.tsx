"use client";

import type { AssistantMessage, Block, CitationInfo } from "@/lib/chat-types";
import { TextBlock } from "./TextBlock";
import { ConfidenceChip } from "./blocks";
import { AgentActivity } from "./AgentActivity";

type ActivityBlock = Extract<Block, { kind: "thinking" | "tool" }>;

/**
 * Renders one assistant turn. Consecutive thinking/tool blocks collapse into a
 * single live "activity" box (Claude-Code style); answer text streams below it;
 * clarifications get their own card. Walking the block list preserves the true
 * chronology even across multiple tool→text rounds.
 */
export function AssistantMessageView({
  message,
  onCite,
}: {
  message: AssistantMessage;
  onCite: (c: CitationInfo) => void;
}) {
  const evidenceCount = Object.keys(message.citations).length;

  // group the block stream into ordered segments
  const segments: ({ type: "activity"; blocks: ActivityBlock[] } | { type: "block"; block: Block })[] =
    [];
  for (const block of message.blocks) {
    if (block.kind === "thinking" || block.kind === "tool") {
      const last = segments[segments.length - 1];
      if (last && last.type === "activity") last.blocks.push(block);
      else segments.push({ type: "activity", blocks: [block] });
    } else {
      segments.push({ type: "block", block });
    }
  }

  const hasText = message.blocks.some((b) => b.kind === "text");

  return (
    <div className="space-y-3">
      {segments.map((seg, i) => {
        if (seg.type === "activity") {
          // the activity box is "running" only while the run is live and no
          // answer text has started yet (so it shows the spinner meaningfully)
          return (
            <AgentActivity
              key={i}
              steps={seg.blocks}
              running={message.running && !hasText}
              evidenceCount={evidenceCount}
            />
          );
        }
        const block = seg.block;
        if (block.kind === "text")
          return (
            <TextBlock key={i} text={block.text} citations={message.citations} onCite={onCite} />
          );
        if (block.kind === "clarification")
          return (
            <div key={i} className="rounded-xl border border-brand/30 bg-brand/5 px-4 py-3 text-sm">
              <p className="font-medium text-foreground">{block.question}</p>
              {block.options.length > 0 && (
                <p className="mt-1 text-muted-foreground">
                  Reply with one of: {block.options.join(", ")}
                </p>
              )}
            </div>
          );
        return null;
      })}

      {/* first-tick state: running but nothing emitted yet */}
      {message.running && message.blocks.length === 0 && (
        <div className="flex items-center gap-2 py-0.5 text-sm text-muted-foreground">
          <span className="size-3 animate-spin rounded-full border border-muted-foreground/40 border-t-transparent" />
          <span className="italic">Working…</span>
        </div>
      )}

      {!message.running && message.confidence && (
        <div className="flex items-center gap-2 pt-1">
          <ConfidenceChip level={message.confidence.level} reason={message.confidence.reason} />
          {message.steps != null && message.steps > 0 && (
            <span className="text-xs text-muted-foreground">
              {message.steps} step{message.steps === 1 ? "" : "s"}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
