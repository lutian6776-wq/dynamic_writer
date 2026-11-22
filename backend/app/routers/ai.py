"""Phase 2 local GPU AI few-shot glyph synthesis API routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.glyph_store import delete_ai_glyphs
from app.services.synthesizer import get_job, get_synthesizer, start_synthesis_job

router = APIRouter(prefix="/api/ai", tags=["ai"])


class AiSynthesizeRequest(BaseModel):
    profile_id: str = "default"
    chars: str = Field(..., min_length=1)
    variants_per_char: int = Field(default=1, ge=1, le=3)
    num_inference_steps: int = Field(default=20, ge=8, le=50)
    guidance_scale: float = Field(default=7.5, ge=1.0, le=15.0)
    style_glyph_ids: Optional[list[str]] = None
    seed: int = 42
    replace_existing_ai: bool = False


@router.get("/status")
def ai_status() -> dict:
    return get_synthesizer().get_status()


@router.post("/synthesize")
def start_ai_synthesize(body: AiSynthesizeRequest) -> dict:
    try:
        return start_synthesis_job(
            profile_id=body.profile_id,
            chars=body.chars,
            variants_per_char=body.variants_per_char,
            num_inference_steps=body.num_inference_steps,
            guidance_scale=body.guidance_scale,
            style_glyph_ids=body.style_glyph_ids,
            seed=body.seed,
            replace_existing_ai=body.replace_existing_ai,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/jobs/{job_id}")
def get_ai_job(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="推理任务不存在")
    return job


@router.post("/unload")
def unload_ai_model() -> dict:
    return get_synthesizer().unload()


@router.delete("/glyphs/{profile_id}")
def clear_ai_glyphs(profile_id: str) -> dict:
    count = delete_ai_glyphs(profile_id)
    return {"deleted": count}
