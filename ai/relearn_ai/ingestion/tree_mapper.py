"""Map a *normalized* Marker tree to DB rows (heuristics ported from v1, spec/02 schema).

    raw Marker JSON
      -> normalize_marker_payload   (envelope unwrap)
      -> normalize_marker_tree      (header snapping, caption pinning, equation reclass)
      -> map_marker_document_tree   (THIS FILE — dumb tree walker)
      -> pipeline persists rows

Unified chunk model: every searchable atom is one `chunks` row; `images` is a
metadata sidecar. chunk_type is the coarse schema category (spec/02):

    Marker block (post-normalization)       chunk_type
    SectionHeader/Title/Text/ListGroup/...  text
    Table                                   table
    Equation (native or reclassified)       equation
    Figure/Picture (caption+alt+desc text)  caption   (+ attached_image_id)
    Caption (when not pinned+dropped)       caption   (+ attached_image_id)
"""

from __future__ import annotations

import html as html_module
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_PAGE_RE = re.compile(r"^/page/(\d+)(?:/|$)")
_H_TAG_RE = re.compile(r"<h([1-6])\b", re.IGNORECASE)
_LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.DOTALL | re.IGNORECASE)
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_TD_RE = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.DOTALL | re.IGNORECASE)
_TAGS_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_FIGURE_REF_RE = re.compile(
    r"\b(figure|fig|table|diagram|chart)\.?\s*(\d+(?:[.\-]\d+)*)", re.IGNORECASE
)

_NORM = "_norm_"  # side-channel fields written by normalize_tree

_CHUNK_TYPE_BY_BLOCK = {
    "Table": "table",
    "Equation": "equation",
    "Caption": "caption",
    "Figure": "caption",
    "Picture": "caption",
}

_tokenizer = None


def _token_count(text: str) -> int:
    global _tokenizer
    if not text:
        return 0
    if _tokenizer is None:
        try:
            import tiktoken

            _tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:  # pragma: no cover — tokenizer download blocked
            _tokenizer = False
    if _tokenizer:
        return len(_tokenizer.encode(text, disallowed_special=()))
    return len(text.split())


# ---------------------------------------------------------------------------
# Output rows
# ---------------------------------------------------------------------------


@dataclass
class MappedStructureNode:
    id: uuid.UUID
    document_id: uuid.UUID
    parent_node_id: uuid.UUID | None
    depth: int
    heading_level: int
    heading_text: str
    node_type: str
    marker_block_id: str
    page_start: int | None = None
    page_end: int | None = None
    structure_path: str | None = None
    heading_breadcrumb: str | None = None
    subtree_chunk_count: int = 0
    subtree_token_count: int = 0
    normalization_flags: dict[str, Any] | None = None
    numbering_prefix: str | None = None  # kept in normalization_flags at persist time


@dataclass
class MappedChunk:
    id: uuid.UUID
    document_id: uuid.UUID
    structure_node_id: uuid.UUID | None
    chunk_type: str
    content: str
    content_html: str | None
    page_number: int | None
    bbox: list | None
    polygon: list | None
    token_count: int
    marker_block_id: str
    chunk_order: int
    structure_path: str | None = None
    heading_breadcrumb: str | None = None
    attached_image_id: uuid.UUID | None = None


@dataclass
class MappedImage:
    id: uuid.UUID
    document_id: uuid.UUID
    structure_node_id: uuid.UUID | None
    page_number: int | None
    bbox: list | None
    caption: str | None
    figure_ref_norm: str | None
    marker_block_id: str
    file_path: str | None = None  # set by the pipeline after byte upload


@dataclass
class MappedDocument:
    structure_nodes: list[MappedStructureNode] = field(default_factory=list)
    chunks: list[MappedChunk] = field(default_factory=list)
    images: list[MappedImage] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Small helpers (ported)
# ---------------------------------------------------------------------------


def parse_page_number(block_id: str | None) -> int | None:
    if not block_id or not isinstance(block_id, str):
        return None
    m = _PAGE_RE.match(block_id)
    return int(m.group(1)) if m else None


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    text = _TAGS_RE.sub(" ", html)
    return html_module.unescape(_WS_RE.sub(" ", text).strip())


def heading_level_from_html(html: str | None) -> int:
    if not html:
        return 2
    m = _H_TAG_RE.search(html)
    return int(m.group(1)) if m else 2


def node_type_for_level(level: int) -> str:
    if level <= 1:
        return "chapter"
    if level == 2:
        return "section"
    return "subsection"


def figure_ref_norm_from_text(*texts: str | None) -> str | None:
    """'Figure 2.1: Mitochondria' → 'figure_2_1' (spec/05)."""
    for t in texts:
        if not t:
            continue
        m = _FIGURE_REF_RE.search(t)
        if m:
            kind = "figure" if m.group(1).lower().startswith("fig") else m.group(1).lower()
            num = re.sub(r"[.\-]", "_", m.group(2))
            return f"{kind}_{num}"
    return None


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
    items = [html_to_text(it) for it in _LI_RE.findall(html or "")]
    return "; ".join(i for i in items if i)


def _flatten_table(html: str) -> str:
    flat: list[str] = []
    for row in _TR_RE.findall(html or ""):
        cells = [html_to_text(c) for c in _TD_RE.findall(row)]
        cells = [c for c in cells if c]
        if cells:
            flat.append(" | ".join(cells))
    return "\n".join(flat)


def _image_chunk_content(
    caption: str | None, alt: str | None, desc: str | None, block_type: str, page: int | None
) -> str:
    """caption (authoritative) > description (VLM) > alt; dedupe substrings."""
    pieces: list[str] = []
    for raw in (caption, desc, alt):
        s = (raw or "").strip()
        if not s or any(s in p or p in s for p in pieces):
            continue
        pieces.append(s)
    if pieces:
        return "\n".join(pieces)
    return f"[{block_type} on page {page}]" if page is not None else f"[{block_type}]"


def _section_hierarchy_refs_desc(section_hierarchy: dict[str, Any] | None) -> list[str]:
    """Marker block ids in section_hierarchy, deepest level first."""
    if not isinstance(section_hierarchy, dict):
        return []
    pairs: list[tuple[int, str]] = []
    for k, v in section_hierarchy.items():
        try:
            lvl = int(k)
        except (TypeError, ValueError):
            continue
        ref = str(v).strip() if v is not None else ""
        if ref:
            pairs.append((lvl, ref))
    pairs.sort(key=lambda x: -x[0])
    return [ref for _lvl, ref in pairs]


def _allocate_image_uuids(document_root: dict[str, Any]) -> dict[str, uuid.UUID]:
    """One image UUID per Figure/Picture (or Figure-reclassified Equation), reserved
    up front so Caption blocks can reference the image regardless of order."""
    out: dict[str, uuid.UUID] = {}

    def walk(node: dict[str, Any]) -> None:
        bt = node.get("block_type")
        bid = node.get("id")
        keep = bt in ("Figure", "Picture") or (
            bt == "Equation" and _get_norm(node, "reclassified_from") == "Figure"
        )
        if keep and isinstance(bid, str) and bid:
            out[bid] = uuid.uuid4()
        for c in node.get("children") or []:
            if isinstance(c, dict):
                walk(c)

    for top in document_root.get("children") or []:
        if isinstance(top, dict):
            walk(top)
    return out


# ---------------------------------------------------------------------------
# Main mapping
# ---------------------------------------------------------------------------


def map_marker_document_tree(
    document_root: dict[str, Any],
    document_id: uuid.UUID,
    *,
    document_title: str | None = None,
) -> MappedDocument:
    out = MappedDocument()
    marker_id_to_section: dict[str, uuid.UUID] = {}
    marker_id_to_image: dict[str, uuid.UUID] = _allocate_image_uuids(document_root)

    header_stack: list[tuple[int, uuid.UUID]] = []  # (heading_level, node_uuid)
    chunk_order = [0]

    children = document_root.get("children")
    if not isinstance(children, list):
        return out

    def _open_section(
        *,
        heading_text: str,
        level: int,
        page_num: int | None,
        marker_block_id: str,
        numbering_prefix: str | None,
        normalization_flags: dict[str, Any] | None,
    ) -> uuid.UUID:
        while header_stack and header_stack[-1][0] >= level:
            header_stack.pop()
        parent_uuid = header_stack[-1][1] if header_stack else None
        parent_depth = 0
        if parent_uuid is not None:
            parent_depth = next(n.depth for n in out.structure_nodes if n.id == parent_uuid)
        new_id = uuid.uuid4()
        out.structure_nodes.append(
            MappedStructureNode(
                id=new_id,
                document_id=document_id,
                parent_node_id=parent_uuid,
                depth=parent_depth + 1,
                heading_level=level,
                heading_text=heading_text or "(untitled)",
                node_type=node_type_for_level(level),
                marker_block_id=marker_block_id,
                page_start=page_num,
                page_end=page_num,
                normalization_flags=dict(normalization_flags) if normalization_flags else None,
                numbering_prefix=numbering_prefix,
            )
        )
        if marker_block_id:
            marker_id_to_section[marker_block_id] = new_id
        header_stack.append((level, new_id))
        return new_id

    def _ensure_root() -> uuid.UUID:
        """Synthetic h1 root when no header has been opened — every chunk gets a section."""
        if header_stack:
            return header_stack[-1][1]
        return _open_section(
            heading_text=(document_title or "(document)").strip() or "(document)",
            level=1,
            page_num=0,
            marker_block_id="",
            numbering_prefix=None,
            normalization_flags={"synthetic_root": True},
        )

    def _resolve_for_block(section_hierarchy: dict[str, Any] | None) -> uuid.UUID:
        for bid in _section_hierarchy_refs_desc(section_hierarchy):
            u = marker_id_to_section.get(bid)
            if u is not None:
                return u
        if header_stack:
            return header_stack[-1][1]
        return _ensure_root()

    def _emit_chunk(
        *,
        chunk_type: str,
        content: str,
        content_html: str | None,
        page_number: int | None,
        bbox: list | None,
        polygon: list | None,
        section_uuid: uuid.UUID | None,
        attached_image_id: uuid.UUID | None,
        marker_block_id: str,
    ) -> None:
        if not content and chunk_type not in ("caption", "equation"):
            return
        out.chunks.append(
            MappedChunk(
                id=uuid.uuid4(),
                document_id=document_id,
                structure_node_id=section_uuid,
                chunk_type=chunk_type,
                content=content,
                content_html=content_html,
                page_number=page_number,
                bbox=bbox,
                polygon=polygon,
                token_count=_token_count(content),
                marker_block_id=marker_block_id,
                chunk_order=chunk_order[0],
                attached_image_id=attached_image_id,
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
    ) -> None:
        bbox, _polygon = _bbox_from_block(block)
        out.images.append(
            MappedImage(
                id=image_uuid,
                document_id=document_id,
                structure_node_id=section_uuid,
                page_number=page_number,
                bbox=bbox,
                caption=caption_text,
                figure_ref_norm=figure_ref_norm_from_text(caption_text, alt_text),
                marker_block_id=str(block.get("id") or ""),
            )
        )

    def visit_block(block: dict[str, Any], page_num: int | None) -> None:
        if not isinstance(block, dict):
            return
        if _is_dropped(block):
            for c in block.get("children") or []:
                if isinstance(c, dict):
                    visit_block(c, page_num)
            return

        bid_str = str(block.get("id") or "").strip()
        bt = block.get("block_type")
        if not isinstance(bt, str):
            bt = "Text"
        pnum = page_num if page_num is not None else parse_page_number(bid_str)
        html_s = block.get("html") if isinstance(block.get("html"), str) else None
        section_hierarchy = block.get("section_hierarchy")
        if not isinstance(section_hierarchy, dict):
            section_hierarchy = None
        bbox, polygon = _bbox_from_block(block)

        if bt in ("SectionHeader", "Title"):
            level = heading_level_from_html(html_s)
            heading_text = html_to_text(html_s) or "(untitled)"
            sec_uuid = _open_section(
                heading_text=heading_text,
                level=level,
                page_num=pnum,
                marker_block_id=bid_str,
                numbering_prefix=_get_norm(block, "numbering_prefix"),
                normalization_flags=_get_norm(block, "normalization_flags"),
            )
            # the heading itself is a searchable chunk inside its own section
            _emit_chunk(
                chunk_type="text",
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
            image_uuid = marker_id_to_image.get(bid_str) or uuid.uuid4()
            alt = _get_norm(block, "figure_alt") or ""
            desc = _get_norm(block, "figure_image_description") or ""
            cap_text = _get_norm(block, "caption_text") or ""
            _emit_image_row(
                block=block,
                image_uuid=image_uuid,
                section_uuid=section_uuid,
                page_number=pnum,
                caption_text=cap_text or None,
                alt_text=alt or None,
            )
            _emit_chunk(
                chunk_type="caption",
                content=_image_chunk_content(cap_text, alt, desc, bt, pnum),
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
                # keep the image row so the equation's bytes stay reachable for re-rendering
                attached_image_uuid = marker_id_to_image.get(bid_str) or uuid.uuid4()
                _emit_image_row(
                    block=block,
                    image_uuid=attached_image_uuid,
                    section_uuid=section_uuid,
                    page_number=pnum,
                    caption_text=cap_text or None,
                    alt_text=alt or None,
                )
            _emit_chunk(
                chunk_type="equation",
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
            # normalize_tree pins+drops captions bound to figures; survivors are standalone
            section_uuid = _resolve_for_block(section_hierarchy)
            attached_block = _get_norm(block, "attached_image_block_id")
            _emit_chunk(
                chunk_type="caption",
                content=html_to_text(html_s),
                content_html=html_s,
                page_number=pnum,
                bbox=bbox,
                polygon=polygon,
                section_uuid=section_uuid,
                attached_image_id=marker_id_to_image.get(attached_block) if attached_block else None,
                marker_block_id=bid_str,
            )

        elif bt == "Table":
            section_uuid = _resolve_for_block(section_hierarchy)
            _emit_chunk(
                chunk_type="table",
                content=_flatten_table(html_s or "") or html_to_text(html_s),
                content_html=html_s,
                page_number=pnum,
                bbox=bbox,
                polygon=polygon,
                section_uuid=section_uuid,
                attached_image_id=None,
                marker_block_id=bid_str,
            )

        elif bt in ("ListGroup", "TableOfContents"):
            section_uuid = _resolve_for_block(section_hierarchy)
            _emit_chunk(
                chunk_type="text",
                content=_flatten_list_items(html_s or "") or html_to_text(html_s),
                content_html=html_s,
                page_number=pnum,
                bbox=bbox,
                polygon=polygon,
                section_uuid=section_uuid,
                attached_image_id=None,
                marker_block_id=bid_str,
            )

        elif bt == "Page":
            # structural container only — its html duplicates every child block
            pass

        else:
            # Text, Code, TextInlineMath, Footnote, surviving PageHeader/Footer,
            # and unknown types: emit as text so content is never lost.
            section_uuid = _resolve_for_block(section_hierarchy)
            content = html_to_text(html_s)
            if content:
                _emit_chunk(
                    chunk_type="text",
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

    _finalize(out)
    return out


def _finalize(out: MappedDocument) -> None:
    """Page spans, subtree rollups, ordinal structure_path, breadcrumbs."""
    node_by_id = {n.id: n for n in out.structure_nodes}

    # page spans: chunks -> own node, then roll up to ancestors
    spans: dict[uuid.UUID, tuple[int, int]] = {}

    def merge_span(node_id: uuid.UUID, lo: int, hi: int) -> None:
        cur = spans.get(node_id)
        spans[node_id] = (lo, hi) if cur is None else (min(cur[0], lo), max(cur[1], hi))

    for c in out.chunks:
        if c.structure_node_id and c.page_number is not None:
            merge_span(c.structure_node_id, c.page_number, c.page_number)
    for n in reversed(out.structure_nodes):
        pr = spans.get(n.id)
        if pr and n.parent_node_id in node_by_id:
            merge_span(n.parent_node_id, *pr)
    for n in out.structure_nodes:
        pr = spans.get(n.id)
        if pr:
            n.page_start, n.page_end = pr

    # subtree chunk/token rollups
    for c in out.chunks:
        node = node_by_id.get(c.structure_node_id)
        while node is not None:
            node.subtree_chunk_count += 1
            node.subtree_token_count += c.token_count
            node = node_by_id.get(node.parent_node_id) if node.parent_node_id else None

    # ordinal structure_path ("1/2.3/4": numbering label when detected, else ordinal)
    child_counter: dict[uuid.UUID | None, int] = {}
    segment: dict[uuid.UUID, str] = {}
    for n in out.structure_nodes:  # document order == creation order
        child_counter[n.parent_node_id] = child_counter.get(n.parent_node_id, 0) + 1
        label = (n.numbering_prefix or "").strip().rstrip(".:)]").lstrip("([")
        segment[n.id] = label if label else str(child_counter[n.parent_node_id])

    for n in out.structure_nodes:
        path_parts: list[str] = []
        crumb_parts: list[str] = []
        cur: MappedStructureNode | None = n
        while cur is not None:
            path_parts.append(segment[cur.id])
            crumb_parts.append(cur.heading_text)
            cur = node_by_id.get(cur.parent_node_id) if cur.parent_node_id else None
        n.structure_path = "/".join(reversed(path_parts))
        n.heading_breadcrumb = " > ".join(reversed(crumb_parts))

    for c in out.chunks:
        parent = node_by_id.get(c.structure_node_id)
        if parent:
            c.structure_path = parent.structure_path
            c.heading_breadcrumb = parent.heading_breadcrumb
