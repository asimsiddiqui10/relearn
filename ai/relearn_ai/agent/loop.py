"""The agent loop (spec/03). No framework: model call → tool calls → results →
repeat, emitting an SSE event for every transition (spec/04). One mechanism
serves clarification/approval/long-running via suspend + resume.

The loop is an async generator of Events. The model streamer and the clock are
injected so the whole thing is testable with a scripted fake model (no API key).
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from relearn_ai.agent import events as ev
from relearn_ai.agent.evidence import RunContext
from relearn_ai.agent.tools import TOOLS, Tool
from relearn_ai.llm.stream import AssistantTurn, Delta, stream_turn

MAX_ITERATIONS = 15
_EID_RE = re.compile(r"\[E\d+\]")
# a paragraph this long with zero citations is flagged 'uncited' (spec/03)
_UNCITED_MIN_WORDS = 25

Streamer = Callable[..., AsyncIterator[Delta]]
Checkpoint = Callable[[dict], Awaitable[None]]


async def default_streamer(messages: list[dict], *, tools: list[dict] | None = None):
    """Production streamer: binds the 'agent' role to stream_turn so the loop's
    streamer contract is just (messages, *, tools) — matching test fakes."""
    async for delta in stream_turn("agent", messages, tools=tools):
        yield delta


def _clock_ms() -> int:
    return int(time.monotonic() * 1000)


def tool_schemas(tools: list[Tool]) -> list[dict]:
    return [t.openai_schema() for t in tools]


async def run_agent(
    messages: list[dict],
    ctx: RunContext,
    db: AsyncSession,
    *,
    tools: list[Tool] | None = None,
    streamer: Streamer = default_streamer,
    model_label: str = "agent",
    checkpoint: Checkpoint | None = None,
    start_seq: int = 0,
) -> AsyncIterator[ev.Event]:
    """Run (or resume) the loop over `messages`. Resume = pass the saved messages
    with the user's clarification already appended as the pending tool's result."""
    tool_list = tools if tools is not None else list(TOOLS.values())
    by_name = {t.name: t for t in tool_list}
    schemas = tool_schemas(tool_list)
    seq = start_seq

    def emit(event: ev.Event) -> ev.Event:
        nonlocal seq
        event.seq = seq
        seq += 1
        return event

    if start_seq == 0:
        yield emit(ev.run_started(str(uuid.uuid4()), model_label))

    final_text = ""
    steps = 0

    for _iteration in range(MAX_ITERATIONS):
        turn = AssistantTurn(text="", thinking="", tool_calls=[])
        text_buf: list[str] = []

        async for delta in streamer(messages, tools=schemas):
            if delta.thinking:
                yield emit(ev.thinking_delta(delta.thinking))
            if delta.text:
                text_buf.append(delta.text)
                yield emit(ev.text_delta(delta.text))
            if delta.done:
                turn = AssistantTurn(
                    text="".join(text_buf), thinking=delta.thinking, tool_calls=delta.tool_calls
                )

        if not turn.tool_calls:
            final_text = turn.text
            break  # final answer produced

        # record the assistant turn (with its tool calls) before executing them —
        # this is exactly the state we persist if a tool suspends.
        messages.append(_assistant_message(turn))

        for call in turn.tool_calls:
            steps += 1
            tool = by_name.get(call.name)
            if tool is None:
                messages.append(_tool_message(call.id, {"error": f"unknown tool {call.name}"}))
                yield emit(ev.tool_result(call.id, call.name, "Unknown tool", 0))
                continue

            # validate args; invalid → error tool-result, let the model adapt
            try:
                args = tool.Args.model_validate(call.arguments)
            except Exception as exc:  # noqa: BLE001
                messages.append(_tool_message(call.id, {"error": f"invalid arguments: {exc}"}))
                yield emit(ev.tool_started(call.id, call.name, f"{call.name} (invalid args)"))
                yield emit(ev.tool_result(call.id, call.name, "Invalid arguments", 0))
                continue

            yield emit(ev.tool_started(call.id, call.name, tool.label(args), call.arguments))

            if tool.requires_user:
                # suspend: persist state, emit the HITL card, stop here.
                state = {
                    "messages": messages,
                    "registry": ctx.registry.snapshot(),
                    "pending": {"call_id": call.id, "tool": call.name, "args": call.arguments},
                    "seq": seq,
                }
                if checkpoint is not None:
                    await checkpoint(state)
                if tool.name == "ask_user":
                    yield emit(
                        ev.clarification_required(
                            call.id, args.question, getattr(args, "options", None)
                        )
                    )
                else:
                    yield emit(ev.approval_required(call.id, tool.name, call.arguments))
                return

            t0 = _clock_ms()
            try:
                result = await tool.run(args, ctx, db)
            except Exception as exc:  # tool failure → model-visible, never a crash
                messages.append(_tool_message(call.id, {"error": f"tool failed: {exc}"}))
                yield emit(ev.tool_result(call.id, call.name, f"Failed: {exc}", _clock_ms() - t0))
                continue

            for eid in result.new_evidence:
                item = ctx.registry.get(eid)
                if item:
                    yield emit(ev.evidence_added({"eid": eid, **item.to_payload()}))
            messages.append(_tool_message(call.id, result.payload))
            yield emit(ev.tool_result(call.id, call.name, result.summary, _clock_ms() - t0))
    else:
        # hit the iteration cap — answer with what we have (spec/03)
        final_text = final_text or "I've reached my step limit. Here's what I found so far."

    # --- finalize: citation verification, confidence, completion ---
    cmap, flags = _verify_citations(final_text, ctx)
    yield emit(ev.citation_map(cmap))
    level, reason = _confidence(ctx, flags)
    yield emit(ev.confidence(level, reason))
    yield emit(ev.run_completed({}, 0, steps))


def _assistant_message(turn: AssistantTurn) -> dict:
    msg: dict = {"role": "assistant", "content": turn.text or None}
    if turn.tool_calls:
        msg["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": c.raw_arguments},
            }
            for c in turn.tool_calls
        ]
    return msg


def _tool_message(call_id: str, payload: dict) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(payload)}


def _verify_citations(text: str, ctx: RunContext) -> tuple[dict, dict]:
    """Post-generation check (spec/03, cheap v1): every [E#] must resolve;
    factual-looking paragraphs with no citation get flagged 'uncited'."""
    cited = set(re.findall(r"\[E(\d+)\]", text))
    cmap = ctx.registry.citation_map()
    flags: dict[str, bool] = {}

    # mark dangling citations (model invented an eid) — they won't be in the map
    for n in cited:
        eid = f"E{n}"
        if eid not in cmap:
            flags.setdefault("has_dangling", True)

    uncited_paras = 0
    for para in (p.strip() for p in text.split("\n\n")):
        words = len(para.split())
        if words >= _UNCITED_MIN_WORDS and not _EID_RE.search(para):
            uncited_paras += 1
    if uncited_paras:
        flags["uncited_paragraphs"] = uncited_paras

    # annotate the map with which eids the answer actually used
    used = {f"E{n}" for n in cited}
    for eid, payload in cmap.items():
        payload["used"] = eid in used
    return cmap, flags


def _confidence(ctx: RunContext, flags: dict) -> tuple[str, str]:
    """Heuristic confidence (spec/03): evidence density + citation health.
    Not a fake number — a level with a reason."""
    n_evidence = len(ctx.registry.all())
    if n_evidence == 0:
        return "low", "no evidence was retrieved"
    if flags.get("has_dangling"):
        return "low", "the answer cited evidence ids that don't resolve"
    if flags.get("uncited_paragraphs"):
        return "medium", "some claims aren't backed by a citation"
    if n_evidence >= 3:
        return "high", f"grounded in {n_evidence} evidence passages"
    return "medium", f"grounded in {n_evidence} evidence passage(s)"
