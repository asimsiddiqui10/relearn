"use client";

import { cn } from "@/lib/utils";
import type { CitationInfo } from "@/lib/chat-types";

export function CitationChip({
  eid,
  citation,
  onClick,
}: {
  eid: string;
  citation?: CitationInfo;
  onClick?: (c: CitationInfo) => void;
}) {
  const resolvable = !!citation;
  return (
    <button
      type="button"
      disabled={!resolvable}
      onClick={() => citation && onClick?.(citation)}
      title={citation?.heading_breadcrumb ?? (resolvable ? "" : "unresolved citation")}
      className={cn(
        "mx-0.5 inline-flex items-center rounded px-1 align-baseline text-[0.7em] font-medium",
        resolvable
          ? "bg-accent/15 text-accent hover:bg-accent/25 cursor-pointer"
          : "bg-destructive/15 text-destructive cursor-not-allowed",
      )}
    >
      {eid}
    </button>
  );
}
