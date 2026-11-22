"""Pydantic schemas for profiles, glyphs, capture sheets, projects, and export."""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


class ProfileOut(BaseModel):
    id: str
    name: str
    created_at: str


class ProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class PageMeta(BaseModel):
    page_index: int
    width_pt: float
    height_pt: float


class RegionConfig(BaseModel):
    id: str
    page_index: int = 0
    name: str = "区域"
    type: Literal["single_line", "multi_line", "table"] = "multi_line"
    x: float
    y: float
    width: float
    height: float
    font_size: float = Field(default=16.0, ge=4.0, le=120.0)
    line_spacing: float = Field(default=24.0, ge=6.0, le=200.0)
    baseline_offset: float = Field(default=20.0, ge=0.0, le=200.0)
    first_line_indent: float = Field(default=0.0, ge=0.0, le=500.0)
    align: Literal["left", "center", "right"] = "left"
    next_region_id: Optional[str] = None
    table_rows: list[float] = Field(default_factory=lambda: [0.0, 0.5, 1.0])
    table_cols: list[float] = Field(default_factory=lambda: [0.0, 0.5, 1.0])
    text: str = ""


class HandwritingStyle(BaseModel):
    preset: Literal["neat", "daily", "rush", "custom"] = "daily"
    ink_color: str = "#1c1d24"
    stroke_weight: float = Field(default=1.0, ge=0.5, le=2.0)
    elastic_intensity: float = Field(default=0.28, ge=0.0, le=1.0)
    rotation_sigma: float = Field(default=1.8, ge=0.0, le=8.0)
    scale_sigma: float = Field(default=0.045, ge=0.0, le=0.2)
    word_spacing_factor: float = Field(default=1.02, ge=0.6, le=2.0)
    baseline_drift: float = Field(default=1.2, ge=0.0, le=6.0)
    line_slant: float = Field(default=0.0, ge=-3.5, le=3.5)
    ink_variation: float = Field(default=0.08, ge=0.0, le=0.4)
    strikethrough_prob: float = Field(default=0.0, ge=0.0, le=0.1)
    strikethrough_style: Literal["double_line", "scribble"] = "double_line"
    fatigue_intensity: float = Field(default=0.2, ge=0.0, le=1.0)
    seed: int = 42


STYLE_PRESETS: dict[str, dict] = {
    "neat": {
        "preset": "neat",
        "stroke_weight": 1.0,
        "elastic_intensity": 0.10,
        "rotation_sigma": 0.7,
        "scale_sigma": 0.02,
        "word_spacing_factor": 0.98,
        "baseline_drift": 0.4,
        "line_slant": 0.0,
        "ink_variation": 0.04,
        "strikethrough_prob": 0.0,
        "fatigue_intensity": 0.05,
    },
    "daily": {
        "preset": "daily",
        "stroke_weight": 1.0,
        "elastic_intensity": 0.28,
        "rotation_sigma": 1.8,
        "scale_sigma": 0.045,
        "word_spacing_factor": 1.02,
        "baseline_drift": 1.2,
        "line_slant": 0.0,
        "ink_variation": 0.08,
        "strikethrough_prob": 0.0,
        "fatigue_intensity": 0.20,
    },
    "rush": {
        "preset": "rush",
        "stroke_weight": 0.96,
        "elastic_intensity": 0.52,
        "rotation_sigma": 3.4,
        "scale_sigma": 0.075,
        "word_spacing_factor": 1.08,
        "baseline_drift": 2.2,
        "line_slant": -0.6,
        "ink_variation": 0.14,
        "strikethrough_prob": 0.008,
        "fatigue_intensity": 0.55,
    },
}


class ProjectOut(BaseModel):
    id: str
    name: str
    profile_id: str
    template_kind: str
    page_count: int
    pages_meta: list[PageMeta]
    regions: list[RegionConfig]
    style: HandwritingStyle
    updated_at: str


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    profile_id: Optional[str] = None
    regions: Optional[list[RegionConfig]] = None
    style: Optional[HandwritingStyle] = None


class SheetGenerateRequest(BaseModel):
    profile_id: str = "default"
    title: str = "手写采集表"
    chars: str = ""
    preset_id: Optional[str] = None
    variants_per_char: int = Field(default=1, ge=1, le=5)
    high_freq_chars: str = ""
    high_freq_variants: int = Field(default=2, ge=1, le=5)


class PreviewRequest(BaseModel):
    dpi: int = Field(default=120, ge=72, le=300)
    missing_char_mode: Literal["highlight", "blank"] = "highlight"
    regions: Optional[list[RegionConfig]] = None
    style: Optional[HandwritingStyle] = None


class ExportRequest(BaseModel):
    dpi: Literal[300, 600] = 300
    mode: Literal["composite", "overlay_only"] = "composite"
    offset_x_mm: float = Field(default=0.0, ge=-50.0, le=50.0)
    offset_y_mm: float = Field(default=0.0, ge=-50.0, le=50.0)
    missing_char_mode: Literal["blank", "highlight"] = "blank"


class RegionRectRequest(BaseModel):
    x: float
    y: float
    width: float
    height: float


class TextAnalyzeRequest(BaseModel):
    profile_id: str = "default"
    text: str = ""


class BatchDeleteGlyphsRequest(BaseModel):
    profile_id: str = "default"
    glyph_ids: list[str] = Field(default_factory=list)
    chars: list[str] = Field(default_factory=list)
    source: Literal["all", "tablet", "ai_generated"] = "all"
    date_from: str = ""
    date_to: str = ""
    tz_offset_min: int = Field(default=0, ge=-840, le=840)
