"""Evidence registry — the product core (spec/03).

Every retrieval tool returns evidence items; the registry assigns short,
token-cheap ids (E1, E2, …) the model cites as [E#]. The registry is the single
source of truth that resolves a citation back to chunk → page → bbox for the PDF
highlight, and post-generation verification checks every [E#] against it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class EvidenceItem:
    eid: str  # "E1", "E2", … — short, token-cheap
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    page: int | None
    bbox: list | None
    polygon: list | None
    heading_breadcrumb: str | None
    text: str

    def to_payload(self) -> dict:
        return {
            "eid": self.eid,
            "chunk_id": str(self.chunk_id),
            "document_id": str(self.document_id),
            "page": self.page,
            "bbox": self.bbox,
            "polygon": self.polygon,
            "heading_breadcrumb": self.heading_breadcrumb,
        }


class EvidenceRegistry:
    """Per-run registry. Dedupes by chunk_id so the same chunk surfaced by two
    tools keeps one stable eid."""

    def __init__(self) -> None:
        self._by_chunk: dict[uuid.UUID, EvidenceItem] = {}
        self._order: list[str] = []
        self._counter = 0

    def register(
        self,
        *,
        chunk_id: uuid.UUID,
        document_id: uuid.UUID,
        page: int | None,
        bbox: list | None,
        polygon: list | None,
        heading_breadcrumb: str | None,
        text: str,
    ) -> EvidenceItem:
        existing = self._by_chunk.get(chunk_id)
        if existing is not None:
            return existing
        self._counter += 1
        item = EvidenceItem(
            eid=f"E{self._counter}",
            chunk_id=chunk_id,
            document_id=document_id,
            page=page,
            bbox=bbox,
            polygon=polygon,
            heading_breadcrumb=heading_breadcrumb,
            text=text,
        )
        self._by_chunk[chunk_id] = item
        self._order.append(item.eid)
        return item

    def get(self, eid: str) -> EvidenceItem | None:
        for item in self._by_chunk.values():
            if item.eid == eid:
                return item
        return None

    def all(self) -> list[EvidenceItem]:
        index = {item.eid: item for item in self._by_chunk.values()}
        return [index[eid] for eid in self._order]

    def citation_map(self) -> dict[str, dict]:
        """E# → {chunk_id, page, bbox, …} for the citation_map SSE event."""
        return {item.eid: item.to_payload() for item in self.all()}

    def snapshot(self) -> list[dict]:
        """Serializable state for suspend/resume (spec/03)."""
        return [
            {**item.to_payload(), "text": item.text, "_order": i}
            for i, item in enumerate(self.all())
        ]

    @classmethod
    def restore(cls, snapshot: list[dict]) -> EvidenceRegistry:
        reg = cls()
        for entry in sorted(snapshot, key=lambda e: e.get("_order", 0)):
            reg._counter += 1
            item = EvidenceItem(
                eid=entry["eid"],
                chunk_id=uuid.UUID(entry["chunk_id"]),
                document_id=uuid.UUID(entry["document_id"]),
                page=entry.get("page"),
                bbox=entry.get("bbox"),
                polygon=entry.get("polygon"),
                heading_breadcrumb=entry.get("heading_breadcrumb"),
                text=entry.get("text", ""),
            )
            reg._by_chunk[item.chunk_id] = item
            reg._order.append(item.eid)
        return reg


@dataclass
class RunContext:
    """Passed to every tool. Scope (space_id, allowed resource/doc ids) is
    enforced in SQL — never trusted to the model."""

    space_id: uuid.UUID
    document_ids: list[uuid.UUID]  # documents the agent may read (space-scoped)
    registry: EvidenceRegistry = field(default_factory=EvidenceRegistry)
