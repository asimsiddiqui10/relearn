"use client";

import type { AssistantMessage, CitationInfo } from "@/lib/chat-types";
import { TextBlock } from "./TextBlock";
import { ThinkingBlock, ToolBlock, ConfidenceChip } from "./blocks";
import { Spinner } from "@/components/ui/spinner";

export function AssistantMessageView({
  message,
  onCite,
}: {
  message: AssistantMessage;
  onCite: (c: CitationInfo) => void;
}) {
  return (
    <div className="space-y-2">
      {message.blocks.map((block, i) => {
        if (block.kind === "thinking") return <ThinkingBlock key={i} text={block.text} />;
        if (block.kind === "tool") return <ToolBlock key={i} block={block} />;
        if (block.kind === "text")
          return (
            <TextBlock key={i} text={block.text} citations={message.citations} onCite={onCite} />
          );
        if (block.kind === "clarification")
          return (
            <div key={i} className="rounded-lg border border-accent/40 bg-accent/5 p-3 text-sm">
              <p className="font-medium">{block.question}</p>
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
        <Spinner className="h-4 w-4 text-muted-foreground" />
      )}

      {!message.running && message.confidence && (
        <div className="flex items-center gap-2 pt-1">
          <ConfidenceChip level={message.confidence.level} reason={message.confidence.reason} />
          {message.steps != null && (
            <span className="text-xs text-muted-foreground">
              Worked through {message.steps} step{message.steps === 1 ? "" : "s"}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
