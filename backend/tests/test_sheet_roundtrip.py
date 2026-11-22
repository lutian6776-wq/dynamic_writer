"""End-to-end capture sheet roundtrip tests: generation, distortion, rectification, barcode, extraction."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image, ImageDraw
from skimage.transform import AffineTransform, warp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_conn, init_db
from app.services.sheet_extractor import (
    decode_header_barcode,
    detect_corner_markers,
    extract_from_upload,
    rectify_page,
)
from app.services.sheet_generator import generate_capture_sheet
from app.services.sheet_geometry import (
    A4_H_PX,
    A4_W_PX,
    MARKER_CENTERS_MM,
    MM_TO_PX,
    get_cell_rects_mm,
)


def test_sheet_roundtrip_with_scale_and_shift(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITER_DATA_DIR", str(tmp_path))
    init_db()

    chars = "实验报告目的原理步骤数据误差分析结论123456，。"
    high_freq = "实验的"
    sheet = generate_capture_sheet(
        profile_id="default",
        title="测试采集表",
        chars=chars,
        variants_per_char=1,
        high_freq_chars=high_freq,
        high_freq_variants=2,
    )
    sheet_id = sheet["sheet_id"]
    pdf_path = Path(sheet["pdf_path"])
    assert pdf_path.exists()
    assert sheet["total_slots"] == len(chars) + 3  # '实', '验', '的' got 2 variants

    # Render generated sheet PDF to 300 DPI image
    doc = pymupdf.open(str(pdf_path))
    pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(300 / 72, 300 / 72), colorspace=pymupdf.csRGB, alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()

    with get_conn() as conn:
        row = conn.execute("SELECT cells_json FROM capture_sheets WHERE sheet_id = ?", (sheet_id,)).fetchone()
    cells = json.loads(row["cells_json"])[0]
    assert len(cells) == sheet["total_slots"]

    # Programmatically write strokes into first 12 cells, leave remaining blank
    draw = ImageDraw.Draw(img)
    filled_count = 12
    for entry in cells[:filled_count]:
        _, box_mm = get_cell_rects_mm(entry["row"], entry["col"])
        x0 = box_mm[0] * MM_TO_PX
        y0 = box_mm[1] * MM_TO_PX
        w = (box_mm[2] - box_mm[0]) * MM_TO_PX
        h = (box_mm[3] - box_mm[1]) * MM_TO_PX
        # Draw simulated dark brush strokes (cross + loop) inside central region
        draw.line([(x0 + w * 0.25, y0 + h * 0.35), (x0 + w * 0.78, y0 + h * 0.38)], fill=(18, 20, 26), width=9)
        draw.line([(x0 + w * 0.50, y0 + h * 0.20), (x0 + w * 0.48, y0 + h * 0.80)], fill=(18, 20, 26), width=9)
        draw.arc([x0 + w * 0.30, y0 + h * 0.42, x0 + w * 0.72, y0 + h * 0.78], 0, 270, fill=(18, 20, 26), width=7)

    # Simulate tablet app export slight scaling + translation perturbation (0.97x scale, +18px X, +14px Y)
    arr = np.asarray(img, dtype=np.uint8)
    tform = AffineTransform(scale=(0.97, 0.97), translation=(18.0, 14.0))
    perturbed = warp(arr, tform.inverse, output_shape=(A4_H_PX, A4_W_PX), mode="constant", cval=1.0)
    perturbed_u8 = np.clip(perturbed * 255.0, 0, 255).astype(np.uint8)

    # Check marker detection accuracy (< 2px after inverse mapping)
    markers = detect_corner_markers(perturbed_u8)
    assert markers is not None
    expected_markers = np.array(
        [[mx * MM_TO_PX * 0.97 + 18.0, my * MM_TO_PX * 0.97 + 14.0] for mx, my in MARKER_CENTERS_MM]
    )
    errs = np.linalg.norm(markers - expected_markers, axis=1)
    assert float(errs.max()) < 2.0, f"Marker alignment error too high: {errs}"

    rectified = rectify_page(perturbed_u8, markers)
    decoded = decode_header_barcode(rectified)
    assert decoded == (sheet_id, 0)

    # Save perturbed image as PNG bytes and run full extraction API
    buf_path = tmp_path / "tablet_export.png"
    Image.fromarray(perturbed_u8).save(str(buf_path))

    res = extract_from_upload(buf_path.read_bytes(), "tablet_export.png", profile_id="default")
    assert res["sheet_ids"] == [sheet_id]
    assert res["pages_processed"] == 1
    assert res["extracted_count"] == filled_count
    assert res["skipped_blank_count"] == len(cells) - filled_count
    assert res["warnings"] == []

    # Verify extracted glyph PNGs have clean alpha (cyan guide removed) and valid tight bbox
    with get_conn() as conn:
        glyph_rows = conn.execute("SELECT * FROM glyphs WHERE sheet_id = ?", (sheet_id,)).fetchall()
    assert len(glyph_rows) == filled_count
    for gr in glyph_rows:
        p = Path(gr["image_path"])
        assert p.exists()
        g_img = Image.open(p).convert("RGBA")
        assert g_img.size == (256, 256)
        alpha = np.asarray(g_img.split()[-1])
        # Corner pixels near cyan guide border should be completely transparent
        assert int(alpha[2, 2]) == 0
        assert int(alpha[253, 253]) == 0
        # Stroke center must have strong ink opacity
        assert int(alpha.max()) > 200
        assert 0.35 <= gr["visual_width_ratio"] <= 0.70
        assert 0.40 <= gr["visual_height_ratio"] <= 0.75
