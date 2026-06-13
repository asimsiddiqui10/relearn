"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { streamChat } from "@/lib/sse";
import { emptyAssistant, reduce } from "@/lib/chat-reducer";
import type { AssistantMessage, ChatMessageRow } from "@/lib/chat-types";

interface Turn {
  user: string;
  assistant: AssistantMessage;
}

function buildHistory(rows: ChatMessageRow[]): Turn[] {
  const out: Turn[] = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    if (row.role !== "user") continue;
    const next = rows[i + 1];
    const assistant = emptyAssistant();
    assistant.running = false;
    if (next && next.role === "assistant") {
      assistant.blocks = [{ kind: "text", text: next.content }];
      assistant.citations = next.citations_json ?? {};
      i++;
    }
    out.push({ user: row.content, assistant });
  }
  return out;
}

/**
 * Chat state, split so streaming can never be clobbered:
 *   - `history`: past turns, loaded once from the DB (seed)
 *   - `live`: the single in-flight turn being streamed
 * `seed` only ever writes `history`, so a slow history load resolving mid-stream
 * can't wipe the live answer (the bug where the reply only showed on refresh).
 */
export function useAgentChat(sessionId: string) {
  const [history, setHistory] = useState<Turn[]>([]);
  const [live, setLive] = useState<Turn | null>(null);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const liveRef = useRef<Turn | null>(null); // mirror, for folding on next send
  const sentRef = useRef(false); // a send happened → don't let seed run anymore

  // reset everything when the session changes (the route reuses this component)
  useEffect(() => {
    abortRef.current?.abort();
    setHistory([]);
    setLive(null);
    setBusy(false);
    liveRef.current = null;
    sentRef.current = false;
  }, [sessionId]);

  const seed = useCallback((rows: ChatMessageRow[]) => {
    if (sentRef.current) return; // never overwrite an active conversation
    setHistory(buildHistory(rows));
  }, []);

  const send = useCallback(
    async (message: string) => {
      sentRef.current = true;
      setBusy(true);
      // fold a previous completed turn into history, then start the new one
      if (liveRef.current) {
        const prev = liveRef.current;
        setHistory((h) => [...h, prev]);
      }
      const turn: Turn = { user: message, assistant: emptyAssistant() };
      liveRef.current = turn;
      setLive(turn);

      const applyLive = (fn: (a: AssistantMessage) => void) =>
        setLive((prev) => {
          if (!prev) return prev;
          const a: AssistantMessage = {
            ...prev.assistant,
            blocks: prev.assistant.blocks.map((b) => ({ ...b })),
            citations: { ...prev.assistant.citations },
          };
          fn(a);
          const next = { ...prev, assistant: a };
          liveRef.current = next;
          return next;
        });

      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        for await (const ev of streamChat(sessionId, message, ctrl.signal)) {
          applyLive((a) => reduce(a, ev));
        }
      } catch (e) {
        applyLive((a) => {
          a.blocks.push({ kind: "text", text: `\n\n_(error: ${(e as Error).message})_` });
        });
      } finally {
        applyLive((a) => {
          a.running = false;
        });
        setBusy(false);
      }
    },
    [sessionId],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const turns = live ? [...history, live] : history;
  return { turns, busy, send, seed, stop };
}
