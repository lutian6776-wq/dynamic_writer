"""Tests for Phase 2 AI few-shot synthesizer helpers, tablet-first priority, and real GTX 1650 inference."""

from __future__ import annotations

import io
import sys
import time
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_conn, init_db, now_iso
from app.models import HandwritingStyle, PageMeta, RegionConfig
from app.services.glyph_store import delete_ai_glyphs, get_glyphs_by_char, list_glyph_summary
from app.services.handwriting_engine import compute_document_placements, render_page_overlay
from app.services.synthesizer import (
    get_synthesizer,
    postprocess_generated_glyph,
    render_content_image,
    select_style_references,
    start_synthesis_job,
    get_job,
)


def _insert_glyph(
    profile_id: str,
    char: str,
    source: str,
    out_dir: Path,
    draw_fn=None,
) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if draw_fn is not None:
        draw_fn(draw)
    else:
        draw.line([(56, 70), (200, 74)], fill=(0, 0, 0, 240), width=14)
        draw.line([(128, 48), (124, 206)], fill=(0, 0, 0, 240), width=14)
        draw.line([(72, 130), (184, 134)], fill=(0, 0, 0, 240), width=12)

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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (gid, profile_id, char, source, str(path), 0.22, 0.19, 0.78, 0.80, 0.56, 0.61, 0.50, now_iso()),
        )
    return gid


def test_ai_helpers_and_tablet_priority(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITER_DATA_DIR", str(tmp_path))
    init_db()
    gdir = tmp_path / "glyphs" / "default"

    # 1. Content rendering check
    c_img = render_content_image("熵", size=96)
    assert c_img.size == (96, 96)
    c_arr = np.asarray(c_img.convert("L"))
    assert int(c_arr[0, 0]) == 255
    assert int(c_arr.min()) < 40

    # 2. Post-processing check (gray diffusion noise -> clean transparent 256x256)
    noisy = Image.new("RGB", (96, 96), (234, 234, 234))
    nd = ImageDraw.Draw(noisy)
    nd.line([(16, 20), (80, 22)], fill=(25, 25, 25), width=6)
    nd.line([(48, 12), (48, 84)], fill=(25, 25, 25), width=6)
    post = postprocess_generated_glyph(noisy, target_height_ratio=0.60)
    rgba = post["rgba_image"]
    assert rgba.size == (256, 256)
    p_alpha = np.asarray(rgba.split()[-1])
    assert int(p_alpha[0, 0]) == 0
    assert int(p_alpha.max()) > 200
    assert 0.50 <= post["visual_height_ratio"] <= 0.70

    # 3. Tablet-first priority + AI tracking
    _insert_glyph("default", "验", "tablet", gdir)
    ai_shi_id = _insert_glyph("default", "实", "ai_generated", gdir)
    tab_shi_id = _insert_glyph("default", "实", "tablet", gdir)
    _insert_glyph("default", "熵", "ai_generated", gdir)

    refs = select_style_references("default", max_refs=4)
    assert all(r["source"] == "tablet" for r in refs)
    assert {r["char"] for r in refs} == {"实", "验"}

    by_char = get_glyphs_by_char("default")
    assert len(by_char["实"]) == 1
    assert by_char["实"][0]["id"] == tab_shi_id
    assert by_char["熵"][0]["source"] == "ai_generated"

    # Summary source filters
    summary_ai = list_glyph_summary("default", source_filter="ai_generated")
    assert {s["char"] for s in summary_ai} == {"实", "熵"}

    # Engine stats & blank vs highlight diff
    pages = [PageMeta(page_index=0, width_pt=595.0, height_pt=842.0)]
    regs = [RegionConfig(id="r1", page_index=0, x=60, y=80, width=300, height=100, text="实验熵")]
    style = HandwritingStyle(elastic_intensity=0.0, rotation_sigma=0.0, baseline_drift=0.0)
    _, stats = compute_document_placements(regs, style, by_char)
    assert stats["ai_generated_chars"] == ["熵"]

    hl_png, _ = render_page_overlay(pages, regs, style, by_char, 0, dpi=120, missing_char_mode="highlight")
    bl_png, _ = render_page_overlay(pages, regs, style, by_char, 0, dpi=120, missing_char_mode="blank")
    arr_hl = np.asarray(Image.open(io.BytesIO(hl_png)).convert("RGBA"))
    arr_bl = np.asarray(Image.open(io.BytesIO(bl_png)).convert("RGBA"))
    # Preview draws subtle indigo dotted underline under AI char '熵', while print 'blank' mode does not
    blue_diff = np.abs(arr_hl[:, :, 2].astype(int) - arr_bl[:, :, 2].astype(int)).sum()
    assert blue_diff > 100

    # Delete AI glyphs cleanly
    deleted = delete_ai_glyphs("default")
    assert deleted == 2
    assert "熵" not in get_glyphs_by_char("default")
    assert ai_shi_id not in {r["id"] for r in get_glyphs_by_char("default")["实"]}


def test_fontdiffuser_real_gpu_inference(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITER_DATA_DIR", str(tmp_path))
    ckpt_dir = Path(__file__).resolve().parents[2] / "data" / "models" / "fontdiffuser"
    monkeypatch.setenv("WRITER_FONTDIFFUSER_CKPT_DIR", str(ckpt_dir))
    init_db()

    synth = get_synthesizer()
    status = synth.get_status()
    assert status["ckpt_ready"] is True, f"Missing checkpoints in {ckpt_dir}: {status}"
    assert status["cuda_available"] is True, f"CUDA not available: {status}"
    assert status["available"] is True

    gdir = tmp_path / "glyphs" / "default"
    _insert_glyph("default", "实", "tablet", gdir)
    _insert_glyph("default", "验", "tablet", gdir)

    import torch

    torch.cuda.reset_peak_memory_stats(0)
    job = start_synthesis_job(
        profile_id="default",
        chars="熵谱",
        variants_per_char=1,
        num_inference_steps=15,
        guidance_scale=7.5,
        seed=42,
    )
    job_id = job["job_id"]
    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline:
        cur = get_job(job_id)
        assert cur is not None
        if cur["status"] != "running":
            break
        time.sleep(0.5)

    final_job = get_job(job_id)
    assert final_job is not None
    assert final_job["status"] == "done", f"Job failed: {final_job}"
    assert final_job["errors"] == []
    assert len(final_job["generated_glyphs"]) == 2

    peak_vram_mb = torch.cuda.max_memory_allocated(0) / (1024 * 1024)
    assert peak_vram_mb < 3500.0, f"VRAM peak too high for 4GB GTX 1650: {peak_vram_mb:.1f} MB"

    by_char = get_glyphs_by_char("default")
    for ch in ("熵", "谱"):
        assert ch in by_char
        row = by_char[ch][0]
        assert row["source"] == "ai_generated"
        img = Image.open(row["image_path"]).convert("RGBA")
        assert img.size == (256, 256)
        alpha = np.asarray(img.split()[-1])
        assert int(alpha[0, 0]) == 0
        assert int(alpha.max()) > 160

    unloaded = synth.unload()
    assert unloaded["loaded"] is False
