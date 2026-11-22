"""Tests for glyph import-date filtering, batch deletion, and AI redraw replacement."""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_conn, init_db
from app.main import app
from app.models import BatchDeleteGlyphsRequest
from app.routers.ai import AiSynthesizeRequest, start_ai_synthesize
from app.routers.glyphs import batch_remove_glyphs, get_glyph_import_dates, get_glyphs
from app.services import synthesizer as synth_mod
from app.services.glyph_store import (
    batch_delete_glyphs,
    get_glyphs_by_char,
    list_glyph_summary,
    list_import_dates,
)


def _insert_glyph_at(
    profile_id: str,
    char: str,
    source: str,
    out_dir: Path,
    created_at: str,
) -> tuple[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.line([(56, 70), (200, 74)], fill=(0, 0, 0, 240), width=14)
    draw.line([(128, 48), (124, 206)], fill=(0, 0, 0, 240), width=14)

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
            (gid, profile_id, char, source, str(path), 0.22, 0.19, 0.78, 0.80, 0.56, 0.61, 0.50, created_at),
        )
    return gid, path


def test_date_filtering_timezone_and_import_dates(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITER_DATA_DIR", str(tmp_path))
    init_db()
    gdir = tmp_path / "glyphs" / "default"

    # 2026-11-21T17:30:00+00:00 is 2026-11-21 in UTC, 2026-11-22 01:30 in UTC+8 (tz_offset_min=480)
    _insert_glyph_at("default", "甲", "tablet", gdir, "2026-11-20T08:00:00+00:00")
    _insert_glyph_at("default", "乙", "tablet", gdir, "2026-11-21T17:30:00+00:00")
    _insert_glyph_at("default", "乙", "ai_generated", gdir, "2026-11-22T09:00:00+00:00")
    _insert_glyph_at("default", "丙", "ai_generated", gdir, "2026-11-22T10:00:00+00:00")

    dates_utc = list_import_dates("default", tz_offset_min=0)
    assert [d["date"] for d in dates_utc] == ["2026-11-22", "2026-11-21", "2026-11-20"]

    dates_utc8 = list_import_dates("default", tz_offset_min=480)
    assert [d["date"] for d in dates_utc8] == ["2026-11-22", "2026-11-20"]
    assert dates_utc8[0]["char_count"] == 2
    assert dates_utc8[0]["variant_count"] == 3
    assert dates_utc8[0]["tablet_count"] == 1
    assert dates_utc8[0]["ai_count"] == 2

    dates_ai_only = list_import_dates("default", source_filter="ai_generated", tz_offset_min=480)
    assert len(dates_ai_only) == 1
    assert dates_ai_only[0]["date"] == "2026-11-22"
    assert dates_ai_only[0]["variant_count"] == 2

    # Date filter on 2026-11-22 in UTC+8 includes both tablet (17:30Z on Nov 21) and ai variants
    nov22_all = list_glyph_summary(
        "default",
        date_from="2026-11-22",
        date_to="2026-11-22",
        tz_offset_min=480,
        sort_by="latest",
    )
    assert [g["char"] for g in nov22_all] == ["丙", "乙"]
    assert nov22_all[1]["variant_count"] == 2
    assert nov22_all[1]["latest_import_date"] == "2026-11-22"

    # Sort by char ascending
    sorted_char = list_glyph_summary("default", tz_offset_min=480, sort_by="char")
    assert [g["char"] for g in sorted_char] == sorted(["甲", "乙", "丙"])

    # Invalid date string raises ValueError
    try:
        list_glyph_summary("default", date_from="2026/11/22")
        assert False, "Expected ValueError for invalid date format"
    except ValueError:
        pass


def test_batch_delete_by_ids_and_by_chars_with_filters(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITER_DATA_DIR", str(tmp_path))
    init_db()
    gdir = tmp_path / "glyphs" / "default"

    id_a_tab, path_a_tab = _insert_glyph_at("default", "测", "tablet", gdir, "2026-11-20T06:00:00+00:00")
    id_a_ai_nov20, path_a_ai_nov20 = _insert_glyph_at(
        "default", "测", "ai_generated", gdir, "2026-11-20T07:00:00+00:00"
    )
    id_a_ai_nov22, path_a_ai_nov22 = _insert_glyph_at(
        "default", "测", "ai_generated", gdir, "2026-11-22T07:00:00+00:00"
    )
    id_b_tab, path_b_tab = _insert_glyph_at("default", "试", "tablet", gdir, "2026-11-22T08:00:00+00:00")
    assert all(p.exists() for p in (path_a_tab, path_a_ai_nov20, path_a_ai_nov22, path_b_tab))

    # Delete specific AI variant on Nov 20 via chars + source + date filter
    res1 = batch_delete_glyphs(
        profile_id="default",
        chars=["测", "试"],
        source_filter="ai_generated",
        date_from="2026-11-20",
        date_to="2026-11-20",
        tz_offset_min=480,
    )
    assert res1["deleted"] == 1
    assert res1["deleted_ids"] == [id_a_ai_nov20]
    assert not path_a_ai_nov20.exists()
    assert path_a_tab.exists()
    assert path_a_ai_nov22.exists()
    assert path_b_tab.exists()

    # Verify FastAPI OpenAPI schema, route ordering & route handlers directly
    openapi = app.openapi()
    path_keys = list(openapi["paths"].keys())
    assert "/api/glyphs/dates" in openapi["paths"]
    assert "get" in openapi["paths"]["/api/glyphs/dates"]
    assert "/api/glyphs/batch-delete" in openapi["paths"]
    assert "post" in openapi["paths"]["/api/glyphs/batch-delete"]
    assert path_keys.index("/api/glyphs/dates") < path_keys.index("/api/glyphs/{glyph_id}")
    assert path_keys.index("/api/glyphs/batch-delete") < path_keys.index("/api/glyphs/{glyph_id}")
    glyphs_params = {p["name"] for p in openapi["paths"]["/api/glyphs"]["get"]["parameters"]}
    assert {"date_from", "date_to", "tz_offset_min", "sort"}.issubset(glyphs_params)
    assert "replace_existing_ai" in openapi["components"]["schemas"]["AiSynthesizeRequest"]["properties"]

    r_dates = get_glyph_import_dates(profile_id="default", source="all", tz_offset_min=480)
    assert [d["date"] for d in r_dates] == ["2026-11-22", "2026-11-20"]

    r_list = get_glyphs(
        profile_id="default",
        search="",
        source="all",
        date_from="2026-11-22",
        date_to="2026-11-22",
        tz_offset_min=480,
        sort="latest",
    )
    assert [g["char"] for g in r_list] == ["试", "测"]

    try:
        get_glyphs(
            profile_id="default",
            search="",
            source="all",
            date_from="bad-date",
            date_to="",
            tz_offset_min=480,
            sort="variant_count",
        )
        assert False, "Expected HTTPException 400"
    except HTTPException as exc:
        assert exc.status_code == 400

    try:
        batch_remove_glyphs(BatchDeleteGlyphsRequest(profile_id="default", glyph_ids=[], chars=[]))
        assert False, "Expected HTTPException 400"
    except HTTPException as exc:
        assert exc.status_code == 400

    r_del = batch_remove_glyphs(
        BatchDeleteGlyphsRequest(profile_id="default", glyph_ids=[id_a_ai_nov22, id_b_tab])
    )
    assert r_del["deleted"] == 2
    assert set(r_del["deleted_ids"]) == {id_a_ai_nov22, id_b_tab}

    assert not path_a_ai_nov22.exists()
    assert not path_b_tab.exists()
    assert path_a_tab.exists()
    remaining = list_glyph_summary("default")
    assert len(remaining) == 1
    assert remaining[0]["char"] == "测"
    assert remaining[0]["variant_count"] == 1


def test_ai_redraw_replace_existing_ai_preserves_tablet_and_handles_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITER_DATA_DIR", str(tmp_path))
    init_db()
    gdir = tmp_path / "glyphs" / "default"

    tab_id, tab_path = _insert_glyph_at("default", "实", "tablet", gdir, "2026-11-21T08:00:00+00:00")
    old_ai_shi, old_ai_shi_path = _insert_glyph_at(
        "default", "实", "ai_generated", gdir, "2026-11-21T09:00:00+00:00"
    )
    old_ai_shang, old_ai_shang_path = _insert_glyph_at(
        "default", "熵", "ai_generated", gdir, "2026-11-21T09:00:00+00:00"
    )
    old_ai_fail, old_ai_fail_path = _insert_glyph_at(
        "default", "谱", "ai_generated", gdir, "2026-11-21T09:00:00+00:00"
    )

    class _FakeSynth:
        def get_status(self) -> dict:
            return {"available": True, "error": None}

        def synthesize_pil_96(
            self,
            char: str,
            style_pils_96: list[Image.Image],
            num_inference_steps: int = 20,
            guidance_scale: float = 7.5,
            seed: int = 42,
        ) -> Image.Image:
            if char == "谱":
                raise RuntimeError("simulated synthesis error")
            img = Image.new("RGB", (96, 96), (255, 255, 255))
            d = ImageDraw.Draw(img)
            d.line([(18, 22), (78, 24)], fill=(15, 15, 15), width=6)
            d.line([(48, 16), (48, 80)], fill=(15, 15, 15), width=6)
            return img

    monkeypatch.setattr(synth_mod, "get_synthesizer", lambda: _FakeSynth())

    job = start_ai_synthesize(
        AiSynthesizeRequest(
            profile_id="default",
            chars="实熵谱",
            variants_per_char=1,
            seed=123,
            replace_existing_ai=True,
        )
    )
    deadline = time.monotonic() + 15.0
    final_job = None
    while time.monotonic() < deadline:
        cur = synth_mod.get_job(job["job_id"])
        if cur and cur["status"] != "running":
            final_job = cur
            break
        time.sleep(0.05)

    assert final_job is not None
    assert final_job["status"] == "done"
    assert len(final_job["generated_glyphs"]) == 2
    assert final_job["replaced_count"] == 2
    assert len(final_job["errors"]) == 1

    # Tablet variant preserved; old AI variants for succeeded chars removed; failed char old AI preserved
    assert tab_path.exists()
    assert not old_ai_shi_path.exists()
    assert not old_ai_shang_path.exists()
    assert old_ai_fail_path.exists()

    summary = {item["char"]: item for item in list_glyph_summary("default")}
    assert summary["实"]["tablet_count"] == 1
    assert summary["实"]["ai_count"] == 1
    assert old_ai_shi not in {v["id"] for v in summary["实"]["variants"]}
    assert tab_id in {v["id"] for v in summary["实"]["variants"]}

    assert summary["熵"]["ai_count"] == 1
    assert old_ai_shang not in {v["id"] for v in summary["熵"]["variants"]}

    assert summary["谱"]["ai_count"] == 1
    assert summary["谱"]["variants"][0]["id"] == old_ai_fail

    # Tablet-first precedence still returns tablet for '实' and new AI for '熵'
    by_char = get_glyphs_by_char("default")
    assert by_char["实"][0]["id"] == tab_id
    assert by_char["熵"][0]["id"] != old_ai_shang
