"""Tests for vector/raster layout detection and composite/overlay-only PDF export."""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import init_db
from app.models import ExportRequest, HandwritingStyle, PageMeta, RegionConfig
from app.services.glyph_store import get_glyphs_by_char
from app.services.layout_detector import detect_lines_in_region, detect_table_in_region
from app.services.pdf_exporter import export_project_pdf, generate_calibration_pdf


def _create_sample_template_pdf(path: Path) -> None:
    doc = pymupdf.open()
    # Page 0: 5 horizontal ruled lines spaced 24pt apart starting at y=120
    p0 = doc.new_page(width=595.28, height=841.89)
    for i in range(5):
        y = 120.0 + i * 24.0
        p0.draw_line(pymupdf.Point(70.0, y), pymupdf.Point(520.0, y), color=(0, 0, 0), width=0.8)

    # Page 1: 3x4 vector table at (80, 100, 440, 250)
    p1 = doc.new_page(width=595.28, height=841.89)
    x0, y0, x1, y1 = 80.0, 100.0, 440.0, 250.0
    p1.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=(0, 0, 0), width=0.8)
    for ry in (150.0, 200.0):
        p1.draw_line(pymupdf.Point(x0, ry), pymupdf.Point(x1, ry), color=(0, 0, 0), width=0.8)
    for cx in (170.0, 260.0, 350.0):
        p1.draw_line(pymupdf.Point(cx, y0), pymupdf.Point(cx, y1), color=(0, 0, 0), width=0.8)

    doc.save(str(path))
    doc.close()


def test_layout_detection_and_pdf_export(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITER_DATA_DIR", str(tmp_path))
    init_db()

    tpl_path = tmp_path / "sample_report.pdf"
    _create_sample_template_pdf(tpl_path)

    # 1. Detect ruled lines on page 0
    lines_res = detect_lines_in_region(str(tpl_path), 0, x=60.0, y=100.0, width=470.0, height=160.0)
    assert lines_res["method"] == "vector"
    assert len(lines_res["line_ys"]) == 5
    assert abs(lines_res["line_spacing"] - 24.0) <= 0.5
    assert abs(lines_res["baseline_offset"] - 20.0) <= 0.5

    # 2. Detect empty 3x4 vector table on page 1
    tbl_res = detect_table_in_region(str(tpl_path), 1, x=75.0, y=95.0, width=370.0, height=160.0)
    assert len(tbl_res["rows"]) == 4  # 3 rows -> 4 boundaries
    assert len(tbl_res["cols"]) == 5  # 4 cols -> 5 boundaries

    # 3. Export both composite and overlay_only PDFs
    pages_meta = [
        PageMeta(page_index=0, width_pt=595.28, height_pt=841.89),
        PageMeta(page_index=1, width_pt=595.28, height_pt=841.89),
    ]
    regions = [
        RegionConfig(id="r0", page_index=0, x=70, y=100, width=450, height=130, text="测试文本"),
    ]
    style = HandwritingStyle()
    glyphs_by_char = get_glyphs_by_char("default")

    comp_bytes = export_project_pdf(
        str(tpl_path),
        pages_meta,
        regions,
        style,
        glyphs_by_char,
        ExportRequest(dpi=300, mode="composite"),
    )
    comp_doc = pymupdf.open(stream=comp_bytes, filetype="pdf")
    assert len(comp_doc) == 2
    assert abs(comp_doc[0].rect.width - 595.28) < 0.5
    comp_doc.close()

    ovl_bytes = export_project_pdf(
        str(tpl_path),
        pages_meta,
        regions,
        style,
        glyphs_by_char,
        ExportRequest(dpi=300, mode="overlay_only", offset_x_mm=2.5, offset_y_mm=-1.5),
    )
    ovl_doc = pymupdf.open(stream=ovl_bytes, filetype="pdf")
    assert len(ovl_doc) == 2
    assert abs(ovl_doc[1].rect.height - 841.89) < 0.5
    ovl_doc.close()

    # 4. Calibration sheet PDF
    cal_bytes = generate_calibration_pdf()
    cal_doc = pymupdf.open(stream=cal_bytes, filetype="pdf")
    assert len(cal_doc) == 1
    cal_doc.close()
