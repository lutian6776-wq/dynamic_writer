"""Unit tests for handwriting layout, multi-variant rotation, mistakes, overflow, and missing chars."""

from __future__ import annotations

import io
import sys
import uuid
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_conn, init_db, now_iso
from app.models import HandwritingStyle, PageMeta, RegionConfig
from app.services.glyph_store import analyze_text_coverage, get_glyphs_by_char
from app.services.handwriting_engine import compute_document_placements, render_page_overlay


def _seed_synthetic_glyph(profile_id: str, char: str, out_dir: Path, variant_tag: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Draw distinct strokes per variant_tag so variants differ visibly
    offset = variant_tag * 6
    draw.line([(45 + offset, 60), (205 - offset, 68)], fill=(0, 0, 0, 240), width=16)
    draw.line([(125, 42), (120 + offset, 210)], fill=(0, 0, 0, 240), width=16)
    gid = uuid.uuid4().hex[:14]
    path = out_dir / f"{gid}.png"
    img.save(str(path))
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO glyphs (
                id, profile_id, char, source, image_path,
                bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                visual_width_ratio, visual_height_ratio, ink_center_y,
                sheet_id, created_at
            ) VALUES (?, ?, ?, 'tablet', ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (gid, profile_id, char, str(path), 0.18, 0.16, 0.80, 0.82, 0.62, 0.66, 0.49, now_iso()),
        )


def test_handwriting_engine_features(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITER_DATA_DIR", str(tmp_path))
    init_db()
    gdir = tmp_path / "glyphs" / "default"

    for ch in "实验数据测得结果错误正的，。":
        _seed_synthetic_glyph("default", ch, gdir, 0)
        if ch == "的":
            # Add 3 distinct variants for '的'
            _seed_synthetic_glyph("default", ch, gdir, 1)
            _seed_synthetic_glyph("default", ch, gdir, 2)

    glyphs_by_char = get_glyphs_by_char("default")
    cov = analyze_text_coverage("default", "实验的[错->正]缺")
    assert cov["missing_unique"] == 1
    assert cov["missing"][0]["char"] == "缺"

    pages = [
        PageMeta(page_index=0, width_pt=595.0, height_pt=842.0),
        PageMeta(page_index=1, width_pt=595.0, height_pt=842.0),
    ]

    # Region 1 on page 0 linked to Region 2 on page 1
    r1 = RegionConfig(
        id="r1",
        page_index=0,
        name="正文1",
        type="multi_line",
        x=60.0,
        y=80.0,
        width=200.0,
        height=45.0,  # Fits ~1-2 lines so rest overflows to page 1!
        font_size=18.0,
        line_spacing=24.0,
        baseline_offset=20.0,
        first_line_indent=36.0,
        next_region_id="r2",
        text="的的的实验[错->正]测得实验结果数据缺字继续写到下一页去吧。",
    )
    r2 = RegionConfig(
        id="r2",
        page_index=1,
        name="正文2",
        type="multi_line",
        x=60.0,
        y=80.0,
        width=400.0,
        height=200.0,
        font_size=18.0,
        line_spacing=24.0,
        baseline_offset=20.0,
        text="",
    )
    r_table = RegionConfig(
        id="t1",
        page_index=0,
        name="实验表格",
        type="table",
        x=60.0,
        y=300.0,
        width=300.0,
        height=120.0,
        font_size=16.0,
        table_rows=[0.0, 0.5, 1.0],
        table_cols=[0.0, 0.5, 1.0],
        text="实验\t数据\n测得\t结果",
    )

    style = HandwritingStyle(
        ink_color="#192742",
        elastic_intensity=0.35,
        fatigue_intensity=0.5,
        strikethrough_style="double_line",
        seed=123,
    )

    by_page, stats = compute_document_placements([r1, r2, r_table], style, glyphs_by_char)

    # Check multi-variant anti-repeat on '的'
    de_ids = [p.glyph_row["id"] for p in by_page[0] if p.char == "的" and p.glyph_row]
    assert len(de_ids) >= 2
    assert de_ids[0] != de_ids[1], "Consecutive '的' glyphs must pick different variants!"

    # Check strikethrough token was placed
    strikes = [p for p in by_page[0] if p.kind == "strikethrough"]
    assert len(strikes) == 1

    # Check overflow onto page 1 happened!
    assert 1 in by_page and len(by_page[1]) > 0

    # Check missing char counting ('缺', '字', '继', '续', '写', '到', '下', '一', '页', '去', '吧')
    assert stats["missing_unique"] >= 1

    # Verify blank vs highlight missing char rendering
    png_hl, _ = render_page_overlay(pages, [r1, r2, r_table], style, glyphs_by_char, 0, dpi=120, missing_char_mode="highlight")
    png_bl, _ = render_page_overlay(pages, [r1, r2, r_table], style, glyphs_by_char, 0, dpi=120, missing_char_mode="blank")

    arr_hl = np.asarray(Image.open(io.BytesIO(png_hl)).convert("RGBA"))
    arr_bl = np.asarray(Image.open(io.BytesIO(png_bl)).convert("RGBA"))
    # Highlight mode paints red reference boxes for missing chars, so red-channel alpha differs significantly
    red_only_diff = np.abs(arr_hl[:, :, 0].astype(int) - arr_bl[:, :, 0].astype(int)).sum()
    assert red_only_diff > 1000

    # Ensure 300 DPI export render runs cleanly
    png_300, _ = render_page_overlay(pages, [r1, r2, r_table], style, glyphs_by_char, 0, dpi=300, missing_char_mode="blank")
    im_300 = Image.open(io.BytesIO(png_300))
    assert im_300.size == (round(595.0 * 300 / 72), round(842.0 * 300 / 72))
