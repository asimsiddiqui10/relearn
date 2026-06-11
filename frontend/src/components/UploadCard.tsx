"use client";

import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import { api } from "@/lib/api";
import type { DocType } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

const DOC_TYPES: { value: DocType; label: string }[] = [
  { value: "textbook", label: "Textbook" },
  { value: "notes", label: "Notes" },
  { value: "question_paper", label: "Question paper" },
  { value: "slides", label: "Slides" },
];

export function UploadCard({ spaceId, onUploaded }: { spaceId: string; onUploaded: () => void }) {
  const [docType, setDocType] = useState<DocType>("textbook");
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    setError(null);
    setBusy(true);
    try {
      await api.uploadResource(spaceId, file, docType);
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        const f = e.dataTransfer.files?.[0];
        if (f && f.type === "application/pdf") upload(f);
      }}
      className={cn(
        "flex flex-wrap items-center gap-3 rounded-xl border border-dashed bg-card/50 px-4 py-3.5 transition-colors",
        drag ? "border-brand bg-brand/5" : "border-border",
      )}
    >
      <select
        value={docType}
        onChange={(e) => setDocType(e.target.value as DocType)}
        className="h-9 rounded-md border border-input bg-card px-3 text-sm shadow-xs outline-none focus-visible:ring-[3px] focus-visible:ring-ring/35"
      >
        {DOC_TYPES.map((t) => (
          <option key={t.value} value={t.value}>
            {t.label}
          </option>
        ))}
      </select>
      <input
        ref={fileRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) upload(f);
        }}
      />
      <Button variant="outline" onClick={() => fileRef.current?.click()} disabled={busy}>
        {busy ? <Spinner /> : <Upload className="h-4 w-4" />}
        {busy ? "Uploading…" : "Upload PDF"}
      </Button>
      <span className="text-xs text-muted-foreground">or drop a PDF here</span>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </div>
  );
}
