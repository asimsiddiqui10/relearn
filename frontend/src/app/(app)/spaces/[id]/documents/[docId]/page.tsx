"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import type { DocumentMeta, StructureNode } from "@/lib/types";
import { DocumentVisualizer } from "@/components/visualizer/DocumentVisualizer";
import { StructureTree } from "@/components/StructureTree";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

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
  const [jumpPage, setJumpPage] = useState(1);

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
      <div className="flex h-full items-center justify-center">
        <Spinner className="h-6 w-6 text-muted-foreground" />
      </div>
    );
  }
  if (!meta) {
    return <div className="p-8 text-destructive">Document not found.</div>;
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-4">
        <Button variant="ghost" size="icon" onClick={() => router.push(`/spaces/${id}`)}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <span className="text-sm capitalize text-muted-foreground">{meta.doc_type}</span>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="w-64 shrink-0 overflow-auto border-r border-border p-2">
          <h2 className="px-2 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Contents
          </h2>
          <StructureTree nodes={nodes} onJump={setJumpPage} />
        </aside>
        <div className="min-w-0 flex-1">
          <DocumentVisualizer
            key={jumpPage}
            pdfUrl={meta.pdf_url}
            pageDimensions={meta.page_dimensions}
            initialPage={jumpPage}
          />
        </div>
      </div>
    </div>
  );
}
