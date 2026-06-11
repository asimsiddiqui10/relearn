"use client";

import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import { api } from "@/lib/api";
import type { DocType } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";

const DOC_TYPES: { value: DocType; label: string }[] = [
  { value: "textbook", label: "Textbook" },
  { value: "notes", label: "Notes" },
  { value: "question_paper", label: "Question paper" },
  { value: "slides", label: "Slides" },
];

export function UploadCard({ spaceId, onUploaded }: { spaceId: string; onUploaded: () => void }) {
  const [docType, setDocType] = useState<DocType>("textbook");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
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
    <Card>
      <CardContent className="flex flex-wrap items-center gap-3 pt-5">
        <select
          value={docType}
          onChange={(e) => setDocType(e.target.value as DocType)}
          className="h-10 rounded-lg border border-border bg-card px-3 text-sm"
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
          onChange={onFile}
        />
        <Button onClick={() => fileRef.current?.click()} disabled={busy}>
          {busy ? <Spinner /> : <Upload className="h-4 w-4" />}
          {busy ? "Uploading…" : "Upload PDF"}
        </Button>
        {error && <span className="text-sm text-destructive">{error}</span>}
      </CardContent>
    </Card>
  );
}
