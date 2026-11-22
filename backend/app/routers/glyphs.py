"""Glyph library, variant inspection, text coverage, and built-in character presets API."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.data.common_chars import CHAR_PRESETS
from app.models import BatchDeleteGlyphsRequest, TextAnalyzeRequest
from app.services.glyph_store import (
    analyze_text_coverage,
    batch_delete_glyphs,
    delete_glyph,
    get_glyph_record,
    list_glyph_summary,
    list_import_dates,
)

router = APIRouter(prefix="/api/glyphs", tags=["glyphs"])


@router.get("/presets")
def get_char_presets() -> list[dict]:
    return CHAR_PRESETS


@router.get("/dates")
def get_glyph_import_dates(
    profile_id: str = Query(default="default"),
    source: str = Query(default="all"),
    tz_offset_min: int = Query(default=0, ge=-840, le=840),
) -> list[dict]:
    return list_import_dates(profile_id, source_filter=source, tz_offset_min=tz_offset_min)


@router.get("")
def get_glyphs(
    profile_id: str = Query(default="default"),
    search: str = Query(default=""),
    source: str = Query(default="all"),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    tz_offset_min: int = Query(default=0, ge=-840, le=840),
    sort: Literal["variant_count", "latest", "char"] = Query(default="variant_count"),
) -> list[dict]:
    try:
        return list_glyph_summary(
            profile_id,
            search=search,
            source_filter=source,
            date_from=date_from,
            date_to=date_to,
            tz_offset_min=tz_offset_min,
            sort_by=sort,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/batch-delete")
def batch_remove_glyphs(body: BatchDeleteGlyphsRequest) -> dict:
    try:
        return batch_delete_glyphs(
            profile_id=body.profile_id,
            glyph_ids=body.glyph_ids,
            chars=body.chars,
            source_filter=body.source,
            date_from=body.date_from,
            date_to=body.date_to,
            tz_offset_min=body.tz_offset_min,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/analyze")
def analyze_coverage(body: TextAnalyzeRequest) -> dict:
    return analyze_text_coverage(body.profile_id, body.text)


@router.get("/{glyph_id}/image")
def get_glyph_image(glyph_id: str) -> FileResponse:
    rec = get_glyph_record(glyph_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="字形不存在")
    path = Path(rec["image_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="字形图片文件丢失")
    return FileResponse(str(path), media_type="image/png")


@router.delete("/{glyph_id}")
def remove_glyph(glyph_id: str) -> dict:
    ok = delete_glyph(glyph_id)
    if not ok:
        raise HTTPException(status_code=404, detail="字形不存在")
    return {"deleted": True}
