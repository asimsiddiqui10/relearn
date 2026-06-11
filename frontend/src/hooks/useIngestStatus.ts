"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Resource } from "@/lib/types";

/**
 * Poll ingest status for resources that aren't terminal yet (spec/01: backend
 * reads job status from the DB; no cross-service sync). Polling is fine for v1;
 * SSE progress is a Phase-1 chat concern, not ingestion.
 */
export function useIngestStatus(spaceId: string, resources: Resource[], onChange: () => void) {
  const [stages, setStages] = useState<Record<string, string | null>>({});
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const pendingIds = resources
    .filter((r) => r.status === "pending" || r.status === "ingesting")
    .map((r) => r.id)
    .join(",");

  useEffect(() => {
    if (!pendingIds) return;
    const ids = pendingIds.split(",");
    let active = true;

    const tick = async () => {
      let anyTerminal = false;
      await Promise.all(
        ids.map(async (id) => {
          try {
            const s = await api.ingestStatus(spaceId, id);
            if (!active) return;
            setStages((prev) => ({ ...prev, [id]: s.stage }));
            if (s.status === "ready" || s.status === "failed") anyTerminal = true;
          } catch {
            /* transient */
          }
        }),
      );
      if (active && anyTerminal) onChangeRef.current();
    };

    const interval = setInterval(tick, 2000);
    tick();
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [spaceId, pendingIds]);

  return stages;
}
