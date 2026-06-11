"use client";

import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "@/lib/pdf";
import { Spinner } from "@/components/ui/spinner";

/**
 * One PDF page rendered to canvas at devicePixelRatio (crisp on retina; classic
 * blurry-PDF bug prevented by spec). An absolutely-positioned SVG overlay sits
 * on top in raw Marker coordinates: viewBox = the page's Marker dimensions,
 * preserveAspectRatio="none" — one coordinate space, no client-side conversion.
 *
 * Phase 0 renders no highlights; the overlay scaffolding and the highlights[]
 * prop are here so Phase 1 citation highlighting drops in without restructuring.
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
  width: number; // CSS px target width
  markerDims?: [number, number]; // [w, h] in Marker coords for this page
  highlights?: Highlight[];
  visible: boolean; // virtualization: only render canvas when in view (±1)
}

export function PdfPage({ doc, pageNumber, width, markerDims, highlights = [], visible }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [aspect, setAspect] = useState<number | null>(null); // height / width
  const [rendered, setRendered] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!visible || rendered) return;
    let cancelled = false;

    (async () => {
      try {
        const page = await doc.getPage(pageNumber);
        const baseViewport = page.getViewport({ scale: 1 });
        const scale = width / baseViewport.width;
        const viewport = page.getViewport({ scale });
        if (cancelled) return;

        setAspect(viewport.height / viewport.width);

        const canvas = canvasRef.current;
        if (!canvas) return;
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;

        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.scale(dpr, dpr);
        await page.render({ canvasContext: ctx, viewport }).promise;
        if (!cancelled) setRendered(true);
      } catch {
        if (!cancelled) setError(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [doc, pageNumber, width, visible, rendered]);

  const height = aspect ? width * aspect : width * 1.294; // US-letter fallback

  return (
    <div
      className="relative mx-auto border border-border bg-white shadow-sm"
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
      <canvas ref={canvasRef} className="block" />

      {/* Highlight overlay — drawn in raw Marker coordinates. Disabled when the
          page has no Marker dimensions (degrade: never misplace a highlight). */}
      {markerDims && highlights.length > 0 && (
        <svg
          className="pointer-events-none absolute inset-0 h-full w-full"
          viewBox={`0 0 ${markerDims[0]} ${markerDims[1]}`}
          preserveAspectRatio="none"
        >
          {highlights.map((h) => {
            if (h.polygon && h.polygon.length >= 3) {
              return (
                <polygon
                  key={h.id}
                  points={h.polygon.map((p) => p.join(",")).join(" ")}
                  className={
                    h.active
                      ? "fill-amber-300/40 stroke-amber-500"
                      : "fill-amber-200/20 stroke-amber-400/40"
                  }
                  strokeWidth={2}
                />
              );
            }
            if (h.bbox) {
              const [x0, y0, x1, y1] = h.bbox;
              return (
                <rect
                  key={h.id}
                  x={x0}
                  y={y0}
                  width={x1 - x0}
                  height={y1 - y0}
                  className={
                    h.active
                      ? "fill-amber-300/40 stroke-amber-500"
                      : "fill-amber-200/20 stroke-amber-400/40"
                  }
                  strokeWidth={2}
                />
              );
            }
            return null;
          })}
        </svg>
      )}
    </div>
  );
}
