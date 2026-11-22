"""Generate A4 vector PDF capture sheets for EMR Android tablet handwriting input."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

import pymupdf

from app.config import ensure_data_dirs, get_reference_font_path, get_sheets_dir
from app.db import get_conn, now_iso
from app.services.sheet_geometry import (
    A4_H_PT,
    A4_W_PT,
    BARCODE_CELL_COUNT,
    BARCODE_CELL_GAP_MM,
    BARCODE_CELL_H_MM,
    BARCODE_CELL_W_MM,
    BARCODE_X_START_MM,
    BARCODE_Y_TOP_MM,
    CELLS_PER_PAGE,
    GRID_COLS,
    MARKER_CENTERS_MM,
    MARKER_INNER_MM,
    MARKER_MID_MM,
    MARKER_OUTER_MM,
    MM_TO_PT,
    get_cell_rects_mm,
    pack_sheet_code,
)


def _dedup_chars(raw: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for ch in raw:
        if not ch.isspace() and ch not in seen:
            seen.add(ch)
            out.append(ch)
    return out


def _mm_rect_to_pt(rect_mm: tuple[float, float, float, float]) -> pymupdf.Rect:
    x0, y0, x1, y1 = rect_mm
    return pymupdf.Rect(x0 * MM_TO_PT, y0 * MM_TO_PT, x1 * MM_TO_PT, y1 * MM_TO_PT)


def _centered_square_pt(cx_mm: float, cy_mm: float, size_mm: float) -> pymupdf.Rect:
    half = size_mm * 0.5
    return pymupdf.Rect(
        (cx_mm - half) * MM_TO_PT,
        (cy_mm - half) * MM_TO_PT,
        (cx_mm + half) * MM_TO_PT,
        (cy_mm + half) * MM_TO_PT,
    )


def generate_capture_sheet(
    profile_id: str,
    title: str,
    chars: str,
    variants_per_char: int = 1,
    high_freq_chars: str = "",
    high_freq_variants: int = 2,
) -> dict:
    """Create a multi-page A4 capture sheet PDF and register it in SQLite."""
    ensure_data_dirs()
    ordered_chars = _dedup_chars(chars)
    if not ordered_chars:
        raise ValueError("待采集字符列表不能为空")

    hf_set = set(_dedup_chars(high_freq_chars))
    slots: list[dict] = []
    for ch in ordered_chars:
        n_vars = max(variants_per_char, high_freq_variants) if ch in hf_set else variants_per_char
        for v in range(1, n_vars + 1):
            slots.append({"char": ch, "variant": v})

    page_count = max(1, math.ceil(len(slots) / CELLS_PER_PAGE))
    pages_cells: list[list[dict]] = []
    for page_idx in range(page_count):
        chunk = slots[page_idx * CELLS_PER_PAGE : (page_idx + 1) * CELLS_PER_PAGE]
        page_entries: list[dict] = []
        for slot_idx, item in enumerate(chunk):
            row, col = divmod(slot_idx, GRID_COLS)
            page_entries.append(
                {
                    "row": row,
                    "col": col,
                    "char": item["char"],
                    "variant": item["variant"],
                }
            )
        pages_cells.append(page_entries)

    created_at = now_iso()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO capture_sheets
                (profile_id, title, page_count, cells_json, pdf_path, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (profile_id, title, page_count, json.dumps(pages_cells, ensure_ascii=False), "", "generated", created_at),
        )
        sheet_id = int(cur.lastrowid)

    pdf_path = get_sheets_dir() / f"sheet_{sheet_id}.pdf"
    font_path = get_reference_font_path()
    doc = pymupdf.open()

    cyan_border = (165 / 255.0, 222 / 255.0, 240 / 255.0)
    cyan_guide = (205 / 255.0, 238 / 255.0, 248 / 255.0)
    label_bg = (0.945, 0.955, 0.965)
    label_border = (0.82, 0.85, 0.88)

    for page_idx, page_entries in enumerate(pages_cells):
        page = doc.new_page(width=A4_W_PT, height=A4_H_PT)
        page.insert_font(fontname="cjk", fontfile=font_path)

        # 1. Four concentric corner fiducial markers
        for cx_mm, cy_mm in MARKER_CENTERS_MM:
            page.draw_rect(
                _centered_square_pt(cx_mm, cy_mm, MARKER_OUTER_MM),
                color=None,
                fill=(0.0, 0.0, 0.0),
            )
            page.draw_rect(
                _centered_square_pt(cx_mm, cy_mm, MARKER_MID_MM),
                color=None,
                fill=(1.0, 1.0, 1.0),
            )
            page.draw_rect(
                _centered_square_pt(cx_mm, cy_mm, MARKER_INNER_MM),
                color=None,
                fill=(0.0, 0.0, 0.0),
            )

        # 2. Header 16-bit barcode with framing black calibration blocks
        code = pack_sheet_code(sheet_id, page_idx)
        for cell_idx in range(BARCODE_CELL_COUNT):
            bx0 = BARCODE_X_START_MM + cell_idx * (BARCODE_CELL_W_MM + BARCODE_CELL_GAP_MM)
            by0 = BARCODE_Y_TOP_MM
            brect = pymupdf.Rect(
                bx0 * MM_TO_PT,
                by0 * MM_TO_PT,
                (bx0 + BARCODE_CELL_W_MM) * MM_TO_PT,
                (by0 + BARCODE_CELL_H_MM) * MM_TO_PT,
            )
            if cell_idx == 0 or cell_idx == BARCODE_CELL_COUNT - 1:
                is_black = True
            else:
                bit_pos = 16 - cell_idx
                is_black = bool((code >> bit_pos) & 1)

            if is_black:
                page.draw_rect(brect, color=None, fill=(0.0, 0.0, 0.0))

        # Header human-readable title & instructions
        barcode_end_mm = BARCODE_X_START_MM + BARCODE_CELL_COUNT * (BARCODE_CELL_W_MM + BARCODE_CELL_GAP_MM) + 2.0
        header_rect = pymupdf.Rect(
            barcode_end_mm * MM_TO_PT,
            7.2 * MM_TO_PT,
            188.0 * MM_TO_PT,
            17.0 * MM_TO_PT,
        )
        page.insert_textbox(
            header_rect,
            f"采集表 #{sheet_id}  第 {page_idx + 1}/{page_count} 页\n{title[:24]}（请在浅青格内手写，勿遮挡四角方块）",
            fontname="cjk",
            fontsize=8.2,
            color=(0.22, 0.25, 0.30),
            align=pymupdf.TEXT_ALIGN_LEFT,
        )

        # 3. Character cells
        for entry in page_entries:
            row = entry["row"]
            col = entry["col"]
            ch = entry["char"]
            var_idx = entry["variant"]
            label_rect_mm, box_rect_mm = get_cell_rects_mm(row, col)
            label_rect = _mm_rect_to_pt(label_rect_mm)
            box_rect = _mm_rect_to_pt(box_rect_mm)

            # Label bar above box (printed dark reference character)
            page.draw_rect(label_rect, color=label_border, fill=label_bg, width=0.4)
            label_str = ch if var_idx == 1 else f"{ch} #{var_idx}"
            # Nudge text rect slightly down to optically center inside 5.6mm label strip
            text_rect = pymupdf.Rect(label_rect.x0 + 1.0, label_rect.y0 + 1.6, label_rect.x1 - 1.0, label_rect.y1)
            page.insert_textbox(
                text_rect,
                label_str,
                fontname="cjk",
                fontsize=10.5,
                color=(0.12, 0.14, 0.18),
                align=pymupdf.TEXT_ALIGN_CENTER,
            )

            # Light cyan writing box + inner crosshair guide
            cx = (box_rect.x0 + box_rect.x1) * 0.5
            cy = (box_rect.y0 + box_rect.y1) * 0.5
            page.draw_line(
                pymupdf.Point(box_rect.x0 + 2.0, cy),
                pymupdf.Point(box_rect.x1 - 2.0, cy),
                color=cyan_guide,
                width=0.45,
                dashes="[2 2] 0",
            )
            page.draw_line(
                pymupdf.Point(cx, box_rect.y0 + 2.0),
                pymupdf.Point(cx, box_rect.y1 - 2.0),
                color=cyan_guide,
                width=0.45,
                dashes="[2 2] 0",
            )
            page.draw_rect(box_rect, color=cyan_border, fill=None, width=0.8)

        # Subtle footer note
        footer_rect = pymupdf.Rect(18.0 * MM_TO_PT, 281.0 * MM_TO_PT, 192.0 * MM_TO_PT, 289.0 * MM_TO_PT)
        page.insert_textbox(
            footer_rect,
            f"共 {len(slots)} 格 · 可只写部分格子，空白格会自动跳过 · 建议使用黑色或深色中性笔迹笔刷",
            fontname="cjk",
            fontsize=7.5,
            color=(0.45, 0.48, 0.54),
            align=pymupdf.TEXT_ALIGN_CENTER,
        )

    doc.save(str(pdf_path), deflate=True)
    doc.close()

    with get_conn() as conn:
        conn.execute(
            "UPDATE capture_sheets SET pdf_path = ? WHERE sheet_id = ?",
            (str(pdf_path), sheet_id),
        )

    return {
        "sheet_id": sheet_id,
        "profile_id": profile_id,
        "title": title,
        "page_count": page_count,
        "total_slots": len(slots),
        "unique_chars": len(ordered_chars),
        "pdf_path": str(pdf_path),
        "created_at": created_at,
    }


def list_capture_sheets(profile_id: Optional[str] = None) -> list[dict]:
    """List generated capture sheets from SQLite."""
    with get_conn() as conn:
        if profile_id:
            rows = conn.execute(
                "SELECT sheet_id, profile_id, title, page_count, status, created_at FROM capture_sheets WHERE profile_id = ? ORDER BY sheet_id DESC",
                (profile_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT sheet_id, profile_id, title, page_count, status, created_at FROM capture_sheets ORDER BY sheet_id DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def get_capture_sheet_record(sheet_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM capture_sheets WHERE sheet_id = ?", (sheet_id,)).fetchone()
    return dict(row) if row else None
