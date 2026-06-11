"""Tool registry."""

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

TOOLS: dict[str, Tool] = {t.name: t for t in RETRIEVAL_TOOLS}

__all__ = ["Tool", "ToolResult", "TOOLS", "RETRIEVAL_TOOLS", "doc_slugs"]
