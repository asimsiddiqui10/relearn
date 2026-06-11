import { cn } from "@/lib/utils";
import type { Resource } from "@/lib/types";

const STYLES: Record<Resource["status"], string> = {
  pending: "border-border bg-muted text-muted-foreground",
  ingesting: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300",
  ready: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300",
  failed: "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300",
};

export function StatusBadge({
  status,
  stage,
}: {
  status: Resource["status"];
  stage?: string | null;
}) {
  const label = status === "ingesting" && stage ? stage : status;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium capitalize",
        STYLES[status],
      )}
    >
      {(status === "ingesting" || status === "pending") && (
        <span className="size-1.5 animate-pulse rounded-full bg-current" />
      )}
      {label}
    </span>
  );
}
