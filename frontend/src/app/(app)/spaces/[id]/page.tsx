"use client";

import { use, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, MessageSquare } from "lucide-react";
import { api } from "@/lib/api";
import type { Resource, Space } from "@/lib/types";
import { UploadCard } from "@/components/UploadCard";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useIngestStatus } from "@/hooks/useIngestStatus";
import { cn } from "@/lib/utils";

export default function SpacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [space, setSpace] = useState<Space | null>(null);
  const [resources, setResources] = useState<Resource[]>([]);
  const [loading, setLoading] = useState(true);

  const loadResources = useCallback(async () => {
    setResources(await api.listResources(id));
  }, [id]);

  useEffect(() => {
    Promise.all([api.getSpace(id), api.listResources(id)])
      .then(([s, r]) => {
        setSpace(s);
        setResources(r);
      })
      .finally(() => setLoading(false));
  }, [id]);

  const stages = useIngestStatus(id, resources, loadResources);
  const hasReady = resources.some((r) => r.status === "ready");

  async function startChat() {
    const cs = await api.createChatSession(id);
    router.push(`/spaces/${id}/chat/${cs.id}`);
  }

  if (loading) {
    return (
      <div className="flex h-dvh items-center justify-center">
        <Spinner className="h-5 w-5 text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="mx-auto h-dvh max-w-4xl overflow-y-auto px-8 py-10">
      <div className="mb-1 flex items-start justify-between gap-4">
        <h1 className="text-3xl">{space?.name}</h1>
        <Button onClick={startChat} disabled={!hasReady} title={hasReady ? "" : "Add a document first"}>
          <MessageSquare className="h-4 w-4" /> New chat
        </Button>
      </div>
      {space?.description && <p className="mb-6 text-muted-foreground">{space.description}</p>}

      <div className="mb-8 mt-6">
        <UploadCard spaceId={id} onUploaded={loadResources} />
      </div>

      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Resources
      </h2>
      {resources.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          No resources yet — upload a PDF to get started.
        </p>
      ) : (
        <div className="overflow-hidden rounded-xl border border-border">
          {resources.map((r, i) => {
            const clickable = r.status === "ready" && r.document_id;
            return (
              <button
                key={r.id}
                disabled={!clickable}
                onClick={() => clickable && router.push(`/spaces/${id}/documents/${r.document_id}`)}
                className={cn(
                  "flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors",
                  i > 0 && "border-t border-border",
                  clickable ? "hover:bg-accent" : "cursor-default",
                )}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="truncate text-sm font-medium">{r.title}</span>
                </div>
                <StatusBadge status={r.status} stage={stages[r.id]} />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
