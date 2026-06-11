"""ask_user — the clarification tool that suspends the loop (spec/03 HITL).

It performs no corpus work; calling it persists run state and emits
clarification_required. The user's reply is fed back as this tool's result on
resume. SCL-as-a-tool, with prompt guidance to prefer answering."""

from __future__ import annotations

from pydantic import BaseModel, Field

from relearn_ai.agent.evidence import RunContext
from relearn_ai.agent.tools.base import Tool, ToolResult
from sqlalchemy.ext.asyncio import AsyncSession


class AskUserArgs(BaseModel):
    question: str = Field(description="A single clarifying question.")
    options: list[str] | None = Field(default=None, description="Optional choices to offer.")


class AskUser(Tool):
    name = "ask_user"
    description = (
        "Ask the user ONE clarifying question — only when ambiguity blocks a correct "
        "answer. Suspends until they reply. Prefer answering when you reasonably can."
    )
    Args = AskUserArgs
    requires_user = True

    def label(self, args: AskUserArgs) -> str:
        return f"Asking: {args.question}"

    async def run(
        self, args: AskUserArgs, ctx: RunContext, db: AsyncSession
    ) -> ToolResult:  # pragma: no cover - never executed; the loop suspends instead
        raise RuntimeError("ask_user suspends the loop; run() must not be called")
