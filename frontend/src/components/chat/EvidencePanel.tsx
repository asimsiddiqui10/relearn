"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { api } from "@/lib/api";
import type { DocumentMeta } from "@/lib/types";
import type { CitationInfo } from "@/lib/chat-types";
import { DocumentVisualizer } from "@/components/visualizer/DocumentVisualizer";
import type { Highlight } from "@/components/visualizer/PdfPage";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

/** Right pane: opens to a cited document, jumps to the page, pulses the bbox.
 *  This is the Phase-1 payoff of the raw-Marker-coord overlay built in Phase 0. */
export function EvidencePanel({
  citation,
  nonce,
  onClose,
}: {
  citation: CitationInfo | null;
  nonce: number;
  onClose: () => void;
}) {
  const [meta, setMeta] = useState<DocumentMeta | null>(null);
  const [loading, setLoading] = useState(false);
  const [docId, setDocId] = useState<string | null>(null);

  useEffect(() => {
    if (!citation) return;
    if (citation.document_id === docId) return;
    setLoading(true);
    api
      .getDocument(citation.document_id)
      .then((m) => {
        setMeta(m);
        setDocId(citation.document_id);
      })
      .finally(() => setLoading(false));
  }, [citation, docId]);

  if (!citation) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-sm text-muted-foreground">
        Click a citation chip to see its source here.
      </div>
    );
  }

  // citation.page is the Marker (0-based) page number; visualizer pages are 1-based
  const page1 = (citation.page ?? 0) + 1;
  const highlights: Record<number, Highlight[]> = {
    [page1]: [
      {
        id: citation.eid,
        bbox: citation.bbox as [number, number, number, number] | undefined,
        polygon: citation.polygon ?? undefined,
        active: true,
      },
    ],
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-border px-3">
        <span className="truncate text-xs text-muted-foreground">
          {citation.heading_breadcrumb ?? "Source"} · p.{page1}
        </span>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="min-h-0 flex-1">
        {loading || !meta ? (
          <div className="flex h-full items-center justify-center">
            <Spinner className="h-5 w-5 text-muted-foreground" />
          </div>
        ) : (
          <DocumentVisualizer
            pdfUrl={meta.pdf_url}
            pageDimensions={meta.page_dimensions}
            jumpTarget={{ page: page1, nonce }}
            highlights={highlights}
          />
        )}
      </div>
    </div>
  );
}
