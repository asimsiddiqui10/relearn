"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { api } from "@/lib/api";
import type { Space } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";

export default function SpacesPage() {
  const router = useRouter();
  const [spaces, setSpaces] = useState<Space[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  useEffect(() => {
    api
      .listSpaces()
      .then(setSpaces)
      .catch(() => setSpaces([]));
  }, []);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    const space = await api.createSpace(name.trim());
    router.push(`/spaces/${space.id}`);
  }

  return (
    <div className="mx-auto h-dvh max-w-4xl overflow-y-auto px-8 py-10">
      <div className="mb-7 flex items-end justify-between">
        <div>
          <h1 className="text-3xl">Spaces</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Shared, source-grounded workspaces for your study material.
          </p>
        </div>
        <Button onClick={() => setCreating((v) => !v)}>
          <Plus className="h-4 w-4" /> New space
        </Button>
      </div>

      {creating && (
        <form onSubmit={onCreate} className="fade-rise mb-6 flex gap-2">
          <Input
            autoFocus
            placeholder="Space name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Button type="submit">Create</Button>
          <Button type="button" variant="ghost" onClick={() => setCreating(false)}>
            Cancel
          </Button>
        </form>
      )}

      {spaces === null ? (
        <div className="flex justify-center py-20">
          <Spinner className="h-5 w-5 text-muted-foreground" />
        </div>
      ) : spaces.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border py-20 text-center">
          <p className="text-sm text-muted-foreground">
            No spaces yet. Create one to upload your study material.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {spaces.map((s) => (
            <button
              key={s.id}
              onClick={() => router.push(`/spaces/${s.id}`)}
              className="group rounded-xl border border-border bg-card p-5 text-left transition-all hover:border-brand/40 hover:shadow-sm"
            >
              <h3 className="text-lg transition-colors group-hover:text-brand">{s.name}</h3>
              {s.description && (
                <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{s.description}</p>
              )}
              <p className="mt-4 text-xs capitalize text-muted-foreground">{s.role}</p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
