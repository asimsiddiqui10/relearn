"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { api } from "@/lib/api";
import type { DocumentMeta, StructureNode } from "@/lib/types";
import { DocumentVisualizer } from "@/components/visualizer/DocumentVisualizer";
import { StructureTree } from "@/components/StructureTree";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

export default function DocumentPage({
  params,
}: {
  params: Promise<{ id: string; docId: string }>;
}) {
  const { id, docId } = use(params);
  const router = useRouter();
  const [meta, setMeta] = useState<DocumentMeta | null>(null);
  const [nodes, setNodes] = useState<StructureNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [jump, setJump] = useState<{ page: number; nonce: number }>();
  const [tocOpen, setTocOpen] = useState(true);

  useEffect(() => {
    Promise.all([api.getDocument(docId), api.getStructure(docId)])
      .then(([m, n]) => {
        setMeta(m);
        setNodes(n);
      })
      .finally(() => setLoading(false));
  }, [docId]);

  if (loading) {
    return (
      <div className="flex h-dvh items-center justify-center">
        <Spinner className="h-5 w-5 text-muted-foreground" />
      </div>
    );
  }
  if (!meta) return <div className="p-8 text-destructive">Document not found.</div>;

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex h-12 shrink-0 items-center gap-1 px-3">
        <button
          onClick={() => router.push(`/spaces/${id}`)}
          className="flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <button
          onClick={() => setTocOpen((v) => !v)}
          className="flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          title={tocOpen ? "Hide contents" : "Show contents"}
        >
          {tocOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
        </button>
        <span className="ml-1 text-sm capitalize text-muted-foreground">{meta.doc_type}</span>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside
          className={cn(
            "shrink-0 overflow-y-auto border-r border-border p-2 transition-all duration-200",
            tocOpen ? "w-64" : "w-0 overflow-hidden border-r-0 p-0",
          )}
        >
          <h2 className="px-2 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Contents
          </h2>
          <StructureTree nodes={nodes} onJump={(page) => setJump((j) => ({ page, nonce: (j?.nonce ?? 0) + 1 }))} />
        </aside>
        <div className="min-w-0 flex-1">
          <DocumentVisualizer
            pdfUrl={meta.pdf_url}
            pageDimensions={meta.page_dimensions}
            jumpTarget={jump}
          />
        </div>
      </div>
    </div>
  );
}
