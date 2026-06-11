"use client";

import { useRef } from "react";
import { ArrowUp, Square } from "lucide-react";
import { cn } from "@/lib/utils";

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  onStop,
  busy,
  placeholder = "Ask about your documents…",
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  busy: boolean;
  placeholder?: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  function autosize() {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 192) + "px";
  }

  const canSend = value.trim().length > 0 && !busy;

  return (
    <div className="rounded-[20px] border border-border bg-card px-4 pt-3.5 shadow-sm transition-colors focus-within:border-ring/50">
      <textarea
        ref={ref}
        value={value}
        rows={1}
        placeholder={placeholder}
        onChange={(e) => {
          onChange(e.target.value);
          autosize();
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (canSend) onSubmit();
          }
        }}
        className="block max-h-48 w-full resize-none overflow-y-auto border-0 bg-transparent p-0 text-sm leading-6 outline-none placeholder:text-muted-foreground"
      />
      <div className="flex items-center justify-between py-2">
        <span className="text-[11px] text-muted-foreground">
          Answers cite their source — click a chip to verify.
        </span>
        {busy && onStop ? (
          <button
            onClick={onStop}
            className="flex h-8 w-8 items-center justify-center rounded-[10px] border border-border bg-card text-foreground transition-all duration-150 hover:bg-accent active:scale-95"
            title="Stop"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
          </button>
        ) : (
          <button
            onClick={() => canSend && onSubmit()}
            disabled={!canSend}
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded-[10px] border border-white/20 text-white transition-all duration-150",
              "bg-gradient-to-b from-neutral-700 to-black active:enabled:scale-95",
              "disabled:cursor-default disabled:from-neutral-400 disabled:to-neutral-500 disabled:opacity-60",
            )}
            title="Send"
          >
            <ArrowUp className="h-4 w-4" strokeWidth={2.5} />
          </button>
        )}
      </div>
    </div>
  );
}
