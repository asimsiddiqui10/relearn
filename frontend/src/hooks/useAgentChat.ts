"use client";

import { useCallback, useRef, useState } from "react";
import { streamChat } from "@/lib/sse";
import { emptyAssistant, reduce } from "@/lib/chat-reducer";
import type { AssistantMessage, ChatMessageRow } from "@/lib/chat-types";

interface Turn {
  user: string;
  assistant: AssistantMessage;
}

/**
 * SSE reducer (spec/04). Reduces the event stream into an ordered list of blocks
 * per assistant message. tool_started appends a ToolBlock keyed by call_id;
 * tool_result updates it in place. text_delta appends to the trailing TextBlock
 * (creating one if the tail isn't text) — so tools and text stay chronological.
 */
export function useAgentChat(sessionId: string) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const seed = useCallback((rows: ChatMessageRow[]) => {
    const out: Turn[] = [];
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      if (row.role === "user") {
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
    }
    setTurns(out);
  }, []);

  const send = useCallback(
    async (message: string) => {
      setBusy(true);
      const idx = turns.length;
      setTurns((t) => [...t, { user: message, assistant: emptyAssistant() }]);

      const patch = (fn: (a: AssistantMessage) => void) =>
        setTurns((t) => {
          const copy = [...t];
          const turn = copy[idx];
          if (!turn) return t;
          const a = { ...turn.assistant, blocks: [...turn.assistant.blocks] };
          fn(a);
          copy[idx] = { ...turn, assistant: a };
          return copy;
        });

      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        for await (const ev of streamChat(sessionId, message, ctrl.signal)) {
          patch((a) => reduce(a, ev));
        }
      } catch (e) {
        patch((a) => {
          a.blocks.push({ kind: "text", text: `\n\n_(error: ${(e as Error).message})_` });
          a.running = false;
        });
      } finally {
        patch((a) => {
          a.running = false;
        });
        setBusy(false);
      }
    },
    [sessionId, turns.length],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  return { turns, busy, send, seed, stop };
}

