"use client";

import { use, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText } from "lucide-react";
import { api } from "@/lib/api";
import type { Resource, Space } from "@/lib/types";
import { UploadCard } from "@/components/UploadCard";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { useIngestStatus } from "@/hooks/useIngestStatus";

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

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="h-6 w-6 text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl p-8">
      <h1 className="mb-1 text-2xl font-serif">{space?.name}</h1>
      {space?.description && <p className="mb-6 text-muted-foreground">{space.description}</p>}

      <div className="mb-6">
        <UploadCard spaceId={id} onUploaded={loadResources} />
      </div>

      <h2 className="mb-3 text-lg">Resources</h2>
      {resources.length === 0 ? (
        <p className="py-8 text-center text-muted-foreground">
          No resources yet. Upload a PDF to get started.
        </p>
      ) : (
        <div className="space-y-2">
          {resources.map((r) => {
            const clickable = r.status === "ready" && r.document_id;
            return (
              <Card
                key={r.id}
                className={clickable ? "cursor-pointer transition-colors hover:border-accent" : ""}
                onClick={() =>
                  clickable && router.push(`/spaces/${id}/documents/${r.document_id}`)
                }
              >
                <CardContent className="flex items-center justify-between py-4">
                  <div className="flex items-center gap-3">
                    <FileText className="h-5 w-5 text-muted-foreground" />
                    <span className="font-medium">{r.title}</span>
                  </div>
                  <StatusBadge status={r.status} stage={stages[r.id]} />
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
