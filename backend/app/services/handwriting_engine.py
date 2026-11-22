"""Personal handwriting layout, human-imperfection, and deformation rendering engine."""

from __future__ import annotations

import re
from collections import Counter, deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter, map_coordinates

from app.config import get_reference_font_path
from app.data.common_chars import CONFUSABLE_CHARS
from app.models import HandwritingStyle, PageMeta, RegionConfig
from app.services.sheet_extractor import GLYPH_CANVAS_SIZE

MISTAKE_RE = re.compile(r"\[([^\[\]\->]+)->([^\[\]\->]+)\]")

FORBIDDEN_LINE_START = set("，。！？；：、）》”’.,:;!?)]%℃°")
FORBIDDEN_LINE_END = set("（《“‘([")
TUCK_PUNCT = set("，。！？；：、,.!?")
LOWER_PUNCT = set("，。、.,_~")


@dataclass
class Token:
    kind: str  # "char" | "mistake" | "newline" | "space"
    char: str = ""
    wrong_text: str = ""
    right_text: str = ""


@dataclass
class PlacedGlyph:
    page_index: int
    kind: str  # "glyph" | "missing" | "strikethrough"
    char: str
    glyph_row: Optional[dict]
    x_pt: float
    baseline_pt: float
    font_size_pt: float
    progress: float  # 0..1 across region chain for fatigue gradient
    token_seed: int
    # Used for strikethrough overlay bounding box in pt
    strike_x0_pt: float = 0.0
    strike_y0_pt: float = 0.0
    strike_x1_pt: float = 0.0
    strike_y1_pt: float = 0.0
    strike_style: str = "double_line"
    is_ai_generated: bool = False
    width_pt: float = 0.0


def parse_text_tokens(
    text: str,
    style: HandwritingStyle,
    glyphs_by_char: dict[str, list[dict]],
    rng: np.random.Generator,
) -> list[Token]:
    """Parse plain text plus `[wrong->right]` inline mistake syntax and optional auto-mistakes."""
    tokens: list[Token] = []

    def _emit_plain(seg: str) -> None:
        for ch in seg:
            if ch == "\n":
                tokens.append(Token(kind="newline"))
            elif ch == "\r":
                continue
            elif ch.isspace():
                tokens.append(Token(kind="space"))
            else:
                if (
                    style.strikethrough_prob > 0.0
                    and ch in CONFUSABLE_CHARS
                    and rng.random() < style.strikethrough_prob
                ):
                    candidates = [c for c in CONFUSABLE_CHARS[ch] if c in glyphs_by_char]
                    if candidates and ch in glyphs_by_char:
                        wrong_ch = candidates[int(rng.integers(0, len(candidates)))]
                        tokens.append(Token(kind="mistake", wrong_text=wrong_ch, right_text=ch))
                        continue
                tokens.append(Token(kind="char", char=ch))

    pos = 0
    for m in MISTAKE_RE.finditer(text):
        _emit_plain(text[pos : m.start()])
        tokens.append(Token(kind="mistake", wrong_text=m.group(1), right_text=m.group(2)))
        pos = m.end()
    _emit_plain(text[pos:])
    return tokens


def _expand_tokens_for_rendering(tokens: list[Token]) -> list[tuple[str, str, int]]:
    """
    Flatten tokens into render items:
    (item_type, char_or_style, group_id)
    where `item_type` in {"char", "wrong_char", "strike_trigger", "newline", "space"}.
    """
    items: list[tuple[str, str, int]] = []
    group_counter = 0
    for tok in tokens:
        if tok.kind == "newline":
            items.append(("newline", "", 0))
        elif tok.kind == "space":
            items.append(("space", "", 0))
        elif tok.kind == "char":
            items.append(("char", tok.char, 0))
        elif tok.kind == "mistake":
            group_counter += 1
            for ch in tok.wrong_text:
                if not ch.isspace():
                    items.append(("wrong_char", ch, group_counter))
            items.append(("strike_trigger", "", group_counter))
            for ch in tok.right_text:
                if not ch.isspace():
                    items.append(("char", ch, 0))
    return items


def _parse_hex_color(hex_str: str) -> tuple[int, int, int]:
    cleaned = hex_str.strip().lstrip("#")
    if len(cleaned) == 3:
        cleaned = "".join(c * 2 for c in cleaned)
    if len(cleaned) != 6:
        return (28, 29, 36)
    try:
        return (int(cleaned[0:2], 16), int(cleaned[2:4], 16), int(cleaned[4:6], 16))
    except ValueError:
        return (28, 29, 36)


@lru_cache(maxsize=4096)
def _load_glyph_alpha(image_path: str) -> np.ndarray:
    """Load 256x256 normalized float32 alpha array from glyph PNG."""
    with Image.open(image_path) as img:
        rgba = img.convert("RGBA")
        alpha = np.asarray(rgba.split()[-1], dtype=np.float32) / 255.0
    return alpha


@lru_cache(maxsize=8)
def _get_meshgrid(size: int) -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.meshgrid(
        np.arange(size, dtype=np.float32),
        np.arange(size, dtype=np.float32),
        indexing="ij",
    )
    return yy, xx


@lru_cache(maxsize=64)
def _get_ref_font(px_size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(get_reference_font_path(), max(8, px_size))


def _pick_variant(
    char: str,
    glyphs_by_char: dict[str, list[dict]],
    recent_history: dict[str, deque],
    rng: np.random.Generator,
) -> Optional[dict]:
    variants = glyphs_by_char.get(char)
    if not variants:
        return None
    if len(variants) == 1:
        return variants[0]

    hist = recent_history.get(char)
    if hist is None:
        hist = deque(maxlen=min(3, len(variants) - 1))
        recent_history[char] = hist

    allowed = [i for i in range(len(variants)) if i not in hist]
    if not allowed:
        allowed = list(range(len(variants)))
    chosen_idx = allowed[int(rng.integers(0, len(allowed)))]
    hist.append(chosen_idx)
    return variants[chosen_idx]


def _estimate_advance_pt(
    ch: str,
    glyph_row: Optional[dict],
    font_size_pt: float,
    word_spacing_factor: float,
    prev_ch: str,
    rng: np.random.Generator,
) -> tuple[float, float]:
    """
    Return (x_nudge_pt, advance_pt).
    Typical CJK box scale is font_size_pt / 0.68.
    """
    box_pt = font_size_pt / 0.68
    if glyph_row is None:
        base = font_size_pt * (0.45 if ch.isascii() else 0.88)
        return (0.0, base * word_spacing_factor)

    ink_w_pt = float(glyph_row["visual_width_ratio"]) * box_pt
    # Clamp unreasonable extreme narrow/wide outliers while preserving natural proportion
    if ch in TUCK_PUNCT:
        min_w = font_size_pt * 0.24
        max_w = font_size_pt * 0.72
        ink_w_pt = max(min_w, min(max_w, ink_w_pt))
        x_nudge = -font_size_pt * 0.08 if (prev_ch and prev_ch not in TUCK_PUNCT) else 0.0
        gap = font_size_pt * 0.08 * word_spacing_factor
        return (x_nudge, ink_w_pt * 0.92 + gap)

    if ch.isascii():
        min_w = font_size_pt * 0.18
        ink_w_pt = max(min_w, ink_w_pt)
        gap = font_size_pt * (0.09 + float(rng.normal(0.0, 0.015))) * word_spacing_factor
        return (0.0, ink_w_pt * 0.96 + max(0.5, gap))

    min_w = font_size_pt * 0.42
    ink_w_pt = max(min_w, ink_w_pt)
    gap = font_size_pt * (0.11 + float(rng.normal(0.0, 0.025))) * word_spacing_factor
    return (0.0, ink_w_pt * word_spacing_factor + max(0.5, gap))


def _place_line_tokens(
    line_items: list[tuple[str, str, int]],
    page_index: int,
    start_x_pt: float,
    baseline_pt: float,
    font_size_pt: float,
    style: HandwritingStyle,
    glyphs_by_char: dict[str, list[dict]],
    recent_history: dict[str, deque],
    rng: np.random.Generator,
    progress_start: float,
    progress_end: float,
    align: str = "left",
    region_width_pt: float = 0.0,
) -> tuple[list[PlacedGlyph], float]:
    """Compute final coordinates for a single line's tokens, including smooth baseline drift."""
    n_items = max(1, len(line_items))
    # First pass: determine variants and advances to support center/right alignment
    prelim: list[dict] = []
    cursor_x = 0.0
    prev_ch = ""

    for idx, (itype, ch, gid) in enumerate(line_items):
        prog = progress_start + (progress_end - progress_start) * (idx / n_items)
        eff_spacing = style.word_spacing_factor * (1.0 + 0.10 * prog * style.fatigue_intensity)

        if itype == "space":
            cursor_x += font_size_pt * 0.36 * eff_spacing
            prev_ch = ""
            continue
        if itype == "strike_trigger":
            prelim.append({"type": "strike_trigger", "group_id": gid})
            continue

        glyph_row = _pick_variant(ch, glyphs_by_char, recent_history, rng)
        nudge_x, adv = _estimate_advance_pt(ch, glyph_row, font_size_pt, eff_spacing, prev_ch, rng)
        prelim.append(
            {
                "type": itype,
                "char": ch,
                "group_id": gid,
                "glyph_row": glyph_row,
                "rel_x": cursor_x + nudge_x,
                "adv": adv,
                "progress": prog,
            }
        )
        cursor_x += adv
        prev_ch = ch

    line_width = cursor_x
    align_offset = 0.0
    if align == "center" and region_width_pt > line_width:
        align_offset = (region_width_pt - line_width) * 0.5
    elif align == "right" and region_width_pt > line_width:
        align_offset = region_width_pt - line_width

    # Smooth low-frequency random walk for natural line baseline drift + slant
    drift_pts = np.zeros(len(prelim) + 1, dtype=np.float32)
    if len(prelim) > 0 and style.baseline_drift > 0.001:
        steps = rng.normal(0.0, style.baseline_drift * 0.35, size=len(prelim))
        walk = np.cumsum(steps)
        # Re-center so start doesn't run away linearly
        walk = walk - np.linspace(walk[0], walk[-1], len(walk)) * 0.45
        drift_pts[: len(prelim)] = np.clip(walk, -style.baseline_drift * 1.6, style.baseline_drift * 1.6)

    slant_slope = float(np.tan(np.deg2rad(style.line_slant)))

    placed: list[PlacedGlyph] = []
    mistake_boxes: dict[int, list[float]] = {}  # gid -> [x0, y0, x1, y1]
    box_pt = font_size_pt / 0.68

    for idx, p in enumerate(prelim):
        if p["type"] == "strike_trigger":
            gid = p["group_id"]
            if gid in mistake_boxes:
                bx0, by0, bx1, by1 = mistake_boxes[gid]
                placed.append(
                    PlacedGlyph(
                        page_index=page_index,
                        kind="strikethrough",
                        char="",
                        glyph_row=None,
                        x_pt=bx0,
                        baseline_pt=0.5 * (by0 + by1),
                        font_size_pt=font_size_pt,
                        progress=0.0,
                        token_seed=int(rng.integers(1, 2**31 - 1)),
                        strike_x0_pt=bx0,
                        strike_y0_pt=by0,
                        strike_x1_pt=bx1,
                        strike_y1_pt=by1,
                        strike_style=style.strikethrough_style,
                    )
                )
            continue

        x_pt = start_x_pt + align_offset + p["rel_x"]
        rel_from_start = x_pt - start_x_pt
        slant_dy = rel_from_start * slant_slope
        fat_slant = rel_from_start * (-0.012 * p["progress"] * style.fatigue_intensity)
        base_y = baseline_pt + float(drift_pts[idx]) + slant_dy + fat_slant

        glyph_row = p["glyph_row"]
        ch = p["char"]
        kind = "glyph" if glyph_row is not None else "missing"

        if glyph_row is not None:
            bx0 = x_pt
            bx1 = x_pt + max(font_size_pt * 0.35, float(glyph_row["visual_width_ratio"]) * box_pt)
            h_pt = max(font_size_pt * 0.35, float(glyph_row["visual_height_ratio"]) * box_pt)
            by0 = base_y - h_pt * 0.92
            by1 = base_y + h_pt * 0.12
        else:
            bx0 = x_pt
            bx1 = x_pt + font_size_pt * 0.85
            by0 = base_y - font_size_pt * 0.85
            by1 = base_y + font_size_pt * 0.1

        if p["type"] == "wrong_char":
            gid = p["group_id"]
            if gid not in mistake_boxes:
                mistake_boxes[gid] = [bx0, by0, bx1, by1]
            else:
                cur = mistake_boxes[gid]
                cur[0] = min(cur[0], bx0)
                cur[1] = min(cur[1], by0)
                cur[2] = max(cur[2], bx1)
                cur[3] = max(cur[3], by1)

        placed.append(
            PlacedGlyph(
                page_index=page_index,
                kind=kind,
                char=ch,
                glyph_row=glyph_row,
                x_pt=x_pt,
                baseline_pt=base_y,
                font_size_pt=font_size_pt,
                progress=p["progress"],
                token_seed=int(rng.integers(1, 2**31 - 1)),
                is_ai_generated=bool(glyph_row is not None and glyph_row.get("source") == "ai_generated"),
                width_pt=max(4.0, bx1 - bx0),
            )
        )

    return placed, line_width


def _layout_flow_chain(
    chain_regions: list[RegionConfig],
    style: HandwritingStyle,
    glyphs_by_char: dict[str, list[dict]],
    recent_history: dict[str, deque],
    rng: np.random.Generator,
) -> tuple[list[PlacedGlyph], list[str]]:
    """Lay out a linked chain of multi_line/single_line regions across pages."""
    head = chain_regions[0]
    combined_text = "\n".join(r.text for r in chain_regions if r.text) if len(chain_regions) > 1 and any(r.text for r in chain_regions[1:]) else head.text
    tokens = parse_text_tokens(combined_text, style, glyphs_by_char, rng)
    items = _expand_tokens_for_rendering(tokens)
    total_items = max(1, len(items))

    placements: list[PlacedGlyph] = []
    warnings: list[str] = []
    item_idx = 0

    for reg_idx, reg in enumerate(chain_regions):
        if item_idx >= len(items):
            break

        if reg.type == "single_line":
            # Take up to next newline (or all remaining) for single line
            line_items: list[tuple[str, str, int]] = []
            while item_idx < len(items):
                if items[item_idx][0] == "newline":
                    item_idx += 1
                    break
                line_items.append(items[item_idx])
                item_idx += 1
            if not line_items:
                continue

            # Auto-shrink font size slightly if single line overflows box width
            font_pt = reg.font_size
            est_w = sum(
                (font_pt * 0.36 if it[0] == "space" else _estimate_advance_pt(it[1], (glyphs_by_char.get(it[1]) or [None])[0], font_pt, style.word_spacing_factor, "", rng)[1])
                for it in line_items
                if it[0] != "strike_trigger"
            )
            if est_w > reg.width * 0.96 and est_w > 1.0:
                font_pt = max(6.5, font_pt * (reg.width * 0.95 / est_w))

            baseline_y = reg.y + reg.height * 0.72
            if reg.baseline_offset > 0 and reg.baseline_offset <= reg.height:
                baseline_y = reg.y + reg.baseline_offset

            line_placed, _ = _place_line_tokens(
                line_items,
                reg.page_index,
                reg.x + 2.0,
                baseline_y,
                font_pt,
                style,
                glyphs_by_char,
                recent_history,
                rng,
                0.0,
                0.2,
                align=reg.align,
                region_width_pt=reg.width - 4.0,
            )
            placements.extend(line_placed)
            continue

        # Multi-line region
        font_pt = reg.font_size
        line_spacing = max(8.0, reg.line_spacing)
        cur_y = reg.y + reg.baseline_offset
        line_num = 0
        max_y = reg.y + reg.height + 2.0

        while item_idx < len(items) and cur_y <= max_y:
            indent = reg.first_line_indent if (reg_idx == 0 and line_num == 0) else 0.0
            avail_w = max(font_pt * 1.2, reg.width - indent)
            start_x = reg.x + indent + 2.0

            line_items = []
            cur_w = 0.0
            prev_ch = ""
            # Allow tiny organic right-margin overhang
            overhang = font_pt * 0.22 * (1.0 + style.fatigue_intensity * 0.5)

            while item_idx < len(items):
                itype, ch, gid = items[item_idx]
                if itype == "newline":
                    item_idx += 1
                    break
                if itype == "strike_trigger":
                    line_items.append((itype, ch, gid))
                    item_idx += 1
                    continue
                if itype == "space":
                    step = font_pt * 0.36 * style.word_spacing_factor
                    if cur_w + step > avail_w and line_items:
                        item_idx += 1
                        break
                    line_items.append((itype, ch, gid))
                    cur_w += step
                    item_idx += 1
                    prev_ch = ""
                    continue

                glyph_row = (glyphs_by_char.get(ch) or [None])[0]
                nudge, adv = _estimate_advance_pt(ch, glyph_row, font_pt, style.word_spacing_factor, prev_ch, rng)

                # Line wrapping with Chinese Kinsoku rules
                if line_items and (cur_w + adv > avail_w + overhang):
                    # Don't orphan FORBIDDEN_LINE_START at start of next line: pull it onto current line if slight
                    if ch in FORBIDDEN_LINE_START and (cur_w + adv <= avail_w + overhang + font_pt * 0.65):
                        line_items.append((itype, ch, gid))
                        item_idx += 1
                        break
                    # Don't leave FORBIDDEN_LINE_END alone at end of current line
                    if len(line_items) > 1 and line_items[-1][0] == "char" and line_items[-1][1] in FORBIDDEN_LINE_END:
                        line_items.pop()
                        item_idx -= 1
                    break

                line_items.append((itype, ch, gid))
                cur_w += adv
                item_idx += 1
                prev_ch = ch

            if line_items:
                p0 = max(0.0, (item_idx - len(line_items)) / total_items)
                p1 = min(1.0, item_idx / total_items)
                line_placed, _ = _place_line_tokens(
                    line_items,
                    reg.page_index,
                    start_x,
                    cur_y,
                    font_pt,
                    style,
                    glyphs_by_char,
                    recent_history,
                    rng,
                    p0,
                    p1,
                    align="left",
                    region_width_pt=avail_w,
                )
                placements.extend(line_placed)

            cur_y += line_spacing
            line_num += 1

    if item_idx < len(items):
        remaining = sum(1 for it in items[item_idx:] if it[0] in ("char", "wrong_char"))
        if remaining > 0:
            warnings.append(f"区域「{head.name}」文本超出边界，剩余 {remaining} 字未排入（可串联下一页区域或调小字号）")

    return placements, warnings


def _layout_table_region(
    reg: RegionConfig,
    style: HandwritingStyle,
    glyphs_by_char: dict[str, list[dict]],
    recent_history: dict[str, deque],
    rng: np.random.Generator,
) -> list[PlacedGlyph]:
    """Lay out Tab/comma separated rows into table cells defined by `table_rows` & `table_cols`."""
    rows = sorted(reg.table_rows) if len(reg.table_rows) >= 2 else [0.0, 1.0]
    cols = sorted(reg.table_cols) if len(reg.table_cols) >= 2 else [0.0, 1.0]
    n_rows = len(rows) - 1
    n_cols = len(cols) - 1

    lines = reg.text.splitlines()
    placements: list[PlacedGlyph] = []

    for r_idx in range(min(n_rows, len(lines))):
        raw_line = lines[r_idx]
        cells_text = raw_line.split("\t") if "\t" in raw_line else raw_line.split(",")
        cell_y0 = reg.y + rows[r_idx] * reg.height
        cell_y1 = reg.y + rows[r_idx + 1] * reg.height
        cell_h = cell_y1 - cell_y0

        for c_idx in range(min(n_cols, len(cells_text))):
            cell_str = cells_text[c_idx].strip()
            if not cell_str:
                continue
            cell_x0 = reg.x + cols[c_idx] * reg.width
            cell_x1 = reg.x + cols[c_idx + 1] * reg.width
            cell_w = max(8.0, cell_x1 - cell_x0 - 4.0)

            tokens = parse_text_tokens(cell_str, style, glyphs_by_char, rng)
            items = _expand_tokens_for_rendering(tokens)
            if not items:
                continue

            font_pt = min(reg.font_size, max(7.0, cell_h * 0.68))
            est_w = sum(
                (font_pt * 0.36 if it[0] == "space" else _estimate_advance_pt(it[1], (glyphs_by_char.get(it[1]) or [None])[0], font_pt, style.word_spacing_factor, "", rng)[1])
                for it in items
                if it[0] != "strike_trigger"
            )
            if est_w > cell_w * 0.94 and est_w > 1.0:
                font_pt = max(6.0, font_pt * (cell_w * 0.92 / est_w))

            baseline_y = cell_y0 + cell_h * 0.72
            prog = (r_idx * n_cols + c_idx) / max(1, n_rows * n_cols)
            placed, _ = _place_line_tokens(
                items,
                reg.page_index,
                cell_x0 + 2.0,
                baseline_y,
                font_pt,
                style,
                glyphs_by_char,
                recent_history,
                rng,
                prog,
                prog,
                align=reg.align if reg.align != "left" else "center",
                region_width_pt=cell_w,
            )
            placements.extend(placed)

    return placements


def compute_document_placements(
    regions: list[RegionConfig],
    style: HandwritingStyle,
    glyphs_by_char: dict[str, list[dict]],
) -> tuple[dict[int, list[PlacedGlyph]], dict]:
    """Compute placements across all regions and linked region chains."""
    rng = np.random.default_rng(style.seed)
    recent_history: dict[str, deque] = {}
    by_id = {r.id: r for r in regions}

    referenced_as_next = {r.next_region_id for r in regions if r.next_region_id and r.next_region_id in by_id}
    by_page: dict[int, list[PlacedGlyph]] = {}
    warnings: list[str] = []

    visited_in_chain: set[str] = set()

    for reg in regions:
        if reg.type == "table":
            placed = _layout_table_region(reg, style, glyphs_by_char, recent_history, rng)
            for p in placed:
                by_page.setdefault(p.page_index, []).append(p)
            continue

        if reg.id in referenced_as_next or reg.id in visited_in_chain:
            continue

        chain: list[RegionConfig] = []
        cur: Optional[RegionConfig] = reg
        seen_local: set[str] = set()
        while cur is not None and cur.id not in seen_local:
            seen_local.add(cur.id)
            visited_in_chain.add(cur.id)
            chain.append(cur)
            nxt_id = cur.next_region_id
            cur = by_id.get(nxt_id) if nxt_id else None

        if not any(r.text.strip() for r in chain):
            continue

        placed, w = _layout_flow_chain(chain, style, glyphs_by_char, recent_history, rng)
        warnings.extend(w)
        for p in placed:
            by_page.setdefault(p.page_index, []).append(p)

    # Also compute missing character counts and AI-generated characters across all placed items
    missing_counter: Counter[str] = Counter()
    ai_chars_seen: set[str] = set()
    ai_generated_chars: list[str] = []
    total_placed_chars = 0
    for page_items in by_page.values():
        for p in page_items:
            if p.kind in ("glyph", "missing"):
                total_placed_chars += 1
                if p.kind == "missing":
                    missing_counter[p.char] += 1
                elif p.is_ai_generated and p.char not in ai_chars_seen:
                    ai_chars_seen.add(p.char)
                    ai_generated_chars.append(p.char)

    stats = {
        "total_chars": total_placed_chars,
        "missing_counts": [{"char": ch, "count": cnt} for ch, cnt in missing_counter.most_common()],
        "missing_unique": len(missing_counter),
        "ai_generated_chars": ai_generated_chars,
        "warnings": warnings,
    }
    return by_page, stats


def _render_deformed_glyph_rgba(
    glyph_row: dict,
    style: HandwritingStyle,
    progress: float,
    dpi: int,
    font_size_pt: float,
    token_seed: int,
    ink_rgb: tuple[int, int, int],
) -> tuple[Image.Image, float]:
    """Apply stroke weight, elastic warp, scale/aspect/rotation jitter, and ink colorization."""
    rng = np.random.default_rng(token_seed)
    alpha = _load_glyph_alpha(glyph_row["image_path"]).copy()

    # 1. Stroke weight modulation (matches true pen thickness)
    if abs(style.stroke_weight - 1.0) > 0.02:
        if style.stroke_weight > 1.0:
            blurred = gaussian_filter(alpha, sigma=1.15)
            blend = min(0.7, (style.stroke_weight - 1.0) * 0.65)
            alpha = np.clip(alpha * (1.0 - blend * 0.25) + blurred * (style.stroke_weight * 0.9), 0.0, 1.0)
            alpha = np.power(alpha, 1.0 / max(1.0, style.stroke_weight))
        else:
            alpha = np.power(np.clip(alpha, 0.0, 1.0), 1.0 / max(0.45, style.stroke_weight))

    # 2. Low-frequency smooth elastic displacement field
    eff_elastic = style.elastic_intensity * (1.0 + 0.45 * progress * style.fatigue_intensity)
    if eff_elastic > 0.005:
        yy, xx = _get_meshgrid(GLYPH_CANVAS_SIZE)
        raw_dx = rng.uniform(-1.0, 1.0, size=(GLYPH_CANVAS_SIZE, GLYPH_CANVAS_SIZE)).astype(np.float32)
        raw_dy = rng.uniform(-1.0, 1.0, size=(GLYPH_CANVAS_SIZE, GLYPH_CANVAS_SIZE)).astype(np.float32)
        dx = gaussian_filter(raw_dx, sigma=24.0)
        dy = gaussian_filter(raw_dy, sigma=24.0)
        rms = float(np.sqrt(np.mean(dx * dx + dy * dy)) + 1e-6)
        amp = eff_elastic * 9.5
        dx = dx / rms * amp
        dy = dy / rms * amp
        alpha = map_coordinates(alpha, [yy + dy, xx + dx], order=1, mode="constant", cval=0.0)

    # 3. Ink density micro-fluctuation
    ink_mult = float(np.clip(1.0 + rng.normal(0.0, style.ink_variation), 0.68, 1.08))
    alpha = np.clip(alpha * ink_mult, 0.0, 1.0)

    # 4. Target pixel size with scale/aspect jitter & rotation
    box_pt = font_size_pt / 0.68
    px_per_pt = dpi / 72.0
    eff_scale_sigma = style.scale_sigma * (1.0 + 0.35 * progress * style.fatigue_intensity)
    scale_jitter = float(np.clip(1.0 + rng.normal(0.0, eff_scale_sigma), 0.78, 1.25))
    aspect_jitter = float(np.clip(1.0 + rng.normal(0.0, eff_scale_sigma * 0.45), 0.90, 1.12))

    target_h = max(6, int(round(box_pt * px_per_pt * scale_jitter)))
    target_w = max(6, int(round(target_h * aspect_jitter)))

    alpha_u8 = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    alpha_pil = Image.fromarray(alpha_u8, mode="L").resize((target_w, target_h), Image.Resampling.LANCZOS)

    rgba = Image.new("RGBA", (target_w, target_h), (*ink_rgb, 0))
    rgba.putalpha(alpha_pil)

    eff_rot_sigma = style.rotation_sigma * (1.0 + 0.45 * progress * style.fatigue_intensity)
    if eff_rot_sigma > 0.02:
        angle = float(np.clip(rng.normal(0.0, eff_rot_sigma), -14.0, 14.0))
        rgba = rgba.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)

    return rgba, float(target_h)


def _draw_strikethrough(
    canvas: Image.Image,
    item: PlacedGlyph,
    dpi: int,
    ink_rgb: tuple[int, int, int],
    stroke_weight: float,
) -> None:
    px_per_pt = dpi / 72.0
    rng = np.random.default_rng(item.token_seed)
    x0 = (item.strike_x0_pt - item.font_size_pt * 0.14) * px_per_pt
    x1 = (item.strike_x1_pt + item.font_size_pt * 0.14) * px_per_pt
    y0 = item.strike_y0_pt * px_per_pt
    y1 = item.strike_y1_pt * px_per_pt
    h = max(6.0, y1 - y0)
    w = max(8.0, x1 - x0)

    draw = ImageDraw.Draw(canvas)
    line_w = max(1, int(round(item.font_size_pt * px_per_pt * 0.048 * stroke_weight)))
    color = (*ink_rgb, 230)

    if item.strike_style == "scribble":
        pts: list[tuple[float, float]] = []
        n_loops = 5
        for i in range(n_loops * 2 + 1):
            t = i / (n_loops * 2)
            px = x0 + t * w + float(rng.normal(0, w * 0.03))
            py = y0 + (0.25 if i % 2 == 0 else 0.78) * h + float(rng.normal(0, h * 0.06))
            pts.append((px, py))
        draw.line(pts, fill=color, width=line_w, joint="curve")
    else:
        for frac in (0.42, 0.58):
            pts = []
            steps = 8
            tilt = float(rng.normal(0.0, h * 0.08))
            arc = float(rng.normal(0.0, h * 0.05))
            for i in range(steps + 1):
                t = i / steps
                px = x0 + t * w
                py = y0 + frac * h + (t - 0.5) * tilt + np.sin(t * np.pi) * arc + float(rng.normal(0, h * 0.015))
                pts.append((px, float(py)))
            draw.line(pts, fill=color, width=line_w, joint="curve")


def render_page_overlay(
    pages_meta: list[PageMeta],
    regions: list[RegionConfig],
    style: HandwritingStyle,
    glyphs_by_char: dict[str, list[dict]],
    page_index: int,
    dpi: int = 120,
    missing_char_mode: str = "highlight",
    precomputed: Optional[tuple[dict[int, list[PlacedGlyph]], dict]] = None,
) -> tuple[bytes, dict]:
    """
    Render transparent RGBA PNG handwriting overlay for `page_index` at `dpi`.
    Returns `(png_bytes, stats_dict)`.
    """
    import io

    if page_index < 0 or page_index >= len(pages_meta):
        raise IndexError(f"Page index {page_index} out of range")

    page_meta = pages_meta[page_index]
    px_per_pt = dpi / 72.0
    canvas_w = max(1, int(round(page_meta.width_pt * px_per_pt)))
    canvas_h = max(1, int(round(page_meta.height_pt * px_per_pt)))
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    if precomputed is None:
        by_page, stats = compute_document_placements(regions, style, glyphs_by_char)
    else:
        by_page, stats = precomputed

    ink_rgb = _parse_hex_color(style.ink_color)
    items = by_page.get(page_index, [])
    draw = ImageDraw.Draw(canvas)

    for item in items:
        if item.kind == "strikethrough":
            _draw_strikethrough(canvas, item, dpi, ink_rgb, style.stroke_weight)
            continue

        if item.kind == "missing":
            if missing_char_mode == "blank":
                continue
            # Highlight missing char cleanly in editor preview
            font_px = max(8, int(round(item.font_size_pt * px_per_pt)))
            x0 = int(round(item.x_pt * px_per_pt))
            y_base = int(round(item.baseline_pt * px_per_pt))
            box_w = max(6, int(round(font_px * 0.86)))
            box_h = max(6, int(round(font_px * 0.92)))
            y0 = y_base - box_h + int(round(font_px * 0.1))
            draw.rectangle([x0, y0, x0 + box_w, y0 + box_h], outline=(225, 65, 65, 175), width=max(1, dpi // 110))
            ref_font = _get_ref_font(int(round(font_px * 0.78)))
            draw.text((x0 + 2, y0 + 1), item.char, font=ref_font, fill=(180, 60, 60, 145))
            continue

        if item.glyph_row is None:
            continue

        patch, unrotated_box_px = _render_deformed_glyph_rgba(
            item.glyph_row,
            style,
            item.progress,
            dpi,
            item.font_size_pt,
            item.token_seed,
            ink_rgb,
        )

        # Anchor horizontally using captured bbox_x0 so leading whitespace is stripped
        bbox_x0 = float(item.glyph_row["bbox_x0"])
        bbox_y1 = float(item.glyph_row["bbox_y1"])

        anchor_y_ratio = 0.84 if item.char in LOWER_PUNCT else (0.55 * 0.84 + 0.45 * bbox_y1)
        # Account for canvas expansion if rotated
        pad_x = (patch.width - unrotated_box_px) * 0.5
        pad_y = (patch.height - unrotated_box_px) * 0.5

        paste_x = int(round(item.x_pt * px_per_pt - bbox_x0 * unrotated_box_px - pad_x))
        paste_y = int(round(item.baseline_pt * px_per_pt - anchor_y_ratio * unrotated_box_px - pad_y))
        canvas.alpha_composite(patch, dest=(paste_x, paste_y))

        if item.is_ai_generated and missing_char_mode == "highlight":
            ux0 = int(round(item.x_pt * px_per_pt))
            ux1 = int(round((item.x_pt + max(item.width_pt, item.font_size_pt * 0.5)) * px_per_pt))
            uy = int(round((item.baseline_pt + item.font_size_pt * 0.08) * px_per_pt))
            dot_step = max(3, int(round(3.0 * px_per_pt)))
            dot_w = max(1, int(round(1.2 * px_per_pt)))
            for dx in range(ux0, ux1, dot_step * 2):
                draw.line([(dx, uy), (min(ux1, dx + dot_step), uy)], fill=(99, 102, 241, 170), width=dot_w)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue(), stats
