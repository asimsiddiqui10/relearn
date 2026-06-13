import type { AgentEvent, AssistantMessage, Block } from "./chat-types";

export const emptyAssistant = (): AssistantMessage => ({
  blocks: [],
  citations: {},
  running: true,
});

/**
 * Fold one SSE event into an assistant message (spec/04 reducer rules), mutating
 * `a` in place. Pure and self-contained so it can be unit-tested without React.
 */
export function reduce(a: AssistantMessage, ev: AgentEvent): void {
  switch (ev.type) {
    case "thinking_delta": {
      const tail = a.blocks[a.blocks.length - 1];
      if (tail?.kind === "thinking") tail.text += ev.text;
      else a.blocks.push({ kind: "thinking", text: ev.text });
      break;
    }
    case "text_delta": {
      const tail = a.blocks[a.blocks.length - 1];
      if (tail?.kind === "text") tail.text += ev.text;
      else a.blocks.push({ kind: "text", text: ev.text });
      break;
    }
    case "tool_started":
      a.blocks.push({
        kind: "tool",
        callId: ev.call_id,
        tool: ev.tool,
        label: ev.label,
        done: false,
      });
      break;
    case "tool_result": {
      const block = a.blocks.find(
        (b): b is Extract<Block, { kind: "tool" }> =>
          b.kind === "tool" && b.callId === ev.call_id,
      );
      if (block) {
        block.summary = ev.summary;
        block.durationMs = ev.duration_ms;
        block.done = true;
      }
      break;
    }
    case "evidence_added": {
      // resolve [E#] chips live — don't wait for the final citation_map
      const { eid, chunk_id, document_id, page, bbox, polygon, heading_breadcrumb } =
        ev as unknown as {
          eid: string;
          chunk_id: string;
          document_id: string;
          page: number | null;
          bbox: number[] | null;
          polygon: number[][] | null;
          heading_breadcrumb: string | null;
        };
      a.citations = {
        ...a.citations,
        [eid]: { eid, chunk_id, document_id, page, bbox, polygon, heading_breadcrumb },
      };
      break;
    }
    case "clarification_required":
      a.blocks.push({
        kind: "clarification",
        callId: ev.call_id,
        question: ev.question,
        options: ev.options ?? [],
      });
      a.running = false;
      break;
    case "citation_map":
      a.citations = ev.map;
      break;
    case "confidence":
      a.confidence = { level: ev.level, reason: ev.reason };
      break;
    case "run_completed":
      a.steps = ev.steps;
      a.running = false;
      break;
  }
}
