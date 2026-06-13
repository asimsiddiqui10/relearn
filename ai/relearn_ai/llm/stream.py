"""Streaming completion in one internal format (spec/06 design rule #1).

The agent loop consumes `Delta` items and never sees provider quirks. Tool-call
fragments (OpenAI streams them piecewise by index) are assembled inside the
adapter and surfaced once, as the terminal delta's `tool_calls`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from relearn_ai.llm.registry import ModelConfig, get_registry
from relearn_ai.observability import observe


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict  # parsed; {} if the model emitted invalid JSON

    @property
    def raw_arguments(self) -> str:
        return json.dumps(self.arguments)


@dataclass
class Delta:
    """One streamed increment. `done` marks the terminal delta carrying the
    fully-assembled turn (text, thinking, tool_calls)."""

    thinking: str = ""
    text: str = ""
    done: bool = False
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class AssistantTurn:
    text: str
    thinking: str
    tool_calls: list[ToolCall]


def _openai_client(model: ModelConfig):
    from openai import AsyncOpenAI

    from relearn_ai.llm.client import LLMError

    if not model.api_key:
        raise LLMError(f"model {model.alias!r} needs {model.api_key_env} set — add it to .env")
    return AsyncOpenAI(base_url=model.base_url, api_key=model.api_key)


@observe(name="llm_stream")
async def stream_turn(
    role: str,
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    model_alias: str | None = None,
) -> AsyncIterator[Delta]:
    """Stream one assistant turn for a role. Yields live thinking/text deltas,
    then one terminal Delta(done=True) with the assembled turn."""
    model = get_registry().resolve(role, model_alias)
    client = _openai_client(model)

    kwargs: dict = {"model": model.model_id, "messages": messages, "stream": True}
    if tools:
        kwargs["tools"] = tools

    text_parts: list[str] = []
    thinking_parts: list[str] = []
    # tool calls assembled by streamed index
    tc_acc: dict[int, dict] = {}

    stream = await client.chat.completions.create(**kwargs)
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            thinking_parts.append(reasoning)
            yield Delta(thinking=reasoning)

        if delta.content:
            text_parts.append(delta.content)
            yield Delta(text=delta.content)

        for tc in delta.tool_calls or []:
            # OpenAI streams one tool call per `index`, splitting args across
            # deltas. Gemini's OpenAI-compat layer sends index=None for EVERY
            # call with full args in a single delta — so keying by index alone
            # collapses multiple calls into one slot and concatenates their JSON
            # into garbage. Key by index when present, else by the call id.
            key = tc.index if tc.index is not None else tc.id
            slot = tc_acc.setdefault(key, {"id": "", "name": "", "args": ""})
            if tc.id:
                slot["id"] = tc.id
            if tc.function and tc.function.name:
                slot["name"] = tc.function.name
            if tc.function and tc.function.arguments:
                slot["args"] += tc.function.arguments

    # insertion order preserves the model's tool-call sequence
    tool_calls = [_assemble(slot) for slot in tc_acc.values()]
    yield Delta(
        done=True,
        tool_calls=tool_calls,
    )


def _assemble(slot: dict) -> ToolCall:
    try:
        args = json.loads(slot["args"]) if slot["args"].strip() else {}
    except json.JSONDecodeError:
        args = {}
    return ToolCall(id=slot["id"] or slot["name"], name=slot["name"], arguments=args)
