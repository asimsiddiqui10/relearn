import * as React from "react";
import { cn } from "@/lib/utils";

export function Badge({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium w-fit whitespace-nowrap [&>svg]:size-3",
        className,
      )}
      {...props}
    />
  );
}
