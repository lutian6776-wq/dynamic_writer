"""Automatic horizontal ruled-line and table grid detection for PDF and image templates."""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pymupdf
from scipy.signal import find_peaks


def _cluster_coords(vals: Sequence[float], tol: float = 2.5) -> list[float]:
    if not vals:
        return []
    sorted_vals = sorted(vals)
    clusters: list[list[float]] = [[sorted_vals[0]]]
    for v in sorted_vals[1:]:
        if v - clusters[-1][-1] <= tol:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return [float(sum(c) / len(c)) for c in clusters]


def _overlap_len(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def detect_lines_in_region(
    template_path: str,
    page_index: int,
    x: float,
    y: float,
    width: float,
    height: float,
) -> dict:
    """
    Detect horizontal ruled lines inside (x, y, width, height) in PDF pt coordinates.
    Prefers exact vector drawings from PyMuPDF; falls back to raster projection peaks.
    """
    x0, y0, x1, y1 = x, y, x + width, y + height
    min_h_overlap = max(12.0, width * 0.25)

    doc = pymupdf.open(template_path)
    try:
        if page_index < 0 or page_index >= len(doc):
            raise IndexError(f"Page index {page_index} out of range")
        page = doc[page_index]

        vector_ys: list[float] = []
        for path in page.get_drawings():
            for item in path.get("items", []):
                kind = item[0]
                if kind == "l":
                    p1, p2 = item[1], item[2]
                    if abs(p1.y - p2.y) <= 1.5:
                        lx0, lx1 = min(p1.x, p2.x), max(p1.x, p2.x)
                        ly = 0.5 * (p1.y + p2.y)
                        if (y0 + 2.0) <= ly <= (y1 + 3.0) and _overlap_len(lx0, lx1, x0, x1) >= min_h_overlap:
                            vector_ys.append(float(ly))
                elif kind == "re":
                    r = item[1]
                    if r.height <= 2.5 and _overlap_len(r.x0, r.x1, x0, x1) >= min_h_overlap:
                        ly = 0.5 * (r.y0 + r.y1)
                        if (y0 + 2.0) <= ly <= (y1 + 3.0):
                            vector_ys.append(float(ly))

        clustered = _cluster_coords(vector_ys, tol=2.5)
        if len(clustered) >= 2:
            diffs = np.diff(clustered)
            spacing = float(np.median(diffs))
            baseline_offset = float(clustered[0] - y0)
            return {
                "line_ys": [round(v, 2) for v in clustered],
                "line_spacing": round(max(8.0, spacing), 2),
                "baseline_offset": round(max(4.0, baseline_offset), 2),
                "method": "vector",
            }

        # Raster projection fallback (scanned PDF or image converted to PDF)
        dpi = 150.0
        scale = dpi / 72.0
        clip = pymupdf.Rect(x0, y0, x1, y1) & page.rect
        if clip.is_empty or clip.width < 4 or clip.height < 4:
            return {"line_ys": [], "line_spacing": 24.0, "baseline_offset": 20.0, "method": "fallback"}

        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip, colorspace=pymupdf.csGRAY, alpha=False)
        gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
        proj = (gray < 185).mean(axis=1)
        min_dist = max(8, int(round(10.0 * scale)))
        peaks, _ = find_peaks(proj, distance=min_dist, prominence=0.16, height=0.18)

        raster_ys = [float(clip.y0 + p / scale) for p in peaks if (clip.y0 + p / scale) >= (y0 + 2.0)]
        if len(raster_ys) >= 2:
            diffs = np.diff(raster_ys)
            spacing = float(np.median(diffs))
            baseline_offset = float(raster_ys[0] - y0)
            return {
                "line_ys": [round(v, 2) for v in raster_ys],
                "line_spacing": round(max(8.0, spacing), 2),
                "baseline_offset": round(max(4.0, baseline_offset), 2),
                "method": "raster",
            }
        elif len(raster_ys) == 1:
            return {
                "line_ys": [round(raster_ys[0], 2)],
                "line_spacing": 24.0,
                "baseline_offset": round(max(4.0, raster_ys[0] - y0), 2),
                "method": "raster",
            }
    finally:
        doc.close()

    return {"line_ys": [], "line_spacing": 24.0, "baseline_offset": 20.0, "method": "none"}


def _normalize_edges(edges: list[float], start: float, span: float) -> list[float]:
    if span <= 1.0:
        return [0.0, 1.0]
    norm = [max(0.0, min(1.0, (e - start) / span)) for e in edges]
    norm = _cluster_coords(norm, tol=0.025)
    if not norm or norm[0] > 0.04:
        norm.insert(0, 0.0)
    else:
        norm[0] = 0.0
    if norm[-1] < 0.96:
        norm.append(1.0)
    else:
        norm[-1] = 1.0
    return [round(v, 4) for v in norm]


def detect_table_in_region(
    template_path: str,
    page_index: int,
    x: float,
    y: float,
    width: float,
    height: float,
) -> dict:
    """
    Detect table row and column boundaries inside (x, y, width, height) in PDF pt coordinates.
    Returns normalized [0.0 .. 1.0] split ratios `rows` and `cols`.
    """
    x0, y0, x1, y1 = x, y, x + width, y + height
    clip = pymupdf.Rect(x0 - 3.0, y0 - 3.0, x1 + 3.0, y1 + 3.0)

    doc = pymupdf.open(template_path)
    try:
        if page_index < 0 or page_index >= len(doc):
            raise IndexError(f"Page index {page_index} out of range")
        page = doc[page_index]
        clip = clip & page.rect

        # Strategy 1: PyMuPDF find_tables (works well when table cells contain text)
        tabs = page.find_tables(clip=clip, strategy="lines")
        if tabs.tables:
            t = tabs.tables[0]
            raw_ys: list[float] = []
            raw_xs: list[float] = []
            for row in t.rows:
                for cell in row.cells:
                    if cell is not None:
                        cx0, cy0, cx1, cy1 = cell
                        raw_xs.extend([cx0, cx1])
                        raw_ys.extend([cy0, cy1])
            ys = _cluster_coords(raw_ys, tol=2.5)
            xs = _cluster_coords(raw_xs, tol=2.5)
            if len(ys) >= 2 and len(xs) >= 2:
                return {
                    "rows": _normalize_edges(ys, y0, height),
                    "cols": _normalize_edges(xs, x0, width),
                    "method": "find_tables",
                }

        # Strategy 2: Vector drawings inside region (handles blank lab-report grids cleanly!)
        min_h_len = max(12.0, width * 0.25)
        min_v_len = max(10.0, height * 0.25)
        vec_ys: list[float] = []
        vec_xs: list[float] = []
        for path in page.get_drawings():
            for item in path.get("items", []):
                kind = item[0]
                if kind == "l":
                    p1, p2 = item[1], item[2]
                    if abs(p1.y - p2.y) <= 1.5 and _overlap_len(min(p1.x, p2.x), max(p1.x, p2.x), x0, x1) >= min_h_len:
                        ly = 0.5 * (p1.y + p2.y)
                        if (y0 - 3.0) <= ly <= (y1 + 3.0):
                            vec_ys.append(float(ly))
                    elif abs(p1.x - p2.x) <= 1.5 and _overlap_len(min(p1.y, p2.y), max(p1.y, p2.y), y0, y1) >= min_v_len:
                        lx = 0.5 * (p1.x + p2.x)
                        if (x0 - 3.0) <= lx <= (x1 + 3.0):
                            vec_xs.append(float(lx))
                elif kind == "re":
                    r = item[1]
                    if _overlap_len(r.x0, r.x1, x0, x1) >= min_h_len:
                        if (y0 - 3.0) <= r.y0 <= (y1 + 3.0):
                            vec_ys.append(float(r.y0))
                        if (y0 - 3.0) <= r.y1 <= (y1 + 3.0):
                            vec_ys.append(float(r.y1))
                    if _overlap_len(r.y0, r.y1, y0, y1) >= min_v_len:
                        if (x0 - 3.0) <= r.x0 <= (x1 + 3.0):
                            vec_xs.append(float(r.x0))
                        if (x0 - 3.0) <= r.x1 <= (x1 + 3.0):
                            vec_xs.append(float(r.x1))

        ys = _cluster_coords(vec_ys, tol=2.5)
        xs = _cluster_coords(vec_xs, tol=2.5)
        if len(ys) >= 3 and len(xs) >= 3:
            return {
                "rows": _normalize_edges(ys, y0, height),
                "cols": _normalize_edges(xs, x0, width),
                "method": "vector",
            }

        # Strategy 3: Raster dark-pixel projection fallback
        dpi = 150.0
        scale = dpi / 72.0
        if not clip.is_empty and clip.width >= 4 and clip.height >= 4:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip, colorspace=pymupdf.csGRAY, alpha=False)
            gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
            dark = gray < 185
            h_proj = dark.mean(axis=1)
            v_proj = dark.mean(axis=0)
            h_peaks, _ = find_peaks(h_proj, distance=max(8, int(10 * scale)), prominence=0.20, height=0.22)
            v_peaks, _ = find_peaks(v_proj, distance=max(8, int(10 * scale)), prominence=0.20, height=0.22)
            r_ys = [float(clip.y0 + p / scale) for p in h_peaks]
            r_xs = [float(clip.x0 + p / scale) for p in v_peaks]
            if len(r_ys) >= 2 or len(r_xs) >= 2:
                rows_out = _normalize_edges(r_ys, y0, height) if len(r_ys) >= 2 else [0.0, 0.5, 1.0]
                cols_out = _normalize_edges(r_xs, x0, width) if len(r_xs) >= 2 else [0.0, 0.5, 1.0]
                return {"rows": rows_out, "cols": cols_out, "method": "raster"}
    finally:
        doc.close()

    return {"rows": [0.0, 0.5, 1.0], "cols": [0.0, 0.5, 1.0], "method": "default"}
