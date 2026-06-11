import { cn } from "@/lib/utils";
import type { Resource } from "@/lib/types";

const STYLES: Record<Resource["status"], string> = {
  pending: "bg-muted text-muted-foreground",
  ingesting: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300",
  ready: "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300",
  failed: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300",
};

export function StatusBadge({ status, stage }: { status: Resource["status"]; stage?: string | null }) {
  const label = status === "ingesting" && stage ? `${status} · ${stage}` : status;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize",
        STYLES[status],
      )}
    >
      {label}
    </span>
  );
}
