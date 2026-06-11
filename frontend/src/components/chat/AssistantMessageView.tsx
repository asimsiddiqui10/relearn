"use client";

import type { AssistantMessage, CitationInfo } from "@/lib/chat-types";
import { TextBlock } from "./TextBlock";
import { ThinkingBlock, ToolBlock, ConfidenceChip } from "./blocks";

export function AssistantMessageView({
  message,
  onCite,
}: {
  message: AssistantMessage;
  onCite: (c: CitationInfo) => void;
}) {
  // group the leading run of thinking/tool blocks into a quiet timeline rail
  return (
    <div className="space-y-2.5">
      {message.blocks.map((block, i) => {
        if (block.kind === "thinking") return <ThinkingBlock key={i} text={block.text} />;
        if (block.kind === "tool") return <ToolBlock key={i} block={block} />;
        if (block.kind === "text")
          return (
            <TextBlock key={i} text={block.text} citations={message.citations} onCite={onCite} />
          );
        if (block.kind === "clarification")
          return (
            <div
              key={i}
              className="rounded-xl border border-brand/30 bg-brand/5 px-4 py-3 text-sm"
            >
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
