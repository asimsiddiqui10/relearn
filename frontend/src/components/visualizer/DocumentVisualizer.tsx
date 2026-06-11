"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { loadPdf, type PDFDocumentProxy } from "@/lib/pdf";
import { PdfPage, type Highlight } from "./PdfPage";
import { Spinner } from "@/components/ui/spinner";

/**
 * Clean-room PDF visualizer (spec/11). Props in, events out — no data fetching
 * inside the component; signed URL + page geometry are passed down.
 *
 * Phase 0: render + virtualized scroll + structure-driven page jumps. The
 * highlights prop and overlay exist but stay empty until Phase 1 citations.
 *
 * State machine: idle → loading → ready → error.
 */
type State = "loading" | "ready" | "error";

interface Props {
  pdfUrl: string;
  pageDimensions: Record<string, [number, number]>; // "0"-based page index → [w,h]
  // a jump request; bump `nonce` to re-trigger a jump to the same page
  jumpTarget?: { page: number; nonce: number };
  highlights?: Record<number, Highlight[]>; // 1-based page → highlights
}

export function DocumentVisualizer({
  pdfUrl,
  pageDimensions,
  jumpTarget,
  highlights = {},
}: Props) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [state, setState] = useState<State>("loading");
  const [numPages, setNumPages] = useState(0);
  const [width, setWidth] = useState(0);
  const [visiblePages, setVisiblePages] = useState<Set<number>>(new Set([1, 2]));

  const scrollRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  // load document
  useEffect(() => {
    let cancelled = false;
    setState("loading");
    loadPdf(pdfUrl)
      .then((d) => {
        if (cancelled) return;
        setDoc(d);
        setNumPages(d.numPages);
        setState("ready");
      })
      .catch(() => !cancelled && setState("error"));
    return () => {
      cancelled = true;
    };
  }, [pdfUrl]);

  // fit-width: track container width, re-layout on resize/rotation (ResizeObserver)
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const measure = () => setWidth(Math.min(el.clientWidth - 32, 900));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [state]);

  // virtualization: render only pages within ±1 of the viewport
  useEffect(() => {
    const root = scrollRef.current;
    if (!root || state !== "ready") return;
    const io = new IntersectionObserver(
      (entries) => {
        setVisiblePages((prev) => {
          const next = new Set(prev);
          for (const e of entries) {
            const p = Number((e.target as HTMLElement).dataset.page);
            if (e.isIntersecting) {
              next.add(p);
              next.add(p - 1);
              next.add(p + 1);
            }
          }
          return next;
        });
      },
      { root, rootMargin: "200px 0px" },
    );
    pageRefs.current.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [state, numPages]);

  // jump to a requested page (structure-tree click). Driven by jumpTarget.nonce
  // so clicking the same heading twice re-scrolls. Deferred to rAF so the scroll
  // runs after the page divs have their real (post-width-measure) heights —
  // otherwise it scrolls before layout settles and lands in the wrong place.
  useEffect(() => {
    if (!jumpTarget || state !== "ready" || width === 0) return;
    const el = pageRefs.current.get(jumpTarget.page);
    if (!el) return;
    const id = requestAnimationFrame(() =>
      el.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
    return () => cancelAnimationFrame(id);
    // width in deps: if the jump arrives before the first measure, re-run once
    // width is known so the scroll still happens.
  }, [jumpTarget?.nonce, jumpTarget?.page, state, width]);

  const pages = useMemo(
    () => Array.from({ length: numPages }, (_, i) => i + 1),
    [numPages],
  );

  if (state === "loading") {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="h-6 w-6 text-muted-foreground" />
      </div>
    );
  }
  if (state === "error") {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-sm text-destructive">
        Could not load this document.
      </div>
    );
  }

  return (
    <div ref={scrollRef} className="h-full overflow-auto bg-muted/30 px-4 py-5">
      <div className="space-y-5">
        {pages.map((p) => (
          <div
            key={p}
            data-page={p}
            ref={(el) => {
              if (el) pageRefs.current.set(p, el);
              else pageRefs.current.delete(p);
            }}
          >
            {width > 0 && doc && (
              <PdfPage
                doc={doc}
                pageNumber={p}
                width={width}
                // page_dimensions is 0-indexed by Marker page number
                markerDims={pageDimensions[String(p - 1)]}
                highlights={highlights[p]}
                visible={visiblePages.has(p)}
              />
            )}
            <div className="mt-1.5 text-center text-[11px] tabular-nums text-muted-foreground/70">
              {p}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
