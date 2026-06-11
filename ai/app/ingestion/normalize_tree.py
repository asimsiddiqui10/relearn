"""
Pre-mapper normalization of the Marker document tree.

Sits between `normalize_marker_payload` (envelope unwrap) and `map_marker_document_tree`
(produces DB rows). Mutates the document tree in-place by attaching `_norm_*` fields
to blocks. The mapper reads those fields; non-mapper consumers can ignore them.

Why a separate stage:
- Marker's section_hierarchy is heuristic and inconsistent (sibling headers at
  different levels, deep sub-headings re-floated to <h3>, missing first item of an
  enumerated series, captions merged with body text, equations stored as Figures
  with empty alt). Doing all the surgery in one place keeps the mapper a dumb tree
  walker and keeps the raw Marker tree usable for re-processing.

What this stage does, in order:
  1. Walk pages -> linearize blocks (preserving children-of-page nesting only).
  2. Drop empty PageHeader / PageFooter blocks.
  3. Bind Caption blocks to their nearest Figure/Picture (same page, vertical proximity).
  4. Parse <img alt>, <div class="img-description">, <img src> from each Figure/Picture
     and attach as `_norm_figure_*`.
  5. Reclassify equation-shaped Figures (math-symbol-dense alt/desc/caption) to Equation
     blocks; attach `_norm_equation_latex`.
  6. Detect numbering prefix on each SectionHeader and snap consecutive same-style
     siblings to the smallest seen heading_level.
  7. Promote a missing first list item ("i. <text>") to a SectionHeader when sibling
     headers ii.. exist at one level.
  8. Demote orphan headers that look like inline labels (e.g. "Mechanism:") so they
     don't outrank their textual parent.
  9. Detect Table-of-Contents ListGroups (numbered "N.M Topic" entries on first page)
     and reclassify as `TableOfContents`.
 10. Attempt to repair `section_hierarchy` continuity across page boundaries.

Bumps the parser version downstream so re-processing picks up new normalizations.

The output is the same nested {Page -> children} tree, with side-channel `_norm_*`
fields on selected blocks, plus a top-level `_norm_meta` dict on the root with stats.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────
# Regex catalogue
# ────────────────────────────────────────────────────────────────────────────

# HTML extraction
_RE_HTAG = re.compile(r"<h([1-6])\b", re.IGNORECASE)
_RE_IMG_ALT = re.compile(r'<img[^>]*\salt="([^"]*)"', re.IGNORECASE)
_RE_IMG_SRC = re.compile(r'<img[^>]*\ssrc="([^"]*)"', re.IGNORECASE)
_RE_IMG_DESC = re.compile(
    r'<div\s+class="img-description"[^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_RE_TAGS = re.compile(r"<[^>]+>")
_RE_WS = re.compile(r"\s+")

# Gate for Pass B demotion: only demote no-prefix headers that clearly look
# like inline labels (trailing colon, or one of a short whitelist of keywords).
# Without this, real section titles ("ATP Synthesis", "P/O ratio") get demoted
# into the wrong parent whenever the previous section happened to end with
# deeper subsections.
_RE_INLINE_LABEL_KEYWORD = re.compile(
    r"^(?:Note|Notes|Mechanism|Summary|Example|Examples|Warning|Remark"
    r"|Tip|Caution|Hint|Definition|Observation)\b[:.]?$",
    re.IGNORECASE,
)


def _looks_like_inline_label(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if t.endswith(":"):
        return True
    return bool(_RE_INLINE_LABEL_KEYWORD.match(t))

# ────────────────────────────────────────────────────────────────────────────
# Heading numbering / labelling
# ────────────────────────────────────────────────────────────────────────────
#
# Single regex that captures the leading "labelish" token of a heading. Allows:
#   - optional word prefix:  Step | Phase | Stage | Part | Chapter | Section
#                            | Appendix | Exercise | Q | Question | § | No.
#   - optional opening bracket:  ( or [
#   - the label itself:      \d+(\.\d+)*  | [A-Za-z]{1,8}
#   - optional closing bracket: ) or ]
#   - optional separator:    . - : ) ] – —
#   - then mandatory whitespace + at least one non-space char (the heading text)
#
# After matching we hand the captures to `_classify_label` which decides the
# numbering style and validates the label. Anything that fails validation
# returns None (so we don't pollute snapping passes with garbage prefixes).
_RE_LEADING_LABEL = re.compile(
    r"""
    ^\s*
    (?:(?P<word>Step|Phase|Stage|Part|Chapter|Section|Appendix
                |Exercise|Question|Q|No\.?|§)\s*)?
    (?P<open>[(\[])?
    (?P<label>\d+(?:\.\d+)*|[A-Za-z]{1,9})
    (?P<close>[)\]])?
    (?P<sep>[.\-:\u2013\u2014]+)?      # one or more punctuation separators (e.g. "Step 4:-")
    \s*
    \S
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Anything in this set requires SOME disambiguator (a separator/bracket/word
# prefix) — otherwise plain headings ("A practical guide", "1980 census")
# would mis-parse as labelled. Dotted is intentionally absent: "14.4.1" is
# self-disambiguating.
_REQUIRES_SEPARATOR = (
    "arabic",
    "alpha_upper",
    "alpha_lower",
    "roman_upper",
    "roman_lower",
)

# TOC item: any leading numeric or word-prefixed label followed by a title.
# We deliberately do NOT match plain "i." / "a." / "A." style labels here —
# those appear constantly in body lists and would over-match.
_RE_TOC_ITEM = re.compile(
    r"^\s*"
    r"(?:"
    r"\d+(?:\.\d+)+\s+\S"                              # multi-segment dotted: 14.1, 1.2.3
    r"|\d+\.\s+[A-Z\u00C0-\u024F]"                     # arabic dot + capitalized title (TOC-shape)
    r"|(?:Chapter|Section|Appendix|Part|Step|Phase)\s+\d"  # word-prefixed
    r")"
)

# Equation-likeness: dense math symbols, arrows, ΔG, kJ/mol, balanced reaction.
_RE_MATH_HINTS = re.compile(
    r"(→|⇌|↔|↦|⟶|\\rightarrow|\\to|\\leftrightarrow|\\Delta\s*G|ΔG|kJ\s*/\s*mol|"
    r"kcal\s*/\s*mol|\\frac|\\sum|\\int|\\sqrt|→{2,}|≈|≠|≤|≥|±|α|β|γ|µ)",
    re.IGNORECASE,
)
_RE_REACTION = re.compile(
    r"\b[A-Z][a-z]?\d{0,2}([A-Z][a-z]?\d{0,2}){1,}\b.*?(\+|→|=|⇌)"
)

# Side-channel field prefix
_NORM = "_norm_"


# ────────────────────────────────────────────────────────────────────────────
# Public entry point
# ────────────────────────────────────────────────────────────────────────────

def normalize_marker_tree(document_root: dict[str, Any]) -> dict[str, Any]:
    """
    In-place normalization of the Marker tree. Returns the same root for chaining.

    Adds these top-level keys to the root:
      _norm_meta: { applied: list[str], counts: { ... } }
    """
    if not isinstance(document_root, dict):
        return document_root

    pages = document_root.get("children")
    if not isinstance(pages, list):
        return document_root

    counts: dict[str, int] = {
        "page_headers_dropped": 0,
        "captions_pinned": 0,
        "figures_with_alt": 0,
        "figures_with_desc": 0,
        "equations_reclassified": 0,
        "headers_snapped": 0,
        "headers_snapped_global": 0,
        "headers_promoted": 0,
        "headers_demoted": 0,
        "captions_dropped_redundant": 0,
        "toc_blocks": 0,
        "section_hierarchy_patched": 0,
    }

    page_blocks_index: list[list[dict[str, Any]]] = []
    for page in pages:
        if not isinstance(page, dict):
            page_blocks_index.append([])
            continue
        page_blocks = [c for c in (page.get("children") or []) if isinstance(c, dict)]
        page_blocks_index.append(page_blocks)

    # 1. Drop empty PageHeader/PageFooter
    for page_blocks in page_blocks_index:
        for b in page_blocks:
            bt = b.get("block_type")
            if bt in ("PageHeader", "PageFooter"):
                if not _plain_text(b.get("html")):
                    _set_norm(b, "drop", True)
                    counts["page_headers_dropped"] += 1

    # 2. Parse Figure/Picture HTML; mark equation candidates
    for page_blocks in page_blocks_index:
        for b in page_blocks:
            bt = b.get("block_type")
            if bt in ("Figure", "Picture"):
                _enrich_figure(b, counts)

    # 3. Bind captions to figures (same page, nearest preceding figure within 80pt)
    for page_blocks in page_blocks_index:
        _bind_captions_on_page(page_blocks, counts)

    # 4. Reclassify equation-shaped Figures to Equation
    for page_blocks in page_blocks_index:
        for b in page_blocks:
            if b.get("block_type") in ("Figure", "Picture") and _looks_like_equation(b):
                _reclassify_as_equation(b, counts)

    # 5. Header-level normalization (across whole document)
    all_headers: list[tuple[int, int, dict[str, Any]]] = []  # (page_idx, block_idx, block)
    for pi, page_blocks in enumerate(page_blocks_index):
        for bi, b in enumerate(page_blocks):
            if b.get("block_type") in ("SectionHeader", "Title") and not _is_dropped(b):
                all_headers.append((pi, bi, b))
    _normalize_headers(all_headers, counts)

    # 6. Promote missing leading list item ("i. Oxygen content") to a header.
    _promote_orphan_first_list_items(page_blocks_index, counts)

    # 7. TOC detection (only on first 2 pages)
    for pi, page_blocks in enumerate(page_blocks_index[:2]):
        for b in page_blocks:
            if b.get("block_type") == "ListGroup" and _is_toc_listgroup(b):
                b["block_type"] = "TableOfContents"
                _set_norm(b, "is_toc", True)
                counts["toc_blocks"] += 1

    # 8. Repair cross-page section_hierarchy continuity (mapper reads this)
    _repair_section_hierarchy_across_pages(page_blocks_index, counts)

    document_root["_norm_meta"] = {"counts": counts}
    return document_root


# ────────────────────────────────────────────────────────────────────────────
# Block helpers
# ────────────────────────────────────────────────────────────────────────────

def _set_norm(b: dict[str, Any], key: str, value: Any) -> None:
    b[_NORM + key] = value


def _get_norm(b: dict[str, Any], key: str, default: Any = None) -> Any:
    return b.get(_NORM + key, default)


def _is_dropped(b: dict[str, Any]) -> bool:
    return bool(_get_norm(b, "drop", False))


def _plain_text(html: str | None) -> str:
    if not html or not isinstance(html, str):
        return ""
    return _RE_WS.sub(" ", _RE_TAGS.sub(" ", html)).strip()


def _bbox_top_bottom(b: dict[str, Any]) -> tuple[float, float] | None:
    bbox = b.get("bbox")
    if not isinstance(bbox, list) or len(bbox) < 4:
        return None
    try:
        return float(bbox[1]), float(bbox[3])
    except (TypeError, ValueError):
        return None


def _heading_level_from_html(html: str | None) -> int:
    if not html:
        return 2
    m = _RE_HTAG.search(html)
    if m:
        return int(m.group(1))
    return 2


def _set_heading_level(b: dict[str, Any], new_level: int) -> None:
    """Rewrite the leading <hN> tag in the block's html."""
    html = b.get("html")
    if not isinstance(html, str):
        return
    nh = _RE_HTAG.sub(f"<h{new_level}", html, count=1)
    nh = re.sub(r"</h([1-6])>", f"</h{new_level}>", nh, count=1)
    b["html"] = nh


# ────────────────────────────────────────────────────────────────────────────
# Figure parsing & equation detection
# ────────────────────────────────────────────────────────────────────────────

def _enrich_figure(b: dict[str, Any], counts: dict[str, int]) -> None:
    html = b.get("html") or ""
    alt_m = _RE_IMG_ALT.search(html)
    src_m = _RE_IMG_SRC.search(html)
    desc_m = _RE_IMG_DESC.search(html)
    alt = alt_m.group(1).strip() if alt_m else ""
    src = src_m.group(1).strip() if src_m else ""
    desc = _plain_text(desc_m.group(1)) if desc_m else ""
    if alt:
        _set_norm(b, "figure_alt", alt)
        counts["figures_with_alt"] += 1
    if src:
        _set_norm(b, "figure_filename", src)
    if desc:
        _set_norm(b, "figure_image_description", desc)
        counts["figures_with_desc"] += 1


def _looks_like_equation(b: dict[str, Any]) -> bool:
    alt = _get_norm(b, "figure_alt", "") or ""
    desc = _get_norm(b, "figure_image_description", "") or ""
    src = _get_norm(b, "figure_filename", "") or ""
    bbox = b.get("bbox") or []
    if alt or desc:
        return False
    width = (bbox[2] - bbox[0]) if isinstance(bbox, list) and len(bbox) >= 4 else 0
    height = (bbox[3] - bbox[1]) if isinstance(bbox, list) and len(bbox) >= 4 else 0
    aspect_thin = bool(width and height and width / max(height, 1) >= 3.0)
    only_image = bool(src) and not alt and not desc
    if only_image and aspect_thin:
        return True
    candidate = " ".join([alt, desc])
    return bool(_RE_MATH_HINTS.search(candidate) or _RE_REACTION.search(candidate))


def _reclassify_as_equation(b: dict[str, Any], counts: dict[str, int]) -> None:
    """Mark a Figure as an Equation (mapper will treat it as an Equation chunk).

    Latex is left empty when we cannot recover it from alt/desc — the mapper still
    creates a chunk so the equation is at least addressable; the rescue pass (TODO)
    can later fill it via VLM/Texify.
    """
    alt = _get_norm(b, "figure_alt", "") or ""
    desc = _get_norm(b, "figure_image_description", "") or ""
    latex_candidate = (alt + "\n" + desc).strip()
    b["block_type"] = "Equation"
    if latex_candidate:
        _set_norm(b, "equation_latex", latex_candidate)
    _set_norm(b, "reclassified_from", "Figure")
    counts["equations_reclassified"] += 1


# ────────────────────────────────────────────────────────────────────────────
# Caption pinning
# ────────────────────────────────────────────────────────────────────────────

def _bind_captions_on_page(page_blocks: list[dict[str, Any]], counts: dict[str, int]) -> None:
    """Pin Caption blocks to the nearest preceding Figure/Picture/Equation on the page.

    Within 200 pt vertical distance (generous; captions appear above or below figures).
    """
    figures = [b for b in page_blocks if b.get("block_type") in ("Figure", "Picture", "Equation")]
    for cap in page_blocks:
        if cap.get("block_type") != "Caption" or _is_dropped(cap):
            continue
        cap_tb = _bbox_top_bottom(cap)
        if cap_tb is None or not figures:
            continue
        cap_top, cap_bot = cap_tb
        best: dict[str, Any] | None = None
        best_dist = float("inf")
        for fig in figures:
            if _is_dropped(fig):
                continue
            fig_tb = _bbox_top_bottom(fig)
            if fig_tb is None:
                continue
            f_top, f_bot = fig_tb
            if cap_top >= f_bot:
                dist = cap_top - f_bot
            elif cap_bot <= f_top:
                dist = f_top - cap_bot
            else:
                dist = 0.0
            if dist < best_dist:
                best_dist = dist
                best = fig
        if best is not None and best_dist <= 200.0:
            cap_id = cap.get("id") or ""
            fig_id = best.get("id") or ""
            _set_norm(cap, "attached_image_block_id", fig_id)
            _set_norm(best, "caption_block_id", cap_id)
            _set_norm(best, "caption_text", _plain_text(cap.get("html")))
            # Drop the standalone Caption chunk: its text is already merged
            # into the Image chunk's content, so emitting it as its own chunk
            # would double-embed and double-FTS the same string.
            _set_norm(cap, "drop", True)
            counts["captions_pinned"] += 1
            counts["captions_dropped_redundant"] += 1


# ────────────────────────────────────────────────────────────────────────────
# Header level normalization
# ────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _NumberingPrefix:
    """A parsed leading numbering label of a heading.

    `style` is one of:
      arabic        - "1", "23"
      dotted        - "14.1", "1.2.3"   (multi-segment numeric)
      roman_lower   - "i", "iv", "xii"  (validated as roman, 1..3999)
      roman_upper   - "I", "IV", "XII"
      alpha_lower   - "a".."z"          (single letter)
      alpha_upper   - "A".."Z"          (single letter)
      word_prefixed - "Step 4", "Phase 2", "Chapter 14"
                      (`label` carries the trailing identifier; `word` carries the keyword)

    `raw` is the literal substring matched in the heading (preserves brackets,
    word, separator) and is what we surface as `numbering_prefix` so the UI
    can render the original outline label.
    """
    style: str
    label: str
    raw: str
    word: str | None = None
    is_parenthesized: bool = False
    is_bracketed: bool = False
    depth: int = 1

    @property
    def rank(self) -> int | None:
        """Position in a hypothetical series. Used by sibling-snapping passes."""
        if self.style == "arabic":
            try:
                return int(self.label)
            except ValueError:
                return None
        if self.style == "dotted":
            tail = self.label.rsplit(".", 1)[-1]
            try:
                return int(tail)
            except ValueError:
                return None
        if self.style in ("roman_lower", "roman_upper"):
            return _roman_to_int(self.label.lower())
        if self.style in ("alpha_lower", "alpha_upper"):
            if len(self.label) == 1 and self.label.isalpha():
                return ord(self.label.lower()) - ord("a") + 1
            return None
        if self.style == "word_prefixed":
            try:
                return int(self.label)
            except ValueError:
                return _roman_to_int(self.label.lower())
        return None


_VALID_ROMAN = re.compile(r"^m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$")


def _roman_to_int(s: str) -> int | None:
    if not s or not _VALID_ROMAN.match(s):
        return None
    table = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total = 0
    prev = 0
    for ch in reversed(s):
        v = table.get(ch)
        if v is None:
            return None
        if v < prev:
            total -= v
        else:
            total += v
        prev = v
    return total or None


def _detect_prefix(text: str) -> _NumberingPrefix | None:
    """Detect the leading numbering label of a heading. Returns None if there
    is no recognisable label, or if the captured label fails validation
    (e.g. an invalid roman numeral like "il.", a hyphenated compound like "X-Ray").
    """
    if not text:
        return None
    m = _RE_LEADING_LABEL.match(text)
    if not m:
        return None
    word = m.group("word")
    label = m.group("label")
    sep = m.group("sep") or ""
    open_b = m.group("open")
    close_b = m.group("close")
    raw = text[m.start() : m.end() - 1].rstrip()  # excludes the trailing first content char

    # A "strong" separator unambiguously marks a label (".", ":", ")", "]").
    # A bare "-" or "—" doesn't — it could be a hyphenated word like "X-Ray".
    has_strong_sep = any(c in sep for c in ".:)]")
    has_bracket = bool(open_b or close_b)

    style = _classify_label(
        label, word=word, has_separator=has_strong_sep or has_bracket
    )
    if style is None:
        return None

    # Disambiguator gate: the candidate must have a strong separator, brackets,
    # or a word prefix — otherwise plain text like "1980 census" or "A practical
    # guide" would mis-parse. Dotted is exempt (self-disambiguating).
    if (
        style in _REQUIRES_SEPARATOR
        and not (has_strong_sep or has_bracket)
        and word is None
    ):
        return None

    depth = label.count(".") + 1 if style == "dotted" else 1
    return _NumberingPrefix(
        style=style,
        label=label,
        raw=raw,
        word=word,
        is_parenthesized=(open_b == "(" or close_b == ")"),
        is_bracketed=(open_b == "[" or close_b == "]"),
        depth=depth,
    )


def _classify_label(label: str, *, word: str | None, has_separator: bool) -> str | None:
    """Decide which numbering style this label belongs to."""
    if not label:
        return None
    # word_prefixed wins when there's an explicit word prefix; the trailing
    # label is then numeric or roman.
    if word is not None:
        if label.isdigit():
            return "word_prefixed"
        if _roman_to_int(label.lower()) is not None:
            return "word_prefixed"
        return None
    if "." in label:
        # All segments must be integers (e.g. "14.4.1"); reject "v.s.".
        segments = label.split(".")
        if all(seg.isdigit() for seg in segments):
            return "dotted"
        return None
    if label.isdigit():
        return "arabic"
    # Letters: try roman first (validated), then plain alpha.
    if label.islower():
        if _roman_to_int(label) is not None:
            return "roman_lower"
        if len(label) == 1:
            return "alpha_lower"
        return None
    if label.isupper():
        if _roman_to_int(label.lower()) is not None:
            return "roman_upper"
        if len(label) == 1:
            return "alpha_upper"
        return None
    return None


def _normalize_headers(
    headers: list[tuple[int, int, dict[str, Any]]],
    counts: dict[str, int],
) -> None:
    """Snap heading levels using detected numbering prefixes.

    Three passes:
      A. Sibling-run snapping: contiguous headers sharing the same numbering
         style get snapped to the smallest level in the run.
         (Style-agnostic: works for any style _detect_prefix recognises.)
      B. Inline-label demotion: a header with no prefix that sits between two
         deeper headers gets demoted to the deeper level.
      C. Global numeric/alpha sibling snapping: catches non-contiguous siblings
         such as "1. Glycolysis" (h2) followed thirty subsections later by
         "2. Citric Acid Cycle" (h3). Fires only when the immediately previous
         same-style label has rank N-1 and the candidate is currently DEEPER.
         Works for any style with a totally-ordered rank: arabic, roman_lower,
         roman_upper, alpha_lower, alpha_upper, dotted, word_prefixed.
    """
    if not headers:
        return

    enriched: list[dict[str, Any]] = []
    for pi, bi, b in headers:
        text = _plain_text(b.get("html"))
        prefix = _detect_prefix(text)
        level = _heading_level_from_html(b.get("html"))
        if prefix:
            # Preserve the original outline label ("Step 4", "(a)", "14.1")
            # rather than always coercing to "<label>.".
            _set_norm(b, "numbering_prefix", prefix.raw)
        enriched.append(
            {
                "page": pi,
                "idx": bi,
                "block": b,
                "text": text,
                "prefix": prefix,
                "level": level,
            }
        )

    # ── Pass A: snap contiguous sibling runs ───────────────────────────────
    i = 0
    while i < len(enriched):
        cur = enriched[i]
        if cur["prefix"] is None:
            i += 1
            continue
        style = cur["prefix"].style
        # For dotted, also require equal depth — "14.1" and "14.1.2" should
        # never be siblings.
        depth = cur["prefix"].depth if style == "dotted" else None
        run = [cur]
        j = i + 1
        while j < len(enriched):
            nxt = enriched[j]
            if (
                nxt["prefix"] is not None
                and nxt["prefix"].style == style
                and (depth is None or nxt["prefix"].depth == depth)
            ):
                run.append(nxt)
                j += 1
            else:
                break
        if len(run) >= 2:
            target_level = min(item["level"] for item in run)
            for item in run:
                if item["level"] != target_level:
                    _flag(item["block"], "level_snapped_from", item["level"])
                    _set_heading_level(item["block"], target_level)
                    item["level"] = target_level
                    counts["headers_snapped"] += 1
        i = j

    # ── Pass B: demote orphan inline-label headers ─────────────────────────
    for k in range(1, len(enriched) - 1):
        cur = enriched[k]
        if cur["prefix"] is not None:
            continue
        if not _looks_like_inline_label(cur["text"]):
            continue
        prev_level = enriched[k - 1]["level"]
        next_level = enriched[k + 1]["level"]
        deeper_neighbour = max(prev_level, next_level)
        if deeper_neighbour - cur["level"] >= 2:
            _flag(cur["block"], "level_demoted_from", cur["level"])
            _set_heading_level(cur["block"], deeper_neighbour)
            cur["level"] = deeper_neighbour
            counts["headers_demoted"] += 1

    # ── Pass C: global rank-1 sibling snapping ─────────────────────────────
    for k in range(1, len(enriched)):
        cur = enriched[k]
        cur_pref = cur["prefix"]
        if cur_pref is None:
            continue
        cur_rank = cur_pref.rank
        if cur_rank is None or cur_rank < 2:
            continue
        for j in range(k - 1, -1, -1):
            prev = enriched[j]
            prev_pref = prev["prefix"]
            if prev_pref is None or prev_pref.style != cur_pref.style:
                continue
            # For dotted, require same depth and same parent prefix
            # (so "14.4.1" and "14.4.2" can be siblings, but "14.4.1" and
            # "15.1.1" cannot).
            if cur_pref.style == "dotted":
                if prev_pref.depth != cur_pref.depth:
                    continue
                cur_parent = cur_pref.label.rsplit(".", 1)[0]
                prev_parent = prev_pref.label.rsplit(".", 1)[0]
                if cur_parent != prev_parent:
                    continue
            # For word_prefixed, the keyword must match too (Step 4 is not the
            # sibling of Phase 5).
            if cur_pref.style == "word_prefixed" and (
                (prev_pref.word or "").lower() != (cur_pref.word or "").lower()
            ):
                continue
            prev_rank = prev_pref.rank
            if prev_rank != cur_rank - 1:
                # First same-style candidate that is NOT our N-1 predecessor —
                # we're inside a different run, stop searching.
                break
            if cur["level"] > prev["level"]:
                _flag(cur["block"], "level_snapped_global_from", cur["level"])
                _set_heading_level(cur["block"], prev["level"])
                cur["level"] = prev["level"]
                counts["headers_snapped_global"] += 1
            break


def _flag(block: dict[str, Any], key: str, value: Any) -> None:
    flags = _get_norm(block, "normalization_flags", None)
    if not isinstance(flags, dict):
        flags = {}
        _set_norm(block, "normalization_flags", flags)
    flags[key] = value


# ────────────────────────────────────────────────────────────────────────────
# Promote orphan list-item to SectionHeader
# ────────────────────────────────────────────────────────────────────────────

def _promote_orphan_first_list_items(
    page_blocks_index: list[list[dict[str, Any]]],
    counts: dict[str, int],
) -> None:
    """When SectionHeaders for rank>=2 exist but rank=1 is missing, look in the
    immediately preceding ListGroup for the first <li> whose label matches the
    series at rank 1 and synthesize a SectionHeader from it.

    Style-agnostic — works for any numbering style with a rank.
    """
    flat: list[tuple[int, int, dict[str, Any]]] = []
    for pi, page_blocks in enumerate(page_blocks_index):
        for bi, b in enumerate(page_blocks):
            flat.append((pi, bi, b))

    n = len(flat)
    i = 0
    while i < n:
        pi, bi, b = flat[i]
        if (
            b.get("block_type") not in ("SectionHeader", "Title")
            or _is_dropped(b)
        ):
            i += 1
            continue
        prefix = _detect_prefix(_plain_text(b.get("html")))
        if prefix is None or prefix.rank is None:
            i += 1
            continue
        # Build the run (consecutive same-style same-depth headers)
        run = [(i, b)]
        j = i + 1
        while j < n:
            _, _, b2 = flat[j]
            if (
                b2.get("block_type") in ("SectionHeader", "Title")
                and not _is_dropped(b2)
            ):
                p2 = _detect_prefix(_plain_text(b2.get("html")))
                if (
                    p2
                    and p2.style == prefix.style
                    and (prefix.style != "dotted" or p2.depth == prefix.depth)
                ):
                    run.append((j, b2))
                    j += 1
                    continue
            j += 1
            break

        # Only act if the first label has rank > 1 (series doesn't start at 1).
        if prefix.rank == 1:
            i = j
            continue
        # Look back for a ListGroup (or short Text block) whose first labelled
        # token starts the series at rank 1. Widened to 15 so a figure/caption
        # or cross-column layout between the list and the first surviving
        # header doesn't hide the originating block. Text fallback covers the
        # case where Marker emits the rank-1 item as a misclassified paragraph.
        for k in range(i - 1, max(-1, i - 15), -1):
            _, _, candidate = flat[k]
            if _is_dropped(candidate):
                continue
            bt = candidate.get("block_type")
            if bt == "ListGroup":
                html = candidate.get("html") or ""
                first_li = re.search(r"<li[^>]*>(.*?)</li>", html, re.DOTALL | re.IGNORECASE)
                if not first_li:
                    continue
                label_text = _plain_text(first_li.group(1))
                source = "list_item"
            elif bt == "Text":
                t = _plain_text(candidate.get("html"))
                # Short Text blocks only — a long paragraph that happens to
                # start with "i. ..." is almost certainly not a missed heading.
                if not t or len(t) > 120:
                    continue
                label_text = t
                source = "text_block"
            else:
                continue

            label_prefix = _detect_prefix(label_text)
            if not label_prefix or label_prefix.style != prefix.style:
                continue
            if label_prefix.rank != 1:
                continue

            # Synthesize a SectionHeader block at the same level as the run
            level = _heading_level_from_html(b.get("html"))
            synthetic = {
                "id": f"{candidate.get('id', '')}_norm_promoted",
                "block_type": "SectionHeader",
                "html": f"<h{level}>{label_text}</h{level}>",
                "page": candidate.get("page"),
                "polygon": candidate.get("polygon"),
                "bbox": candidate.get("bbox"),
                "section_hierarchy": candidate.get("section_hierarchy") or {},
                "images": {},
                "markdown": None,
                "inference_failed": False,
            }
            _set_norm(synthetic, "synthesized_from", source)
            _set_norm(synthetic, "numbering_prefix", label_prefix.raw)
            _flag(synthetic, "synthetic_promoted", True)
            page_idx = candidate.get("page")
            if isinstance(page_idx, int) and 0 <= page_idx < len(page_blocks_index):
                page_blocks = page_blocks_index[page_idx]
                try:
                    insert_at = page_blocks.index(candidate) + 1
                except ValueError:
                    insert_at = len(page_blocks)
                page_blocks.insert(insert_at, synthetic)
                counts["headers_promoted"] += 1
            break
        i = j


# ────────────────────────────────────────────────────────────────────────────
# TOC detection
# ────────────────────────────────────────────────────────────────────────────

def _is_toc_listgroup(b: dict[str, Any]) -> bool:
    html = b.get("html") or ""
    items = re.findall(r"<li[^>]*>(.*?)</li>", html, re.DOTALL | re.IGNORECASE)
    if len(items) < 3:
        return False
    matches = sum(1 for it in items if _RE_TOC_ITEM.match(_plain_text(it)))
    return matches >= max(3, int(0.7 * len(items)))


# ────────────────────────────────────────────────────────────────────────────
# Cross-page section_hierarchy repair
# ────────────────────────────────────────────────────────────────────────────

def _repair_section_hierarchy_across_pages(
    page_blocks_index: list[list[dict[str, Any]]],
    counts: dict[str, int],
) -> None:
    """If the first non-header block on page N has shallower section_hierarchy than
    the running hierarchy from page N-1, copy missing deeper levels forward.

    Marker drops the deepest level on continuation paragraphs; we restore it so
    the mapper attaches the chunk to the right section.

    Only headers update `last_hierarchy`. When a header at level L appears we
    keep ancestors strictly shallower than L and add the new header at level L —
    deeper stale levels are dropped.
    """
    last_hierarchy: dict[int, Any] = {}
    for page_blocks in page_blocks_index:
        page_first_block_handled = False
        for b in page_blocks:
            if _is_dropped(b):
                continue
            bt = b.get("block_type")
            sh = b.get("section_hierarchy")
            if not isinstance(sh, dict):
                sh = {}
            if bt in ("SectionHeader", "Title"):
                lvl = _heading_level_from_html(b.get("html"))
                last_hierarchy = {k: v for k, v in last_hierarchy.items() if k < lvl}
                last_hierarchy[lvl] = b.get("id")
                page_first_block_handled = True
                continue
            if not page_first_block_handled and last_hierarchy:
                cur_max = max(
                    (int(k) for k in sh.keys() if str(k).isdigit()), default=0
                )
                last_max = max(last_hierarchy.keys(), default=0)
                if last_max > cur_max:
                    patched = {str(k): v for k, v in last_hierarchy.items()}
                    patched.update({str(k): v for k, v in sh.items()})
                    b["section_hierarchy"] = patched
                    counts["section_hierarchy_patched"] += 1
                page_first_block_handled = True
