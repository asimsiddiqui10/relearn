import { describe, expect, it } from "vitest";
import { emptyAssistant, reduce } from "./chat-reducer";
import type { AgentEvent } from "./chat-types";

const ev = (e: Partial<AgentEvent> & { type: string }, seq = 0) =>
  ({ seq, ...e }) as AgentEvent;

describe("chat reducer (spec/04 block model)", () => {
  it("merges consecutive text deltas into one TextBlock", () => {
    const a = emptyAssistant();
    reduce(a, ev({ type: "text_delta", text: "Hello " }));
    reduce(a, ev({ type: "text_delta", text: "world" }));
    expect(a.blocks).toHaveLength(1);
    expect(a.blocks[0]).toEqual({ kind: "text", text: "Hello world" });
  });

  it("keeps text and tools in chronological order", () => {
    const a = emptyAssistant();
    reduce(a, ev({ type: "text_delta", text: "Let me check. " }));
    reduce(a, ev({ type: "tool_started", call_id: "c1", tool: "search_chunks", label: "Searching…" }));
    reduce(a, ev({ type: "text_delta", text: "Found it." }));
    expect(a.blocks.map((b) => b.kind)).toEqual(["text", "tool", "text"]);
  });

  it("updates a ToolBlock in place on tool_result", () => {
    const a = emptyAssistant();
    reduce(a, ev({ type: "tool_started", call_id: "c1", tool: "search_chunks", label: "Searching…" }));
    reduce(a, ev({ type: "tool_result", call_id: "c1", tool: "search_chunks", summary: "Found 9 passages", duration_ms: 1200 }));
    expect(a.blocks).toHaveLength(1);
    const block = a.blocks[0];
    expect(block).toMatchObject({ kind: "tool", done: true, summary: "Found 9 passages", durationMs: 1200 });
  });

  it("records citations and confidence; completes the run", () => {
    const a = emptyAssistant();
    reduce(a, ev({ type: "citation_map", map: { E1: { eid: "E1", chunk_id: "x", document_id: "d", page: 0, bbox: null, polygon: null, heading_breadcrumb: "H", used: true } } }));
    reduce(a, ev({ type: "confidence", level: "high", reason: "grounded in 3 passages" }));
    reduce(a, ev({ type: "run_completed", usage: {}, duration_ms: 0, steps: 2 }));
    expect(a.citations.E1.used).toBe(true);
    expect(a.confidence).toEqual({ level: "high", reason: "grounded in 3 passages" });
    expect(a.steps).toBe(2);
    expect(a.running).toBe(false);
  });

  it("renders a clarification card and pauses the run", () => {
    const a = emptyAssistant();
    reduce(a, ev({ type: "clarification_required", call_id: "c1", question: "Which chapter?", options: ["1", "2"] }));
    expect(a.blocks[0]).toMatchObject({ kind: "clarification", question: "Which chapter?" });
    expect(a.running).toBe(false);
  });
});
