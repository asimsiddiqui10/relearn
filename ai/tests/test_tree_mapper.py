"""Mapping heuristics: normalize → map produces correct structure/chunks/images."""

import json
import uuid
from pathlib import Path

from relearn_ai.ingestion.marker_payload import normalize_marker_payload
from relearn_ai.ingestion.normalize_tree import normalize_marker_tree
from relearn_ai.ingestion.tree_mapper import figure_ref_norm_from_text, map_marker_document_tree

FIXTURE = Path(__file__).parent / "fixtures" / "marker_sample.json"


def _map():
    payload = json.loads(FIXTURE.read_text())
    root, _ = normalize_marker_payload(payload)
    normalize_marker_tree(root)
    return map_marker_document_tree(root, uuid.uuid4(), document_title="Biology")


def test_structure_tree_shape():
    mapped = _map()
    by_text = {n.heading_text: n for n in mapped.structure_nodes}
    # h1 chapter + two h2 sections
    assert "Chapter 1 Cell Biology" in by_text
    assert "1.1 The Mitochondrion" in by_text
    assert "1.2 Cellular Respiration" in by_text

    chapter = by_text["Chapter 1 Cell Biology"]
    mito = by_text["1.1 The Mitochondrion"]
    assert chapter.depth == 1 and chapter.parent_node_id is None
    assert mito.depth == 2 and mito.parent_node_id == chapter.id
    assert mito.heading_breadcrumb == "Chapter 1 Cell Biology > 1.1 The Mitochondrion"


def test_page_spans_roll_up():
    mapped = _map()
    chapter = next(n for n in mapped.structure_nodes if n.heading_text.startswith("Chapter"))
    # chapter spans both pages because descendants live on page 0 and 1
    assert chapter.page_start == 0
    assert chapter.page_end == 1


def test_caption_pinned_to_figure_no_standalone_chunk():
    mapped = _map()
    # the Caption block is pinned + dropped; its text rides on the image chunk
    caption_chunks = [c for c in mapped.chunks if c.chunk_type == "caption"]
    assert len(caption_chunks) == 1
    img_chunk = caption_chunks[0]
    assert "mitochondrion" in img_chunk.content.lower()
    assert img_chunk.attached_image_id is not None


def test_image_row_and_figure_ref():
    mapped = _map()
    assert len(mapped.images) == 1
    img = mapped.images[0]
    assert img.figure_ref_norm == "figure_1_1"
    assert img.caption and "cristae" in img.caption


def test_equation_and_table_chunks():
    mapped = _map()
    types = {c.chunk_type for c in mapped.chunks}
    assert "equation" in types
    assert "table" in types
    table_chunk = next(c for c in mapped.chunks if c.chunk_type == "table")
    assert "Glycolysis | 2" in table_chunk.content


def test_every_chunk_has_section_and_path():
    mapped = _map()
    assert mapped.chunks
    for c in mapped.chunks:
        assert c.structure_node_id is not None
        assert c.structure_path
        assert c.heading_breadcrumb


def test_subtree_counts():
    mapped = _map()
    chapter = next(n for n in mapped.structure_nodes if n.heading_text.startswith("Chapter"))
    # chapter subtree contains every chunk in the doc
    assert chapter.subtree_chunk_count == len(mapped.chunks)


def test_figure_ref_norm_helper():
    assert figure_ref_norm_from_text("Figure 2.1: Cell") == "figure_2_1"
    assert figure_ref_norm_from_text("Table 3-2 summary") == "table_3_2"
    assert figure_ref_norm_from_text("no ref here") is None
