"use client";

import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "@/lib/pdf";
import { Spinner } from "@/components/ui/spinner";

/**
 * A single PDF page: a crisp canvas render (scaled by devicePixelRatio so it
 * never goes blurry on retina) with a highlight overlay painted on top.
 *
 * The overlay is an SVG whose viewBox is the page's *Marker* coordinate space
 * (preserveAspectRatio="none"), so citation bboxes/polygons — which come from
 * Marker — drop in with zero client-side coordinate math. If a page has no
 * Marker dimensions we skip the overlay rather than risk a misplaced box.
 */
export interface Highlight {
  id: string;
  bbox?: [number, number, number, number];
  polygon?: number[][];
  active?: boolean;
}

interface Props {
  doc: PDFDocumentProxy;
  pageNumber: number; // 1-based
  width: number; // target CSS width in px
  markerDims?: [number, number]; // [w, h] in Marker coords for this page
  highlights?: Highlight[];
  visible: boolean; // only paint the canvas when scrolled near (virtualization)
}

export function PdfPage({ doc, pageNumber, width, markerDims, highlights = [], visible }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const taskRef = useRef<{ cancel: () => void; promise: Promise<void> } | null>(null);
  const [aspect, setAspect] = useState<number | null>(null); // h / w
  const [rendered, setRendered] = useState(false);
  const [error, setError] = useState(false);

  // (re)render whenever the width changes — so resizing the panel re-rasterizes
  // at the new size (crisp, never upscaled) and the overlay stays aligned.
  useEffect(() => {
    if (!visible || width === 0) return;
    let cancelled = false;
    (async () => {
      try {
        const page = await doc.getPage(pageNumber);
        const base = page.getViewport({ scale: 1 });
        const viewport = page.getViewport({ scale: width / base.width });
        if (cancelled) return;
        setAspect(viewport.height / viewport.width);

        const canvas = canvasRef.current;
        if (!canvas) return;
        // cancel any in-flight render on this canvas (rapid resize) — otherwise
        // pdf.js throws "cannot use the same canvas during multiple render()".
        taskRef.current?.cancel();

        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * dpr); // backing-store px
        canvas.height = Math.floor(viewport.height * dpr);

        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.scale(dpr, dpr);
        const task = page.render({ canvasContext: ctx, viewport });
        taskRef.current = task;
        await task.promise;
        if (!cancelled) {
          setRendered(true);
          setError(false);
        }
      } catch (e) {
        // resize cancellations are expected — only surface real failures
        if ((e as Error)?.name === "RenderingCancelledException") return;
        if (!cancelled) setError(true);
      }
    })();
    return () => {
      cancelled = true;
      taskRef.current?.cancel();
    };
  }, [doc, pageNumber, width, visible]);

  const height = aspect ? width * aspect : width * 1.294; // US-letter fallback

  return (
    <div
      className="relative mx-auto overflow-hidden rounded-lg border border-border bg-white shadow-sm"
      style={{ width, height }}
    >
      {!rendered && !error && (
        <div className="absolute inset-0 flex items-center justify-center">
          <Spinner className="h-5 w-5 text-muted-foreground" />
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center px-4 text-center text-sm text-destructive">
          Failed to render page {pageNumber}
        </div>
      )}
      {/* CSS fills the container; the backing store is rendered at width·dpr,
          so it scales smoothly during a drag and re-rasterizes crisp after. */}
      <canvas ref={canvasRef} className="block h-full w-full" />

      {markerDims && highlights.length > 0 && (
        <svg
          className="pointer-events-none absolute inset-0 h-full w-full"
          viewBox={`0 0 ${markerDims[0]} ${markerDims[1]}`}
          preserveAspectRatio="none"
        >
          {highlights.map((h) => <HighlightShape key={h.id} h={h} />)}
        </svg>
      )}
    </div>
  );
}

/** Light-yellow highlighter look: soft amber fill, firmer amber edge when active. */
function HighlightShape({ h }: { h: Highlight }) {
  const style: React.CSSProperties = {
    fill: "#fde047", // yellow-300 — the highlighter wash
    fillOpacity: h.active ? 0.38 : 0.2,
    stroke: "#ca8a04", // yellow-700 edge
    strokeOpacity: h.active ? 0.9 : 0.3,
  };
  const cls = h.active ? "cite-pulse" : undefined;

  if (h.polygon && h.polygon.length >= 3) {
    return (
      <polygon
        points={h.polygon.map((p) => p.join(",")).join(" ")}
        style={style}
        strokeWidth={2}
        className={cls}
      />
    );
  }
  if (h.bbox) {
    const [x0, y0, x1, y1] = h.bbox;
    return (
      <rect
        x={x0}
        y={y0}
        width={x1 - x0}
        height={y1 - y0}
        rx={3}
        style={style}
        strokeWidth={2}
        className={cls}
      />
    );
  }
  return null;
}
