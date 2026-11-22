"""High-DPI composite & overlay-only PDF export plus millimeter calibration sheet."""

from __future__ import annotations

import pymupdf

from app.config import get_reference_font_path
from app.models import ExportRequest, HandwritingStyle, PageMeta, RegionConfig
from app.services.handwriting_engine import compute_document_placements, render_page_overlay
from app.services.sheet_geometry import A4_H_MM, A4_H_PT, A4_W_MM, A4_W_PT, MM_TO_PT


def export_project_pdf(
    template_path: str,
    pages_meta: list[PageMeta],
    regions: list[RegionConfig],
    style: HandwritingStyle,
    glyphs_by_char: dict[str, list[dict]],
    export_req: ExportRequest,
) -> bytes:
    """
    Export final PDF at 300/600 DPI in either:
      - `composite`: vector original template + lossless handwriting overlay PNG
      - `overlay_only`: blank pages with handwriting overlay shifted by (offset_x_mm, offset_y_mm)
    """
    precomputed = compute_document_placements(regions, style, glyphs_by_char)

    if export_req.mode == "composite":
        doc = pymupdf.open(template_path)
        try:
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                overlay_png, _ = render_page_overlay(
                    pages_meta=pages_meta,
                    regions=regions,
                    style=style,
                    glyphs_by_char=glyphs_by_char,
                    page_index=page_idx,
                    dpi=export_req.dpi,
                    missing_char_mode=export_req.missing_char_mode,
                    precomputed=precomputed,
                )
                page.insert_image(page.rect, stream=overlay_png, overlay=True)
            return doc.tobytes(deflate=True)
        finally:
            doc.close()

    # Pure handwriting overlay mode for feeding pre-printed paper sheets
    out_doc = pymupdf.open()
    try:
        dx_pt = export_req.offset_x_mm * MM_TO_PT
        dy_pt = export_req.offset_y_mm * MM_TO_PT
        for page_idx, pm in enumerate(pages_meta):
            page = out_doc.new_page(width=pm.width_pt, height=pm.height_pt)
            overlay_png, _ = render_page_overlay(
                pages_meta=pages_meta,
                regions=regions,
                style=style,
                glyphs_by_char=glyphs_by_char,
                page_index=page_idx,
                dpi=export_req.dpi,
                missing_char_mode=export_req.missing_char_mode,
                precomputed=precomputed,
            )
            target_rect = pymupdf.Rect(dx_pt, dy_pt, pm.width_pt + dx_pt, pm.height_pt + dy_pt)
            page.insert_image(target_rect, stream=overlay_png, overlay=True)
        return out_doc.tobytes(deflate=True)
    finally:
        out_doc.close()


def generate_calibration_pdf() -> bytes:
    """Generate a 1-page A4 millimeter calibration target for pre-printed paper overlay printing."""
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=A4_W_PT, height=A4_H_PT)
        page.insert_font(fontname="cjk", fontfile=get_reference_font_path())

        # 20mm inset frame
        inset = 20.0 * MM_TO_PT
        frame = pymupdf.Rect(inset, inset, A4_W_PT - inset, A4_H_PT - inset)
        page.draw_rect(frame, color=(0.15, 0.25, 0.45), width=0.8)

        # Center crosshair at (105mm, 148.5mm)
        cx = (A4_W_MM * 0.5) * MM_TO_PT
        cy = (A4_H_MM * 0.5) * MM_TO_PT
        span = 22.0 * MM_TO_PT
        page.draw_line(pymupdf.Point(cx - span, cy), pymupdf.Point(cx + span, cy), color=(0.85, 0.15, 0.15), width=0.8)
        page.draw_line(pymupdf.Point(cx, cy - span), pymupdf.Point(cx, cy + span), color=(0.85, 0.15, 0.15), width=0.8)

        # Ruler ticks (-15mm to +15mm) on both axes
        for mm in range(-15, 16):
            if mm == 0:
                continue
            tick_len = (3.5 if mm % 5 == 0 else 1.8) * MM_TO_PT
            tx = cx + mm * MM_TO_PT
            page.draw_line(pymupdf.Point(tx, cy - tick_len), pymupdf.Point(tx, cy + tick_len), color=(0.2, 0.2, 0.2), width=0.5)
            ty = cy + mm * MM_TO_PT
            page.draw_line(pymupdf.Point(cx - tick_len, ty), pymupdf.Point(cx + tick_len, ty), color=(0.2, 0.2, 0.2), width=0.5)

        title_rect = pymupdf.Rect(25 * MM_TO_PT, 26 * MM_TO_PT, 185 * MM_TO_PT, 65 * MM_TO_PT)
        page.insert_textbox(
            title_rect,
            "套打偏移校准测试页 (A4)\n"
            "1. 请用你日常打印实验报告的同一台打印机（务必选择“实际大小 / 100%缩放”）打印此页。\n"
            "2. 用尺子量出外框四边到纸张边缘的距离（理论应均为 20.0 mm）。\n"
            "3. 若实际左边距为 L mm、上边距为 T mm，则在导出弹窗中填入：\n"
            "   X 偏移 = 20.0 - L (mm) ， Y 偏移 = 20.0 - T (mm)。",
            fontname="cjk",
            fontsize=10.5,
            color=(0.12, 0.14, 0.18),
            align=pymupdf.TEXT_ALIGN_LEFT,
        )
        return doc.tobytes(deflate=True)
    finally:
        doc.close()
