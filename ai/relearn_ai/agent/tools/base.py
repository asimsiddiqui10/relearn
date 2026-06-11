"""Tool framework (spec/03, spec/04).

Each tool: a Pydantic args model (JSON schema auto-generated for the LLM), a
deterministic `label()` (shown while running) and `summarize()` (shown on
completion) — zero-latency, zero-cost narration, never an LLM in the loop.
Tools that touch the corpus get the RunContext server-side; scope is enforced
in SQL, never trusted to the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from relearn_ai.agent.evidence import RunContext


@dataclass
class ToolResult:
    payload: dict  # full result fed back to the model as the tool message
    summary: str  # deterministic one-liner for the tool_result SSE event
    new_evidence: list[str] = field(default_factory=list)  # eids registered this call


class Tool:
    """Base class. Subclasses set name/description/Args and implement run()."""

    name: ClassVar[str]
    description: ClassVar[str]
    Args: ClassVar[type[BaseModel]]
    requires_user: ClassVar[bool] = False  # suspends the loop (ask_user, save_questions)

    def label(self, args: BaseModel) -> str:  # noqa: ARG002
        return f"Running {self.name}…"

    async def run(
        self, args: BaseModel, ctx: RunContext, db: AsyncSession
    ) -> ToolResult:  # pragma: no cover - abstract
        raise NotImplementedError

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.Args.model_json_schema(),
            },
        }
