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
        "mx-0.5 inline-flex translate-y-[-1px] items-center rounded px-1 align-baseline font-sans text-[0.68em] font-semibold tracking-tight transition-colors",
        resolvable
          ? "cursor-pointer bg-brand/12 text-brand hover:bg-brand/22"
          : "cursor-not-allowed bg-destructive/12 text-destructive",
      )}
    >
      {eid}
    </button>
  );
}
