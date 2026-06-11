"""Normalize Marker API responses vs raw document JSON trees."""

from __future__ import annotations

from typing import Any

# Bump when mapping logic changes (stored on marker_ingest_runs for reprocessing).
# v3 (2026-04): unified chunk model; every searchable atom is a `chunks` row.
#               Adds marker_normalize_tree pre-pass (header snapping, caption pinning,
#               equation reclassification, TOC detection, cross-page hierarchy repair).
MARKER_INGEST_PARSER_VERSION = "3"


def normalize_marker_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """
    Return (document_root, envelope).

    Hosted APIs often wrap the tree as {"success", "filename", "json": {...}, ...}.
    Local / CLI output may be the document object directly (block_type Document or children list).
    """
    if not isinstance(payload, dict):
        raise TypeError("marker payload must be a dict")

    inner = payload.get("json")
    if isinstance(inner, dict) and (
        inner.get("block_type") == "Document" or "children" in inner or inner.get("metadata") is not None
    ):
        envelope = {k: v for k, v in payload.items() if k != "json"}
        return inner, envelope

    if "children" in payload or payload.get("block_type") == "Document":
        return payload, None

    raise ValueError(
        "Unrecognized Marker payload shape: expected top-level 'json' document or Document-shaped dict"
    )


def document_metadata_for_db(document_root: dict[str, Any]) -> dict[str, Any] | None:
    """Extract Marker document metadata (e.g. table_of_contents, page_stats) for documents.metadata_json."""
    meta = document_root.get("metadata")
    return meta if isinstance(meta, dict) else None
