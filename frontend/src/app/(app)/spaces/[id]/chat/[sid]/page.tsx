"use client";

import { use, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import type { CitationInfo } from "@/lib/chat-types";
import { useAgentChat } from "@/hooks/useAgentChat";
import { AssistantMessageView } from "@/components/chat/AssistantMessageView";
import { EvidencePanel } from "@/components/chat/EvidencePanel";
import { ChatComposer } from "@/components/chat/ChatComposer";
import { ResizablePanel } from "@/components/ResizablePanel";
import { Spinner } from "@/components/ui/spinner";

export default function ChatPage({ params }: { params: Promise<{ id: string; sid: string }> }) {
  const { id, sid } = use(params);
  const router = useRouter();
  const { turns, busy, send, seed, stop } = useAgentChat(sid);
  const [input, setInput] = useState("");
  const [cite, setCite] = useState<{ c: CitationInfo; nonce: number } | null>(null);
  const [panelW, setPanelW] = useState(520);
  const [ready, setReady] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setReady(false);
    api
      .listChatMessages(sid)
      .then(seed)
      .finally(() => setReady(true));
  }, [sid, seed]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  function submit() {
    const msg = input.trim();
    if (!msg || busy) return;
    setInput("");
    send(msg);
  }

  function openCitation(c: CitationInfo) {
    setCite((prev) => ({ c, nonce: (prev?.nonce ?? 0) + 1 }));
  }

  const panelOpen = cite !== null;

  return (
    <div className="flex h-dvh">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-1 px-3">
          <button
            onClick={() => router.push(`/spaces/${id}`)}
            className="flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-2xl space-y-8 px-6 pb-6">
            {!ready ? (
              <div className="flex justify-center py-20">
                <Spinner className="h-5 w-5 text-muted-foreground" />
              </div>
            ) : turns.length === 0 ? (
              <div className="py-20 text-center">
                <h2 className="mb-2 text-xl">Ask your documents</h2>
                <p className="text-sm text-muted-foreground">
                  Every claim is grounded in your sources — click a citation to verify it.
                </p>
              </div>
            ) : (
              turns.map((turn, i) => (
                <div key={i} className="space-y-3.5">
                  <div className="flex justify-end">
                    <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-muted px-4 py-2.5 text-sm">
                      {turn.user}
                    </div>
                  </div>
                  <AssistantMessageView message={turn.assistant} onCite={openCitation} />
                </div>
              ))
            )}
          </div>
        </div>

        <div className="shrink-0 px-6 pb-5">
          <div className="mx-auto max-w-2xl">
            <ChatComposer
              value={input}
              onChange={setInput}
              onSubmit={submit}
              onStop={stop}
              busy={busy}
            />
          </div>
        </div>
      </div>

      <ResizablePanel open={panelOpen} width={panelW} onWidthChange={setPanelW}>
        <EvidencePanel citation={cite?.c ?? null} nonce={cite?.nonce ?? 0} onClose={() => setCite(null)} />
      </ResizablePanel>
    </div>
  );
}
