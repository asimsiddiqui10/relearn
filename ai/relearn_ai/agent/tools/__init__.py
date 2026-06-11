"""Tool registry."""

from relearn_ai.agent.tools.ask_user import AskUser
from relearn_ai.agent.tools.base import Tool, ToolResult
from relearn_ai.agent.tools.retrieval_tools import (
    ExpandChunk,
    GetImages,
    GetToc,
    ReadSection,
    SearchChunks,
    doc_slugs,
)

RETRIEVAL_TOOLS: list[Tool] = [
    SearchChunks(),
    GetToc(),
    ReadSection(),
    ExpandChunk(),
    GetImages(),
]

# the agent's full v1 tool set (spec/03)
ALL_TOOLS: list[Tool] = [*RETRIEVAL_TOOLS, AskUser()]

TOOLS: dict[str, Tool] = {t.name: t for t in ALL_TOOLS}

__all__ = ["Tool", "ToolResult", "TOOLS", "ALL_TOOLS", "RETRIEVAL_TOOLS", "doc_slugs"]
