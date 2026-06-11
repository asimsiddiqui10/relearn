"""
Map a *normalized* Marker JSON document tree to Spaces records.

Architecture:
    raw Marker JSON
      -> normalize_marker_payload (envelope unwrap, pre-existing)
      -> normalize_marker_tree    (header level snapping, caption pinning, etc.)
      -> map_marker_document_tree (THIS FILE)
      -> persist_mapped_document  (DB writes)

Unified chunk model
-------------------
Every searchable atom becomes a single row in `chunks`. The `images` table is a
metadata sidecar. Search and citation always go through `chunks.id`.

Block-type mapping (chunks.block_type):

    Source (post-normalization)                 chunks row
    -----------------------------------------   ---------------------------------
    SectionHeader / Title                       block_type='SectionHeader'
                                                 - content = heading text
                                                 - structure_node_id = node it titled
                                                 - one matching structure_nodes row created

    Text                                        block_type='Text'
                                                 - content = paragraph text

    ListGroup (regular)                         block_type='ListGroup'
                                                 - content = flattened list items "; "

    ListGroup (TOC, post-normalize)             block_type='TableOfContents'
                                                 - content = flattened items
                                                 - retrievable but normally filtered out

    Table                                       block_type='Table'
                                                 - content = row-major flattened cells
                                                 - content_html keeps the grid

    Equation (native or reclassified)           block_type='Equation'
                                                 - content = latex/plain math text
                                                 - attached_image_id set if reclassified
                                                   from a Figure (so the image bytes can
                                                   still be reached for re-rendering)

    Figure / Picture                            block_type='Image'
                                                 - content = caption + alt + description
                                                 - attached_image_id -> images row with
                                                   filename, bbox, equation_latex (if any)

    Caption (after normalize pins it)           block_type='Caption'
                                                 - content = caption text
                                                 - attached_image_id -> the image it captions

    PageHeader / PageFooter                     SKIPPED unless they survive normalization
                                                 (they only do when carrying chapter/page-#
                                                  text the publisher set inside a header)

The mapper is now a dumb tree walker. All hierarchy fixing has already happened
upstream in `marker_normalize_tree`.
"""

from __future__ import annotations

import html as html_module
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

# ────────────────────────────────────────────────────────────────────────────
# Regex catalogue
# ────────────────────────────────────────────────────────────────────────────

_PAGE_RE = re.compile(r"^/page/(\d+)/")
_H_TAG_RE = re.compile(r"<h([1-6])\b", re.IGNORECASE)
_LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.DOTALL | re.IGNORECASE)
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_TD_RE = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.DOTALL | re.IGNORECASE)
_TAGS_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Side-channel field prefix written by marker_normalize_tree
_NORM = "_norm_"


# ────────────────────────────────────────────────────────────────────────────
# Public dataclasses (consumed by marker_db_loader)
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class MappedStructureNode:
    id: uuid.UUID
    document_id: uuid.UUID
    parent_node_id: uuid.UUID | None
    heading_level: int
    heading_text: str
    node_type: str
    node_order: int
    page_number: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    bbox: list | None = None
    polygon: list | None = None
    marker_block_id: str = ""
    structure_path: str | None = None
    heading_breadcrumb: str | None = None
    numbering_prefix: str | None = None
    normalization_flags: dict[str, Any] | None = None


@dataclass
class MappedChunk:
    id: uuid.UUID
    document_id: uuid.UUID
    structure_node_id: uuid.UUID | None
    section_order_index: int | None
    block_type: str
    content: str                         # the single column searched/embedded
    content_html: str | None
    page_number: int | None
    bbox: list | None
    polygon: list | None
    chunk_order: int
    token_count: int
    structure_path: str | None = None
    heading_breadcrumb: str | None = None
    attached_image_id: uuid.UUID | None = None
    marker_block_id: str = ""


@dataclass
class MappedImage:
    id: uuid.UUID
    document_id: uuid.UUID
    structure_node_id: uuid.UUID | None
    page_number: int | None
    block_type: str                      # 'Figure', 'Picture', or 'Equation'
    caption: str | None
    alt_text: str | None
    image_description: str | None
    image_filename: str | None
    equation_latex: str | None
    bbox: list | None
    polygon: list | None
    metadata_json: dict[str, Any] | None
    structure_path: str | None = None
    heading_breadcrumb: str | None = None
    marker_block_id: str = ""


@dataclass
class MappedDocument:
    structure_nodes: list[MappedStructureNode] = field(default_factory=list)
    chunks: list[MappedChunk] = field(default_factory=list)
    images: list[MappedImage] = field(default_factory=list)


# ────────────────────────────────────────────────────────────────────────────
# Small helpers
# ────────────────────────────────────────────────────────────────────────────

def parse_page_number(block_id: str | None) -> int | None:
    if not block_id or not isinstance(block_id, str):
        return None
    m = _PAGE_RE.match(block_id)
    if not m:
        return None
    return int(m.group(1))


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    text = _TAGS_RE.sub(" ", html)
    text = _WS_RE.sub(" ", text).strip()
    return html_module.unescape(text)


def heading_level_from_html(html: str | None) -> int:
    if not html:
        return 2
    m = _H_TAG_RE.search(html)
    if m:
        return int(m.group(1))
    return 2


def node_type_for_level(level: int) -> str:
    if level <= 1:
        return "chapter"
    if level == 2:
        return "section"
    return "subsection"


def strip_images_recursive(obj: Any) -> Any:
    """Replace base64 image payloads with placeholders for JSONB storage."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k == "images" and isinstance(v, dict):
                out[k] = {
                    ik: "<stripped>" if isinstance(iv, str) and len(iv) > 200 else iv
                    for ik, iv in v.items()
                }
            else:
                out[k] = strip_images_recursive(v)
        return out
    if isinstance(obj, list):
        return [strip_images_recursive(x) for x in obj]
    return obj


def _bbox_from_block(block: dict[str, Any]) -> tuple[list | None, list | None]:
    bbox = block.get("bbox")
    polygon = block.get("polygon")
    if bbox is not None and not isinstance(bbox, list):
        bbox = None
    if polygon is not None and not isinstance(polygon, list):
        polygon = None
    return bbox, polygon


def _get_norm(block: dict[str, Any], key: str, default: Any = None) -> Any:
    return block.get(_NORM + key, default)


def _is_dropped(block: dict[str, Any]) -> bool:
    return bool(_get_norm(block, "drop", False))


def _flatten_list_items(html: str) -> str:
    items = _LI_RE.findall(html or "")
    cleaned = [html_to_text(it) for it in items]
    cleaned = [c for c in cleaned if c]
    return "; ".join(cleaned)


def _flatten_table(html: str) -> str:
    rows = _TR_RE.findall(html or "")
    flat: list[str] = []
    for row in rows:
        cells = _TD_RE.findall(row)
        cells = [html_to_text(c) for c in cells]
        cells = [c for c in cells if c]
        if cells:
            flat.append(" | ".join(cells))
    return "\n".join(flat)


def _image_chunk_content(
    caption: str | None,
    alt: str | None,
    desc: str | None,
    block_type: str,
    page_number: int | None,
) -> str:
    """Best-effort single text payload for an image chunk.

    Order: caption (most authoritative), description (long VLM), alt (short).
    Deduped: substring of an earlier piece is dropped.
    Falls back to a placeholder so the row is still addressable.
    """
    pieces: list[str] = []
    for raw in (caption, desc, alt):
        s = (raw or "").strip()
        if not s:
            continue
        if any(s in p or p in s for p in pieces):
            continue
        pieces.append(s)
    if pieces:
        return "\n".join(pieces)
    return f"[{block_type} on page {page_number}]" if page_number is not None else f"[{block_type}]"


# ────────────────────────────────────────────────────────────────────────────
# Hierarchy resolution helpers
# ────────────────────────────────────────────────────────────────────────────

def _marker_ref_from_hierarchy_value(v: Any) -> str:
    if isinstance(v, str):
        return v.strip()
    if v is None:
        return ""
    return str(v).strip()


def _section_hierarchy_marker_refs_desc(section_hierarchy: dict[str, Any] | None) -> list[str]:
    """Marker block ids in section_hierarchy, deepest level first."""
    if not section_hierarchy or not isinstance(section_hierarchy, dict):
        return []
    pairs: list[tuple[int, str]] = []
    for k, v in section_hierarchy.items():
        try:
            lvl = int(k)
        except (TypeError, ValueError):
            continue
        ref = _marker_ref_from_hierarchy_value(v)
        if ref:
            pairs.append((lvl, ref))
    pairs.sort(key=lambda x: -x[0])
    return [ref for _lvl, ref in pairs]


def _resolve_section_uuid(
    section_hierarchy: dict[str, Any] | None,
    marker_id_to_section_uuid: dict[str, uuid.UUID],
    stack_top_uuid: uuid.UUID | None,
) -> uuid.UUID | None:
    for bid in _section_hierarchy_marker_refs_desc(section_hierarchy):
        u = marker_id_to_section_uuid.get(bid)
        if u is not None:
            return u
    return stack_top_uuid


def _section_order_index(
    section_uuid: uuid.UUID | None,
    node_ids_in_order: list[uuid.UUID],
) -> int | None:
    if section_uuid is None:
        return None
    try:
        return node_ids_in_order.index(section_uuid)
    except ValueError:
        return None


def _merge_page_span(
    spans: dict[uuid.UUID, tuple[int, int]],
    node_id: uuid.UUID,
    page_span: tuple[int, int],
) -> None:
    lo, hi = page_span
    cur = spans.get(node_id)
    if cur is None:
        spans[node_id] = (lo, hi)
        return
    spans[node_id] = (min(cur[0], lo), max(cur[1], hi))


# ────────────────────────────────────────────────────────────────────────────
# Image-uuid pre-pass
# ────────────────────────────────────────────────────────────────────────────

def _allocate_image_uuids(document_root: dict[str, Any]) -> dict[str, uuid.UUID]:
    """Walk the tree once and reserve one image UUID per Figure/Picture (or
    Equation block reclassified from a Figure).

    Reserved separately from the mapping pass so Caption blocks can reference
    the image regardless of document order.
    """
    out: dict[str, uuid.UUID] = {}

    def walk(node: dict[str, Any]) -> None:
        if not isinstance(node, dict):
            return
        bt = node.get("block_type")
        bid = node.get("id")
        keep_image_row = bt in ("Figure", "Picture") or (
            bt == "Equation" and _get_norm(node, "reclassified_from") == "Figure"
        )
        if keep_image_row and isinstance(bid, str) and bid:
            out[bid] = uuid.uuid4()
        for c in (node.get("children") or []):
            if isinstance(c, dict):
                walk(c)

    for top in (document_root.get("children") or []):
        if isinstance(top, dict):
            walk(top)
    return out


# ────────────────────────────────────────────────────────────────────────────
# Main mapping
# ────────────────────────────────────────────────────────────────────────────

def map_marker_document_tree(
    document_root: dict[str, Any],
    document_id: uuid.UUID,
    *,
    document_title: str | None = None,
) -> MappedDocument:
    """Walk a *normalized* Marker page/block tree and produce mapped rows.

    `document_title` is used to label the synthetic root if the document has no
    h1 SectionHeader (so every chunk still has a containing section).
    """
    out = MappedDocument()
    marker_id_to_section_uuid: dict[str, uuid.UUID] = {}
    marker_id_to_image_uuid: dict[str, uuid.UUID] = _allocate_image_uuids(document_root)

    # Stack of (heading_level, structure_uuid)
    header_stack: list[tuple[int, uuid.UUID]] = []
    node_order_counter = [0]
    chunk_order = [0]

    children = document_root.get("children")
    if not isinstance(children, list):
        return out

    # ── section node creation helpers ──────────────────────────────────────

    def _open_section(
        *,
        heading_text: str,
        level: int,
        page_num: int | None,
        bbox: list | None,
        polygon: list | None,
        marker_block_id: str,
        numbering_prefix: str | None,
        normalization_flags: dict[str, Any] | None,
    ) -> uuid.UUID:
        while header_stack and header_stack[-1][0] >= level:
            header_stack.pop()
        parent_uuid = header_stack[-1][1] if header_stack else None
        new_id = uuid.uuid4()
        node = MappedStructureNode(
            id=new_id,
            document_id=document_id,
            parent_node_id=parent_uuid,
            heading_level=level,
            heading_text=heading_text or "(untitled)",
            node_type=node_type_for_level(level),
            node_order=node_order_counter[0],
            page_number=page_num,
            page_start=page_num,
            page_end=page_num,
            bbox=bbox,
            polygon=polygon,
            marker_block_id=marker_block_id,
            numbering_prefix=numbering_prefix,
            normalization_flags=dict(normalization_flags) if normalization_flags else None,
        )
        node_order_counter[0] += 1
        out.structure_nodes.append(node)
        if marker_block_id:
            marker_id_to_section_uuid[marker_block_id] = new_id
        header_stack.append((level, new_id))
        return new_id

    def _ensure_root() -> uuid.UUID:
        """Create a synthetic h1 root using document_title if no header has been
        opened yet. Guarantees every body chunk has a containing section."""
        if header_stack:
            return header_stack[-1][1]
        return _open_section(
            heading_text=(document_title or "(document)").strip() or "(document)",
            level=1,
            page_num=0,
            bbox=None,
            polygon=None,
            marker_block_id="",
            numbering_prefix=None,
            normalization_flags={"synthetic_root": True},
        )

    def _resolve_for_block(section_hierarchy: dict[str, Any] | None) -> uuid.UUID | None:
        """Wrap _resolve_section_uuid so we only invoke `_ensure_root` (which
        mutates state) as a true fallback — never speculatively when the
        hierarchy already resolves to a known section."""
        for bid in _section_hierarchy_marker_refs_desc(section_hierarchy):
            u = marker_id_to_section_uuid.get(bid)
            if u is not None:
                return u
        if header_stack:
            return header_stack[-1][1]
        return _ensure_root()

    # ── chunk emission ─────────────────────────────────────────────────────

    def _emit_chunk(
        *,
        block_type: str,
        content: str,
        content_html: str | None,
        page_number: int | None,
        bbox: list | None,
        polygon: list | None,
        section_uuid: uuid.UUID | None,
        attached_image_id: uuid.UUID | None,
        marker_block_id: str,
    ) -> None:
        if not content and block_type not in ("Image", "Equation"):
            return
        sec_order_idx = _section_order_index(section_uuid, [n.id for n in out.structure_nodes])
        out.chunks.append(
            MappedChunk(
                id=uuid.uuid4(),
                document_id=document_id,
                structure_node_id=section_uuid,
                section_order_index=sec_order_idx,
                block_type=block_type,
                content=content,
                content_html=content_html,
                page_number=page_number,
                bbox=bbox,
                polygon=polygon,
                chunk_order=chunk_order[0],
                token_count=len(content.split()) if content else 0,
                attached_image_id=attached_image_id,
                marker_block_id=marker_block_id,
            )
        )
        chunk_order[0] += 1

    def _emit_image_row(
        *,
        block: dict[str, Any],
        image_uuid: uuid.UUID,
        section_uuid: uuid.UUID | None,
        page_number: int | None,
        caption_text: str | None,
        alt_text: str | None,
        image_description: str | None,
        image_filename: str | None,
        equation_latex: str | None,
    ) -> None:
        bbox, polygon = _bbox_from_block(block)
        bid = str(block.get("id") or "")
        meta: dict[str, Any] = {
            "marker_id": bid,
            "marker_block_type": block.get("block_type"),
        }
        reclass = _get_norm(block, "reclassified_from")
        if reclass:
            meta["reclassified_from"] = reclass
        out.images.append(
            MappedImage(
                id=image_uuid,
                document_id=document_id,
                structure_node_id=section_uuid,
                page_number=page_number,
                block_type=block.get("block_type") or "Figure",
                caption=caption_text,
                alt_text=alt_text,
                image_description=image_description,
                image_filename=image_filename,
                equation_latex=equation_latex,
                bbox=bbox,
                polygon=polygon,
                metadata_json=meta,
                marker_block_id=bid,
            )
        )

    # ── recursive walk ─────────────────────────────────────────────────────

    def visit_block(block: dict[str, Any], page_num: int | None) -> None:
        if not isinstance(block, dict):
            return
        if _is_dropped(block):
            # Still descend, in case a wrapper was dropped but children matter.
            for c in (block.get("children") or []):
                if isinstance(c, dict):
                    visit_block(c, page_num)
            return

        bid = block.get("id")
        bid_str = str(bid).strip() if bid is not None else ""
        bt = block.get("block_type")
        if not isinstance(bt, str):
            bt = "Text"

        pnum = page_num if page_num is not None else parse_page_number(bid_str)
        html = block.get("html")
        html_s = html if isinstance(html, str) else None
        section_hierarchy = block.get("section_hierarchy")
        if section_hierarchy is not None and not isinstance(section_hierarchy, dict):
            section_hierarchy = None
        bbox, polygon = _bbox_from_block(block)

        if bt in ("SectionHeader", "Title"):
            level = heading_level_from_html(html_s)
            heading_text = html_to_text(html_s) or "(untitled)"
            sec_uuid = _open_section(
                heading_text=heading_text,
                level=level,
                page_num=pnum,
                bbox=bbox,
                polygon=polygon,
                marker_block_id=bid_str,
                numbering_prefix=_get_norm(block, "numbering_prefix"),
                normalization_flags=_get_norm(block, "normalization_flags"),
            )
            # Heading also becomes a searchable chunk inside its own section.
            _emit_chunk(
                block_type="SectionHeader",
                content=heading_text,
                content_html=html_s,
                page_number=pnum,
                bbox=bbox,
                polygon=polygon,
                section_uuid=sec_uuid,
                attached_image_id=None,
                marker_block_id=bid_str,
            )

        elif bt in ("Figure", "Picture"):
            section_uuid = _resolve_for_block(section_hierarchy)
            image_uuid = marker_id_to_image_uuid.get(bid_str) or uuid.uuid4()
            alt = _get_norm(block, "figure_alt") or ""
            desc = _get_norm(block, "figure_image_description") or ""
            fname = _get_norm(block, "figure_filename") or ""
            cap_text = _get_norm(block, "caption_text") or ""
            content = _image_chunk_content(cap_text, alt, desc, bt, pnum)
            _emit_image_row(
                block=block,
                image_uuid=image_uuid,
                section_uuid=section_uuid,
                page_number=pnum,
                caption_text=cap_text or None,
                alt_text=alt or None,
                image_description=desc or None,
                image_filename=fname or None,
                equation_latex=None,
            )
            _emit_chunk(
                block_type="Image",
                content=content,
                content_html=html_s,
                page_number=pnum,
                bbox=bbox,
                polygon=polygon,
                section_uuid=section_uuid,
                attached_image_id=image_uuid,
                marker_block_id=bid_str,
            )

        elif bt == "Equation":
            section_uuid = _resolve_for_block(section_hierarchy)
            latex = (_get_norm(block, "equation_latex") or "").strip()
            cap_text = _get_norm(block, "caption_text") or ""
            alt = _get_norm(block, "figure_alt") or ""
            content = latex or html_to_text(html_s) or _image_chunk_content(
                cap_text, alt, _get_norm(block, "figure_image_description"), bt, pnum
            )
            attached_image_uuid: uuid.UUID | None = None
            if _get_norm(block, "reclassified_from") == "Figure":
                attached_image_uuid = marker_id_to_image_uuid.get(bid_str) or uuid.uuid4()
                _emit_image_row(
                    block=block,
                    image_uuid=attached_image_uuid,
                    section_uuid=section_uuid,
                    page_number=pnum,
                    caption_text=cap_text or None,
                    alt_text=alt or None,
                    image_description=_get_norm(block, "figure_image_description"),
                    image_filename=_get_norm(block, "figure_filename"),
                    equation_latex=latex or None,
                )
            _emit_chunk(
                block_type="Equation",
                content=content,
                content_html=html_s,
                page_number=pnum,
                bbox=bbox,
                polygon=polygon,
                section_uuid=section_uuid,
                attached_image_id=attached_image_uuid,
                marker_block_id=bid_str,
            )

        elif bt == "Caption":
            section_uuid = _resolve_for_block(section_hierarchy)
            cap_text = html_to_text(html_s)
            attached_image_uuid = None
            attached_block = _get_norm(block, "attached_image_block_id")
            if attached_block:
                attached_image_uuid = marker_id_to_image_uuid.get(attached_block)
            _emit_chunk(
                block_type="Caption",
                content=cap_text,
                content_html=html_s,
                page_number=pnum,
                bbox=bbox,
                polygon=polygon,
                section_uuid=section_uuid,
                attached_image_id=attached_image_uuid,
                marker_block_id=bid_str,
            )

        elif bt == "ListGroup":
            section_uuid = _resolve_for_block(section_hierarchy)
            content = _flatten_list_items(html_s or "") or html_to_text(html_s)
            _emit_chunk(
                block_type="ListGroup",
                content=content,
                content_html=html_s,
                page_number=pnum,
                bbox=bbox,
                polygon=polygon,
                section_uuid=section_uuid,
                attached_image_id=None,
                marker_block_id=bid_str,
            )

        elif bt == "TableOfContents":
            section_uuid = _resolve_for_block(section_hierarchy)
            content = _flatten_list_items(html_s or "") or html_to_text(html_s)
            _emit_chunk(
                block_type="TableOfContents",
                content=content,
                content_html=html_s,
                page_number=pnum,
                bbox=bbox,
                polygon=polygon,
                section_uuid=section_uuid,
                attached_image_id=None,
                marker_block_id=bid_str,
            )

        elif bt == "Table":
            section_uuid = _resolve_for_block(section_hierarchy)
            content = _flatten_table(html_s or "") or html_to_text(html_s)
            _emit_chunk(
                block_type="Table",
                content=content,
                content_html=html_s,
                page_number=pnum,
                bbox=bbox,
                polygon=polygon,
                section_uuid=section_uuid,
                attached_image_id=None,
                marker_block_id=bid_str,
            )

        elif bt == "Page":
            # Page is a structural container only; its html is the concatenation
            # of every child block's html, so emitting a chunk would duplicate
            # everything beneath it. We still descend into children below.
            pass

        elif bt in ("Text", "Code", "TextInlineMath", "Handwriting", "Footnote", "Form",
                    "PageHeader", "PageFooter"):
            section_uuid = _resolve_for_block(section_hierarchy)
            content = html_to_text(html_s)
            _emit_chunk(
                block_type=bt,
                content=content,
                content_html=html_s,
                page_number=pnum,
                bbox=bbox,
                polygon=polygon,
                section_uuid=section_uuid,
                attached_image_id=None,
                marker_block_id=bid_str,
            )

        else:
            # Unknown block_type: still emit so we don't lose content.
            section_uuid = _resolve_for_block(section_hierarchy)
            content = html_to_text(html_s)
            if content:
                _emit_chunk(
                    block_type=bt,
                    content=content,
                    content_html=html_s,
                    page_number=pnum,
                    bbox=bbox,
                    polygon=polygon,
                    section_uuid=section_uuid,
                    attached_image_id=None,
                    marker_block_id=bid_str,
                )

        kids = block.get("children")
        if isinstance(kids, list):
            for child in kids:
                if isinstance(child, dict):
                    visit_block(child, pnum)

    for page in children:
        if not isinstance(page, dict):
            continue
        pnum = parse_page_number(page.get("id") if isinstance(page.get("id"), str) else "")
        visit_block(page, pnum)

    # ── Roll page spans up to ancestors ────────────────────────────────────
    section_pages: dict[uuid.UUID, tuple[int, int]] = {}
    for c in out.chunks:
        if c.structure_node_id is not None and c.page_number is not None:
            _merge_page_span(section_pages, c.structure_node_id, (c.page_number, c.page_number))
    for im in out.images:
        if im.structure_node_id is not None and im.page_number is not None:
            _merge_page_span(section_pages, im.structure_node_id, (im.page_number, im.page_number))

    parent_by_id = {n.id: n.parent_node_id for n in out.structure_nodes}
    for n in reversed(out.structure_nodes):
        pr = section_pages.get(n.id)
        if pr and n.parent_node_id is not None and n.parent_node_id in parent_by_id:
            _merge_page_span(section_pages, n.parent_node_id, pr)

    for n in out.structure_nodes:
        pr = section_pages.get(n.id)
        if pr:
            n.page_start, n.page_end = pr

    # ── structure_path / breadcrumb on every node and propagate to chunks ──
    node_by_id = {n.id: n for n in out.structure_nodes}
    for n in out.structure_nodes:
        path_parts: list[str] = []
        breadcrumb_parts: list[str] = []
        current = n
        while current is not None:
            path_parts.append(str(current.id))
            breadcrumb_parts.append(current.heading_text)
            current = node_by_id.get(current.parent_node_id) if current.parent_node_id else None
        path_parts.reverse()
        breadcrumb_parts.reverse()
        n.structure_path = "/" + "/".join(path_parts)
        n.heading_breadcrumb = " > ".join(breadcrumb_parts)

    for c in out.chunks:
        if c.structure_node_id and c.structure_node_id in node_by_id:
            parent = node_by_id[c.structure_node_id]
            c.structure_path = parent.structure_path
            c.heading_breadcrumb = parent.heading_breadcrumb
    for im in out.images:
        if im.structure_node_id and im.structure_node_id in node_by_id:
            parent = node_by_id[im.structure_node_id]
            im.structure_path = parent.structure_path
            im.heading_breadcrumb = parent.heading_breadcrumb

    return out


# ────────────────────────────────────────────────────────────────────────────
# Disk JSON shape (kept stable for backend artefact files)
# ────────────────────────────────────────────────────────────────────────────

def mapped_chunks_for_disk_json(mapped: MappedDocument) -> list[dict[str, Any]]:
    return [
        {
            "id": str(c.id),
            "block_type": c.block_type,
            "text": c.content,
            "content_html": c.content_html,
            "page_number": c.page_number,
            "bbox": c.bbox,
            "polygon": c.polygon,
            "chunk_order": c.chunk_order,
            "structure_node_id": str(c.structure_node_id) if c.structure_node_id else None,
            "attached_image_id": str(c.attached_image_id) if c.attached_image_id else None,
            "strategy": "marker_json_tree",
            "word_count": c.token_count,
        }
        for c in mapped.chunks
    ]
