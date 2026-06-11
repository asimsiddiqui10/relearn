"use client";

import { use, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Send } from "lucide-react";
import { api } from "@/lib/api";
import type { CitationInfo } from "@/lib/chat-types";
import { useAgentChat } from "@/hooks/useAgentChat";
import { AssistantMessageView } from "@/components/chat/AssistantMessageView";
import { EvidencePanel } from "@/components/chat/EvidencePanel";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

export default function ChatPage({ params }: { params: Promise<{ id: string; sid: string }> }) {
  const { id, sid } = use(params);
  const router = useRouter();
  const { turns, busy, send, seed } = useAgentChat(sid);
  const [input, setInput] = useState("");
  const [cite, setCite] = useState<{ c: CitationInfo; nonce: number } | null>(null);
  const [ready, setReady] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .listChatMessages(sid)
      .then((rows) => seed(rows))
      .finally(() => setReady(true));
  }, [sid, seed]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  function onSend(e: React.FormEvent) {
    e.preventDefault();
    const msg = input.trim();
    if (!msg || busy) return;
    setInput("");
    send(msg);
  }

  function openCitation(c: CitationInfo) {
    setCite((prev) => ({ c, nonce: (prev?.nonce ?? 0) + 1 }));
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-4">
        <Button variant="ghost" size="icon" onClick={() => router.push(`/spaces/${id}`)}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <span className="text-sm text-muted-foreground">Chat</span>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* chat column */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div ref={scrollRef} className="flex-1 overflow-auto">
            <div className="mx-auto max-w-2xl space-y-6 p-6">
              {!ready ? (
                <div className="flex justify-center py-16">
                  <Spinner className="h-6 w-6 text-muted-foreground" />
                </div>
              ) : turns.length === 0 ? (
                <p className="py-16 text-center text-muted-foreground">
                  Ask anything about this space&apos;s documents. Every claim will cite its source.
                </p>
              ) : (
                turns.map((turn, i) => (
                  <div key={i} className="space-y-3">
                    <div className="flex justify-end">
                      <div className="max-w-[85%] rounded-2xl bg-muted px-4 py-2 text-sm">
                        {turn.user}
                      </div>
                    </div>
                    <AssistantMessageView message={turn.assistant} onCite={openCitation} />
                  </div>
                ))
              )}
            </div>
          </div>

          <form onSubmit={onSend} className="border-t border-border p-4">
            <div className="mx-auto flex max-w-2xl items-end gap-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) onSend(e);
                }}
                placeholder="Ask about your documents…"
                rows={1}
                className="flex-1 resize-none rounded-lg border border-border bg-card px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
              <Button type="submit" size="icon" disabled={busy || !input.trim()}>
                {busy ? <Spinner /> : <Send className="h-4 w-4" />}
              </Button>
            </div>
          </form>
        </div>

        {/* evidence panel */}
        <aside className="hidden w-[44%] shrink-0 border-l border-border lg:block">
          <EvidencePanel
            citation={cite?.c ?? null}
            nonce={cite?.nonce ?? 0}
            onClose={() => setCite(null)}
          />
        </aside>
      </div>
    </div>
  );
}
