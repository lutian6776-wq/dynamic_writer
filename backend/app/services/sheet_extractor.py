"""Rectify tablet-exported capture sheets, decode barcode, strip cyan guides, and extract glyph PNGs."""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path
from typing import Optional

import numpy as np
import pymupdf
from PIL import Image
from skimage.measure import label, regionprops
from skimage.transform import ProjectiveTransform, warp

from app.config import ensure_data_dirs, get_glyphs_dir
from app.db import get_conn, now_iso
from app.services.sheet_geometry import (
    A4_H_PX,
    A4_W_PX,
    BARCODE_CELL_COUNT,
    BARCODE_CELL_GAP_MM,
    BARCODE_CELL_H_MM,
    BARCODE_CELL_W_MM,
    BARCODE_X_START_MM,
    BARCODE_Y_TOP_MM,
    EXTRACTION_DPI,
    MARKER_CENTERS_MM,
    MM_TO_PX,
    get_cell_rects_mm,
    unpack_sheet_code,
)

GLYPH_CANVAS_SIZE = 256


def _render_upload_to_pages(file_bytes: bytes, filename: str) -> list[np.ndarray]:
    """Convert uploaded PDF or image bytes into a list of RGB uint8 numpy arrays."""
    suffix = Path(filename).suffix.lower()
    pages: list[np.ndarray] = []
    if suffix == ".pdf":
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        try:
            scale = EXTRACTION_DPI / 72.0
            mat = pymupdf.Matrix(scale, scale)
            for page in doc:
                pix = page.get_pixmap(matrix=mat, colorspace=pymupdf.csRGB, alpha=False)
                arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()
                pages.append(arr)
        finally:
            doc.close()
    else:
        img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        pages.append(np.asarray(img, dtype=np.uint8))
    return pages


def detect_corner_markers(rgb: np.ndarray) -> Optional[np.ndarray]:
    """
    Detect the 4 concentric square fiducial markers (TL, TR, BR, BL).
    Returns a (4, 2) float64 array of (x, y) pixel centers, or None if not all 4 found.
    """
    h, w = rgb.shape[:2]
    gray = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
    dark = gray < 145.0
    labeled = label(dark, connectivity=2)
    props = regionprops(labeled)

    min_bw = max(14.0, 0.015 * w)
    max_bw = 0.14 * w

    candidates: list[tuple[float, float, float]] = []  # (cx, cy, score)
    for p in props:
        minr, minc, maxr, maxc = p.bbox
        bh = float(maxr - minr)
        bw = float(maxc - minc)
        if bw < min_bw or bw > max_bw:
            continue
        aspect = bh / max(bw, 1.0)
        if aspect < 0.72 or aspect > 1.38:
            continue
        if p.euler_number > 0:
            continue
        fill_ratio = float(p.area) / (bw * bh)
        if fill_ratio < 0.25 or fill_ratio > 0.85:
            continue

        # Inspect central 56% subwindow for the inner concentric square
        pad_r = int(round(0.22 * bh))
        pad_c = int(round(0.22 * bw))
        sub = dark[minr + pad_r : maxr - pad_r, minc + pad_c : maxc - pad_c]
        if sub.size == 0:
            continue
        sub_lbl = label(sub, connectivity=2)
        sub_props = regionprops(sub_lbl)
        outer_cx = 0.5 * (minc + maxc)
        outer_cy = 0.5 * (minr + maxr)
        sub_h, sub_w = sub.shape

        best_inner = None
        for sp in sub_props:
            s_minr, s_minc, s_maxr, s_maxc = sp.bbox
            # Ignore components touching the outer ring border of the subwindow
            if s_minr == 0 or s_minc == 0 or s_maxr == sub_h or s_maxc == sub_w:
                continue
            area_ratio = float(sp.area) / (bw * bh)
            if area_ratio < 0.03 or area_ratio > 0.24:
                continue
            in_cy, in_cx = sp.centroid
            abs_cx = (minc + pad_c) + in_cx
            abs_cy = (minr + pad_r) + in_cy
            dist = float(np.hypot(abs_cx - outer_cx, abs_cy - outer_cy))
            if dist <= 0.18 * bw:
                best_inner = (0.5 * (outer_cx + abs_cx), 0.5 * (outer_cy + abs_cy), area_ratio, dist)
                break

        if best_inner is not None:
            cx, cy, area_ratio, dist = best_inner
            # Score favors expected area_ratio ~0.09, square aspect ~1.0, low center offset
            score = abs(area_ratio - 0.09) * 10.0 + abs(aspect - 1.0) + dist / max(bw, 1.0)
            candidates.append((cx, cy, score))

    if len(candidates) < 4:
        return None

    mid_x = w * 0.5
    mid_y = h * 0.5
    quadrants: list[list[tuple[float, float, float]]] = [[], [], [], []]
    for cx, cy, score in candidates:
        if cx < mid_x and cy < mid_y:
            quadrants[0].append((cx, cy, score))
        elif cx >= mid_x and cy < mid_y:
            quadrants[1].append((cx, cy, score))
        elif cx >= mid_x and cy >= mid_y:
            quadrants[2].append((cx, cy, score))
        else:
            quadrants[3].append((cx, cy, score))

    if any(len(q) == 0 for q in quadrants):
        return None

    # Expected relative marker locations to break ties if user accidentally drew a nested square elsewhere
    expected_norm = [
        (MARKER_CENTERS_MM[0][0] / 210.0, MARKER_CENTERS_MM[0][1] / 297.0),
        (MARKER_CENTERS_MM[1][0] / 210.0, MARKER_CENTERS_MM[1][1] / 297.0),
        (MARKER_CENTERS_MM[2][0] / 210.0, MARKER_CENTERS_MM[2][1] / 297.0),
        (MARKER_CENTERS_MM[3][0] / 210.0, MARKER_CENTERS_MM[3][1] / 297.0),
    ]

    chosen: list[tuple[float, float]] = []
    for q_idx, q_cands in enumerate(quadrants):
        ex, ey = expected_norm[q_idx]
        best = min(
            q_cands,
            key=lambda c: c[2] + 3.0 * float(np.hypot(c[0] / w - ex, c[1] / h - ey)),
        )
        chosen.append((best[0], best[1]))

    return np.array(chosen, dtype=np.float64)


def rectify_page(rgb: np.ndarray, src_pts: np.ndarray) -> np.ndarray:
    """Warp detected page into canonical 300 DPI A4 dimensions using projective transform."""
    dst_pts = np.array(
        [[mx * MM_TO_PX, my * MM_TO_PX] for mx, my in MARKER_CENTERS_MM],
        dtype=np.float64,
    )
    tform = ProjectiveTransform.from_estimate(dst_pts, src_pts)
    warped = warp(
        rgb,
        tform,
        output_shape=(A4_H_PX, A4_W_PX),
        order=1,
        mode="constant",
        cval=1.0,
        preserve_range=False,
    )
    return np.clip(warped * 255.0, 0, 255).astype(np.uint8)


def decode_header_barcode(rectified_rgb: np.ndarray) -> Optional[tuple[int, int]]:
    """Decode the 16-bit header barcode into (sheet_id, page_index)."""
    gray = 0.299 * rectified_rgb[:, :, 0] + 0.587 * rectified_rgb[:, :, 1] + 0.114 * rectified_rgb[:, :, 2]

    cell_means: list[float] = []
    for idx in range(BARCODE_CELL_COUNT):
        x0_mm = BARCODE_X_START_MM + idx * (BARCODE_CELL_W_MM + BARCODE_CELL_GAP_MM)
        y0_mm = BARCODE_Y_TOP_MM
        # Sample central 50% of each cell to tolerate slight sub-pixel registration jitter
        cx0 = int(round((x0_mm + BARCODE_CELL_W_MM * 0.25) * MM_TO_PX))
        cx1 = int(round((x0_mm + BARCODE_CELL_W_MM * 0.75) * MM_TO_PX))
        cy0 = int(round((y0_mm + BARCODE_CELL_H_MM * 0.25) * MM_TO_PX))
        cy1 = int(round((y0_mm + BARCODE_CELL_H_MM * 0.75) * MM_TO_PX))
        patch = gray[cy0:cy1, cx0:cx1]
        if patch.size == 0:
            return None
        cell_means.append(float(np.mean(patch)))

    black_ref = 0.5 * (cell_means[0] + cell_means[-1])
    # Sample white paper strip 2mm below the barcode
    wy0 = int(round((BARCODE_Y_TOP_MM + BARCODE_CELL_H_MM + 1.5) * MM_TO_PX))
    wy1 = int(round((BARCODE_Y_TOP_MM + BARCODE_CELL_H_MM + 4.0) * MM_TO_PX))
    wx0 = int(round(BARCODE_X_START_MM * MM_TO_PX))
    wx1 = int(round((BARCODE_X_START_MM + 60.0) * MM_TO_PX))
    white_ref = float(np.percentile(gray[wy0:wy1, wx0:wx1], 80))

    if white_ref - black_ref < 40.0:
        return None

    threshold = 0.5 * (black_ref + white_ref)
    code = 0
    for bit_idx in range(1, BARCODE_CELL_COUNT - 1):
        is_black = cell_means[bit_idx] < threshold
        code = (code << 1) | (1 if is_black else 0)

    return unpack_sheet_code(code)


def extract_cell_alpha(cell_rgb: np.ndarray) -> Optional[dict]:
    """
    Strip cyan guide lines from a single cell crop and extract anti-aliased ink alpha + metrics.
    Returns None if cell is blank.
    """
    arr = cell_rgb.astype(np.float32)
    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]

    # Mask light-cyan grid & crosshair guides while preserving neutral/dark/blue-black pen ink
    cyan_guide = ((b - r) > 18.0) & (g > 170.0) & (b > 180.0)
    cyan_halo = ((b - r) > 11.0) & (b > 202.0) & (g > 195.0)
    clean_rgb = arr.copy()
    clean_rgb[cyan_guide | cyan_halo] = 255.0

    luma = 0.299 * clean_rgb[:, :, 0] + 0.587 * clean_rgb[:, :, 1] + 0.114 * clean_rgb[:, :, 2]
    bg = float(np.clip(np.percentile(luma, 92), 215.0, 255.0))
    denom = max(bg - 55.0, 75.0)
    alpha = np.clip((bg - 12.0 - luma) / denom, 0.0, 1.0)
    alpha[alpha < 0.06] = 0.0

    # Blank cell check
    if int(np.count_nonzero(alpha > 0.22)) < 28:
        return None

    ys, xs = np.where(alpha > 0.12)
    if ys.size == 0 or xs.size == 0:
        return None

    h, w = alpha.shape
    bbox_x0 = float(xs.min()) / w
    bbox_y0 = float(ys.min()) / h
    bbox_x1 = float(xs.max() + 1) / w
    bbox_y1 = float(ys.max() + 1) / h

    weights = alpha[ys, xs]
    weight_sum = float(np.sum(weights))
    ink_center_y = float(np.sum(ys * weights) / max(weight_sum, 1e-6)) / h

    # Resize full writing box proportionally to 256x256 so relative character size is preserved
    alpha_u8 = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    alpha_img = Image.fromarray(alpha_u8, mode="L").resize(
        (GLYPH_CANVAS_SIZE, GLYPH_CANVAS_SIZE),
        Image.Resampling.LANCZOS,
    )
    rgba = Image.new("RGBA", (GLYPH_CANVAS_SIZE, GLYPH_CANVAS_SIZE), (0, 0, 0, 0))
    rgba.putalpha(alpha_img)

    return {
        "rgba_image": rgba,
        "bbox_x0": bbox_x0,
        "bbox_y0": bbox_y0,
        "bbox_x1": bbox_x1,
        "bbox_y1": bbox_y1,
        "visual_width_ratio": max(0.05, bbox_x1 - bbox_x0),
        "visual_height_ratio": max(0.05, bbox_y1 - bbox_y0),
        "ink_center_y": ink_center_y,
    }


def extract_from_upload(
    file_bytes: bytes,
    filename: str,
    profile_id: str = "default",
    override_sheet_id: Optional[int] = None,
    override_page_index: Optional[int] = None,
) -> dict:
    """Process an uploaded PDF/image capture sheet and persist extracted glyphs."""
    ensure_data_dirs()
    raw_pages = _render_upload_to_pages(file_bytes, filename)
    if not raw_pages:
        raise ValueError("上传文件中未检测到有效页面")

    profile_dir = get_glyphs_dir() / profile_id
    profile_dir.mkdir(parents=True, exist_ok=True)

    extracted_glyphs: list[dict] = []
    skipped_blank_count = 0
    warnings: list[str] = []
    decoded_sheet_ids: set[int] = set()
    pages_processed = 0

    for idx, page_rgb in enumerate(raw_pages):
        markers = detect_corner_markers(page_rgb)
        if markers is not None:
            rectified = rectify_page(page_rgb, markers)
        elif override_sheet_id is not None:
            rectified = np.asarray(
                Image.fromarray(page_rgb).resize((A4_W_PX, A4_H_PX), Image.Resampling.LANCZOS),
                dtype=np.uint8,
            )
            warnings.append(f"第 {idx + 1} 页未检测到完整四角定位标，已按整页缩放降级切字")
        else:
            warnings.append(f"第 {idx + 1} 页未检测到完整四角定位标，已跳过")
            continue

        decoded = decode_header_barcode(rectified)
        if override_sheet_id is not None:
            sheet_id = override_sheet_id
            page_index = override_page_index if override_page_index is not None else idx
        elif decoded is not None:
            sheet_id, page_index = decoded
        else:
            warnings.append(f"第 {idx + 1} 页未能识别页眉采集表编号，可尝试手动指定 Sheet ID")
            continue

        with get_conn() as conn:
            row = conn.execute(
                "SELECT cells_json FROM capture_sheets WHERE sheet_id = ?",
                (sheet_id,),
            ).fetchone()
        if row is None:
            warnings.append(f"数据库中未找到采集表 #{sheet_id}")
            continue

        pages_cells = json.loads(row["cells_json"])
        if page_index < 0 or page_index >= len(pages_cells):
            warnings.append(f"采集表 #{sheet_id} 不存在第 {page_index + 1} 页")
            continue

        decoded_sheet_ids.add(sheet_id)
        pages_processed += 1
        page_entries = pages_cells[page_index]
        created_at = now_iso()

        with get_conn() as conn:
            for entry in page_entries:
                _, box_mm = get_cell_rects_mm(entry["row"], entry["col"])
                x0 = int(round(box_mm[0] * MM_TO_PX)) + 5
                y0 = int(round(box_mm[1] * MM_TO_PX)) + 5
                x1 = int(round(box_mm[2] * MM_TO_PX)) - 5
                y1 = int(round(box_mm[3] * MM_TO_PX)) - 5

                crop = rectified[y0:y1, x0:x1]
                result = extract_cell_alpha(crop)
                if result is None:
                    skipped_blank_count += 1
                    continue

                glyph_id = uuid.uuid4().hex[:16]
                out_path = profile_dir / f"{glyph_id}.png"
                result["rgba_image"].save(str(out_path), format="PNG")

                conn.execute(
                    """
                    INSERT INTO glyphs (
                        id, profile_id, char, source, image_path,
                        bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                        visual_width_ratio, visual_height_ratio, ink_center_y,
                        sheet_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        glyph_id,
                        profile_id,
                        entry["char"],
                        "tablet",
                        str(out_path),
                        result["bbox_x0"],
                        result["bbox_y0"],
                        result["bbox_x1"],
                        result["bbox_y1"],
                        result["visual_width_ratio"],
                        result["visual_height_ratio"],
                        result["ink_center_y"],
                        sheet_id,
                        created_at,
                    ),
                )

                extracted_glyphs.append(
                    {
                        "id": glyph_id,
                        "char": entry["char"],
                        "variant": entry["variant"],
                        "image_url": f"/api/glyphs/{glyph_id}/image",
                    }
                )

            conn.execute(
                "UPDATE capture_sheets SET status = 'imported' WHERE sheet_id = ?",
                (sheet_id,),
            )

    return {
        "sheet_ids": sorted(decoded_sheet_ids),
        "pages_processed": pages_processed,
        "extracted_count": len(extracted_glyphs),
        "skipped_blank_count": skipped_blank_count,
        "extracted_glyphs": extracted_glyphs,
        "warnings": warnings,
    }
