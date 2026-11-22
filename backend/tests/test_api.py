"""FastAPI integration tests covering health, mobile page, profiles, sheets, projects, preview & export."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app


def test_api_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITER_DATA_DIR", str(tmp_path))

    async def _run() -> None:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                # Health & mobile page
                r = await client.get("/api/health")
                assert r.status_code == 200
                assert r.json()["status"] == "ok"

                ai_st = await client.get("/api/ai/status")
                assert ai_st.status_code == 200
                assert "cuda_available" in ai_st.json()

                gl_ai = await client.get("/api/glyphs?profile_id=default&source=ai_generated")
                assert gl_ai.status_code == 200

                m = await client.get("/mobile")
                assert m.status_code == 200
                assert "墨迹" in m.text

                # Profiles
                p = await client.get("/api/profiles")
                assert p.status_code == 200
                assert len(p.json()) >= 1

                # Generate capture sheet + LAN QR
                sh = await client.post(
                    "/api/sheets/generate",
                    json={"profile_id": "default", "title": "API测试", "chars": "实验报告", "variants_per_char": 1},
                )
                assert sh.status_code == 200
                sheet_id = sh.json()["sheet_id"]
                pdf_resp = await client.get(f"/api/sheets/{sheet_id}/pdf")
                assert pdf_resp.status_code == 200
                assert pdf_resp.headers["content-type"] == "application/pdf"

                qr = await client.get("/api/sheets/lan-qr")
                assert qr.status_code == 200
                assert "<svg" in qr.json()["svg"]

                # Upload sample template PDF
                doc = pymupdf.open()
                page = doc.new_page(width=595.28, height=841.89)
                page.draw_line((60, 140), (500, 140), color=(0, 0, 0), width=1)
                page.draw_line((60, 165), (500, 165), color=(0, 0, 0), width=1)
                tpl_bytes = doc.tobytes()
                doc.close()

                up = await client.post(
                    "/api/projects/upload",
                    files={"file": ("report.pdf", tpl_bytes, "application/pdf")},
                    data={"name": "物理实验1"},
                )
                assert up.status_code == 200
                proj = up.json()
                pid = proj["id"]

                # Detect lines
                dl = await client.post(
                    f"/api/projects/{pid}/pages/0/detect-lines",
                    json={"x": 50, "y": 115, "width": 460, "height": 80},
                )
                assert dl.status_code == 200
                assert abs(dl.json()["line_spacing"] - 25.0) < 1.0

                # Update regions & render preview
                region = {
                    "id": "reg1",
                    "page_index": 0,
                    "name": "实验目的",
                    "type": "multi_line",
                    "x": 60.0,
                    "y": 118.0,
                    "width": 440.0,
                    "height": 80.0,
                    "font_size": 16.0,
                    "line_spacing": 25.0,
                    "baseline_offset": 22.0,
                    "first_line_indent": 0.0,
                    "align": "left",
                    "next_region_id": None,
                    "table_rows": [0.0, 0.5, 1.0],
                    "table_cols": [0.0, 0.5, 1.0],
                    "text": "测试实验目的。",
                }
                upd = await client.put(f"/api/projects/{pid}", json={"regions": [region]})
                assert upd.status_code == 200

                prev = await client.post(
                    f"/api/projects/{pid}/pages/0/preview",
                    json={"dpi": 120, "missing_char_mode": "highlight"},
                )
                assert prev.status_code == 200
                assert len(prev.json()["image_base64"]) > 100
                assert prev.json()["stats"]["missing_unique"] > 0

                # Export PDF
                exp = await client.post(
                    f"/api/projects/{pid}/export",
                    json={"dpi": 300, "mode": "composite", "missing_char_mode": "blank"},
                )
                assert exp.status_code == 200
                assert exp.headers["content-type"] == "application/pdf"
                assert len(exp.content) > 500

    asyncio.run(_run())
