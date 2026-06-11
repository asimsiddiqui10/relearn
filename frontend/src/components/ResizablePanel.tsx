"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * Right-docked panel with a draggable left edge (MikeOSS AssistantSidePanel
 * pattern). Smooth: width is tracked in a ref during drag and committed to
 * state on release-free rAF, body gets a col-resize cursor while dragging.
 */
export function ResizablePanel({
  open,
  width,
  onWidthChange,
  min = 360,
  maxFraction = 0.7,
  children,
}: {
  open: boolean;
  width: number;
  onWidthChange: (w: number) => void;
  min?: number;
  maxFraction?: number;
  children: React.ReactNode;
}) {
  const [dragging, setDragging] = useState(false);
  const frame = useRef<number | null>(null);

  const onDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setDragging(true);
    },
    [],
  );

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      if (frame.current) cancelAnimationFrame(frame.current);
      frame.current = requestAnimationFrame(() => {
        const max = window.innerWidth * maxFraction;
        const next = Math.min(Math.max(window.innerWidth - e.clientX, min), max);
        onWidthChange(next);
      });
    };
    const onUp = () => setDragging(false);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [dragging, min, maxFraction, onWidthChange]);

  return (
    <div
      className={cn(
        "relative shrink-0 overflow-hidden border-l border-border bg-card",
        "shadow-[-4px_0_16px_rgba(0,0,0,0.04)]",
        !dragging && "transition-[width] duration-200 ease-out",
      )}
      style={{ width: open ? width : 0 }}
    >
      {/* drag handle */}
      <div
        onMouseDown={onDown}
        className={cn(
          "absolute left-0 top-0 z-10 h-full w-1.5 -translate-x-1/2 cursor-col-resize",
          "transition-colors hover:bg-brand/40",
          dragging && "bg-brand/60",
        )}
      />
      <div className="h-full" style={{ minWidth: width }}>
        {children}
      </div>
    </div>
  );
}
