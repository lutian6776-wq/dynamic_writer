"""Template project management, layout detection, preview rendering, and PDF export routes."""

from __future__ import annotations

import base64
import json
import shutil
import uuid
from pathlib import Path
from typing import Optional

import pymupdf
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from PIL import Image

from app.config import ensure_data_dirs, get_projects_dir
from app.db import get_conn, now_iso
from app.models import (
    ExportRequest,
    HandwritingStyle,
    PageMeta,
    PreviewRequest,
    ProjectOut,
    ProjectUpdate,
    RegionConfig,
    RegionRectRequest,
)
from app.services.glyph_store import get_glyphs_by_char
from app.services.handwriting_engine import render_page_overlay
from app.services.layout_detector import detect_lines_in_region, detect_table_in_region
from app.services.pdf_exporter import export_project_pdf, generate_calibration_pdf
from app.services.sheet_geometry import A4_W_PT

router = APIRouter(tags=["projects"])

ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _row_to_project_out(row) -> ProjectOut:
    return ProjectOut(
        id=row["id"],
        name=row["name"],
        profile_id=row["profile_id"],
        template_kind=row["template_kind"],
        page_count=row["page_count"],
        pages_meta=[PageMeta(**m) for m in json.loads(row["pages_meta_json"])],
        regions=[RegionConfig(**r) for r in json.loads(row["regions_json"])],
        style=HandwritingStyle(**json.loads(row["style_json"])),
        updated_at=row["updated_at"],
    )


def _get_project_row(project_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return row


@router.get("/api/projects", response_model=list[ProjectOut])
def list_projects() -> list[ProjectOut]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    return [_row_to_project_out(r) for r in rows]


@router.post("/api/projects/upload", response_model=ProjectOut)
async def upload_template_project(
    file: UploadFile = File(...),
    name: Optional[str] = Form(default=None),
    profile_id: str = Form(default="default"),
) -> ProjectOut:
    ensure_data_dirs()
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")

    orig_name = file.filename or "template.pdf"
    suffix = Path(orig_name).suffix.lower()
    if suffix != ".pdf" and suffix not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(status_code=400, detail="仅支持 PDF 或常见图片格式 (PNG/JPG/WEBP)")

    project_id = uuid.uuid4().hex[:12]
    proj_dir = get_projects_dir() / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)

    raw_path = proj_dir / f"source{suffix}"
    raw_path.write_bytes(raw)

    if suffix == ".pdf":
        template_pdf_path = raw_path
        template_kind = "pdf"
    else:
        template_kind = "image"
        template_pdf_path = proj_dir / "template.pdf"
        with Image.open(raw_path) as img:
            w_px, h_px = img.size
        w_pt = A4_W_PT
        h_pt = A4_W_PT * (h_px / max(w_px, 1))
        pdf_doc = pymupdf.open()
        try:
            page = pdf_doc.new_page(width=w_pt, height=h_pt)
            page.insert_image(page.rect, filename=str(raw_path))
            pdf_doc.save(str(template_pdf_path), deflate=True)
        finally:
            pdf_doc.close()

    doc = pymupdf.open(str(template_pdf_path))
    try:
        pages_meta = [
            {"page_index": i, "width_pt": float(p.rect.width), "height_pt": float(p.rect.height)}
            for i, p in enumerate(doc)
        ]
    finally:
        doc.close()

    proj_name = (name or Path(orig_name).stem).strip() or "未命名模板"
    updated_at = now_iso()
    default_style = HandwritingStyle().model_dump()

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO projects (
                id, name, profile_id, template_path, template_kind,
                page_count, pages_meta_json, regions_json, style_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                proj_name,
                profile_id,
                str(template_pdf_path),
                template_kind,
                len(pages_meta),
                json.dumps(pages_meta),
                "[]",
                json.dumps(default_style),
                updated_at,
            ),
        )
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _row_to_project_out(row)


@router.get("/api/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str) -> ProjectOut:
    return _row_to_project_out(_get_project_row(project_id))


@router.put("/api/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, body: ProjectUpdate) -> ProjectOut:
    row = _get_project_row(project_id)
    name = body.name if body.name is not None else row["name"]
    profile_id = body.profile_id if body.profile_id is not None else row["profile_id"]
    regions_json = (
        json.dumps([r.model_dump() for r in body.regions], ensure_ascii=False)
        if body.regions is not None
        else row["regions_json"]
    )
    style_json = (
        json.dumps(body.style.model_dump(), ensure_ascii=False)
        if body.style is not None
        else row["style_json"]
    )
    updated_at = now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE projects
            SET name = ?, profile_id = ?, regions_json = ?, style_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (name, profile_id, regions_json, style_json, updated_at, project_id),
        )
        updated = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _row_to_project_out(updated)


@router.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict:
    row = _get_project_row(project_id)
    proj_dir = Path(row["template_path"]).parent
    with get_conn() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    if proj_dir.exists() and proj_dir.parent == get_projects_dir():
        shutil.rmtree(proj_dir, ignore_errors=True)
    return {"deleted": True}


@router.get("/api/projects/{project_id}/pages/{page_index}/background")
def get_page_background(project_id: str, page_index: int, dpi: int = Query(default=150, ge=72, le=300)) -> Response:
    row = _get_project_row(project_id)
    doc = pymupdf.open(row["template_path"])
    try:
        if page_index < 0 or page_index >= len(doc):
            raise HTTPException(status_code=404, detail="页码超出范围")
        scale = dpi / 72.0
        pix = doc[page_index].get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False)
        png_bytes = pix.tobytes("png")
    finally:
        doc.close()
    return Response(content=png_bytes, media_type="image/png")


@router.post("/api/projects/{project_id}/pages/{page_index}/detect-lines")
def detect_lines(project_id: str, page_index: int, body: RegionRectRequest) -> dict:
    row = _get_project_row(project_id)
    try:
        return detect_lines_in_region(
            template_path=row["template_path"],
            page_index=page_index,
            x=body.x,
            y=body.y,
            width=body.width,
            height=body.height,
        )
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/projects/{project_id}/pages/{page_index}/detect-table")
def detect_table(project_id: str, page_index: int, body: RegionRectRequest) -> dict:
    row = _get_project_row(project_id)
    try:
        return detect_table_in_region(
            template_path=row["template_path"],
            page_index=page_index,
            x=body.x,
            y=body.y,
            width=body.width,
            height=body.height,
        )
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/projects/{project_id}/pages/{page_index}/preview")
def preview_page(project_id: str, page_index: int, body: PreviewRequest) -> dict:
    row = _get_project_row(project_id)
    pages_meta = [PageMeta(**m) for m in json.loads(row["pages_meta_json"])]
    regions = body.regions if body.regions is not None else [RegionConfig(**r) for r in json.loads(row["regions_json"])]
    style = body.style if body.style is not None else HandwritingStyle(**json.loads(row["style_json"]))
    glyphs_by_char = get_glyphs_by_char(row["profile_id"])

    try:
        png_bytes, stats = render_page_overlay(
            pages_meta=pages_meta,
            regions=regions,
            style=style,
            glyphs_by_char=glyphs_by_char,
            page_index=page_index,
            dpi=body.dpi,
            missing_char_mode=body.missing_char_mode,
        )
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "image_base64": base64.b64encode(png_bytes).decode("ascii"),
        "stats": stats,
    }


@router.post("/api/projects/{project_id}/export")
def export_project(project_id: str, body: ExportRequest) -> Response:
    row = _get_project_row(project_id)
    pages_meta = [PageMeta(**m) for m in json.loads(row["pages_meta_json"])]
    regions = [RegionConfig(**r) for r in json.loads(row["regions_json"])]
    style = HandwritingStyle(**json.loads(row["style_json"]))
    glyphs_by_char = get_glyphs_by_char(row["profile_id"])

    pdf_bytes = export_project_pdf(
        template_path=row["template_path"],
        pages_meta=pages_meta,
        regions=regions,
        style=style,
        glyphs_by_char=glyphs_by_char,
        export_req=body,
    )
    suffix = "composite" if body.mode == "composite" else "overlay"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="handwriting_{project_id}_{suffix}.pdf"'},
    )


@router.get("/api/export/calibration-pdf")
def download_calibration_pdf() -> Response:
    pdf_bytes = generate_calibration_pdf()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="calibration_a4.pdf"'},
    )
