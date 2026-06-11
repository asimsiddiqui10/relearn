"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { api } from "@/lib/api";
import type { Space } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";

export default function SpacesPage() {
  const router = useRouter();
  const [spaces, setSpaces] = useState<Space[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  async function load() {
    setSpaces(await api.listSpaces());
  }

  useEffect(() => {
    load().catch(() => setSpaces([]));
  }, []);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    const space = await api.createSpace(name.trim());
    setName("");
    setCreating(false);
    router.push(`/spaces/${space.id}`);
  }

  return (
    <div className="mx-auto max-w-4xl p-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl">Spaces</h1>
        <Button onClick={() => setCreating((v) => !v)}>
          <Plus className="h-4 w-4" /> New space
        </Button>
      </div>

      {creating && (
        <form onSubmit={onCreate} className="mb-6 flex gap-2">
          <Input
            autoFocus
            placeholder="Space name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Button type="submit">Create</Button>
        </form>
      )}

      {spaces === null ? (
        <div className="flex justify-center py-16">
          <Spinner className="h-6 w-6 text-muted-foreground" />
        </div>
      ) : spaces.length === 0 ? (
        <p className="py-16 text-center text-muted-foreground">
          No spaces yet. Create one to upload your study material.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {spaces.map((s) => (
            <Card
              key={s.id}
              className="cursor-pointer transition-colors hover:border-accent"
              onClick={() => router.push(`/spaces/${s.id}`)}
            >
              <CardContent className="pt-5">
                <CardTitle className="font-serif">{s.name}</CardTitle>
                {s.description && (
                  <p className="mt-1 text-sm text-muted-foreground">{s.description}</p>
                )}
                <p className="mt-3 text-xs text-muted-foreground capitalize">{s.role}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
