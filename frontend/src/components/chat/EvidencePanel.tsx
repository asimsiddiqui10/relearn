"use client";

import { useEffect, useState } from "react";
import { FileText, X } from "lucide-react";
import { api } from "@/lib/api";
import type { DocumentMeta } from "@/lib/types";
import type { CitationInfo } from "@/lib/chat-types";
import { DocumentVisualizer } from "@/components/visualizer/DocumentVisualizer";
import type { Highlight } from "@/components/visualizer/PdfPage";
import { Spinner } from "@/components/ui/spinner";

/** Inner content of the resizable evidence panel: loads the cited document,
 *  jumps to the page, pulses the bbox in raw Marker coords. */
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
    if (!citation || citation.document_id === docId) return;
    setLoading(true);
    api
      .getDocument(citation.document_id)
      .then((m) => {
        setMeta(m);
        setDocId(citation.document_id);
      })
      .finally(() => setLoading(false));
  }, [citation, docId]);

  const page1 = (citation?.page ?? 0) + 1;
  const highlights: Record<number, Highlight[]> = citation
    ? {
        [page1]: [
          {
            id: citation.eid,
            bbox: citation.bbox as [number, number, number, number] | undefined,
            polygon: citation.polygon ?? undefined,
            active: true,
          },
        ],
      }
    : {};

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-3">
        <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          {citation?.heading_breadcrumb ?? "Source"}
          {citation && <span className="text-foreground/50"> · p.{page1}</span>}
        </span>
        <button
          onClick={onClose}
          className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          title="Close"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1">
        {!citation ? (
          <div className="flex h-full items-center justify-center px-6 text-center text-sm text-muted-foreground">
            Click a citation to see its source.
          </div>
        ) : loading || !meta ? (
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
