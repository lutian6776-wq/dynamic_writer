"""Personal glyph library queries, text coverage analysis, and FontDiffuser 96x96 reference export."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from app.db import get_conn

MISTAKE_PATTERN = re.compile(r"\[([^\[\]\->]+)->([^\[\]\->]+)\]")


def extract_required_chars(text: str) -> list[str]:
    """
    Extract all non-whitespace characters needed to render `text`,
    including both wrong and right characters inside `[错->正]` tokens.
    """
    out: list[str] = []
    pos = 0
    for match in MISTAKE_PATTERN.finditer(text):
        for ch in text[pos : match.start()]:
            if not ch.isspace():
                out.append(ch)
        for ch in match.group(1):
            if not ch.isspace():
                out.append(ch)
        for ch in match.group(2):
            if not ch.isspace():
                out.append(ch)
        pos = match.end()
    for ch in text[pos:]:
        if not ch.isspace():
            out.append(ch)
    return out


def _parse_local_date(created_at: str, tz_offset_min: int = 0) -> str:
    """Convert stored ISO-8601 UTC timestamp string into local YYYY-MM-DD date."""
    raw = (created_at or "").strip()
    if not raw:
        return ""
    try:
        iso_str = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        local_dt = dt + timedelta(minutes=tz_offset_min)
        return local_dt.date().isoformat()
    except ValueError:
        return raw[:10]


def _normalize_date_str(val: str) -> str:
    """Validate and normalize YYYY-MM-DD filter date strings."""
    cleaned = (val or "").strip()
    if not cleaned:
        return ""
    try:
        datetime.strptime(cleaned, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("日期格式应为 YYYY-MM-DD") from exc
    return cleaned


def list_glyph_summary(
    profile_id: str,
    search: str = "",
    source_filter: str = "all",
    date_from: str = "",
    date_to: str = "",
    tz_offset_min: int = 0,
    sort_by: str = "variant_count",
) -> list[dict]:
    """Return one summary entry per character with variant list and source counts."""
    norm_from = _normalize_date_str(date_from)
    norm_to = _normalize_date_str(date_to)

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, char, source, image_path, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                   visual_width_ratio, visual_height_ratio, ink_center_y, sheet_id, created_at
            FROM glyphs
            WHERE profile_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (profile_id,),
        ).fetchall()

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        ch = row["char"]
        if search and search not in ch:
            continue
        local_date = _parse_local_date(row["created_at"], tz_offset_min)
        if norm_from and local_date < norm_from:
            continue
        if norm_to and local_date > norm_to:
            continue
        grouped.setdefault(ch, []).append(
            {
                "id": row["id"],
                "char": ch,
                "source": row["source"],
                "image_url": f"/api/glyphs/{row['id']}/image",
                "visual_width_ratio": row["visual_width_ratio"],
                "visual_height_ratio": row["visual_height_ratio"],
                "ink_center_y": row["ink_center_y"],
                "sheet_id": row["sheet_id"],
                "created_at": row["created_at"],
                "import_date": local_date,
            }
        )

    result: list[dict] = []
    for ch, variants in grouped.items():
        tablet_vars = [v for v in variants if v["source"] == "tablet"]
        ai_vars = [v for v in variants if v["source"] == "ai_generated"]
        has_tablet = len(tablet_vars) > 0
        has_ai = len(ai_vars) > 0

        if source_filter == "tablet" and not has_tablet:
            continue
        if source_filter == "ai_generated" and not has_ai:
            continue

        if source_filter == "tablet":
            latest_var = tablet_vars[0]
        elif source_filter == "ai_generated":
            latest_var = ai_vars[0]
        else:
            latest_var = tablet_vars[0] if has_tablet else variants[0]

        if source_filter == "tablet":
            latest_time_var = tablet_vars[0]
        elif source_filter == "ai_generated":
            latest_time_var = ai_vars[0]
        else:
            latest_time_var = variants[0]

        result.append(
            {
                "char": ch,
                "variant_count": len(variants),
                "tablet_count": len(tablet_vars),
                "ai_count": len(ai_vars),
                "has_tablet": has_tablet,
                "has_ai": has_ai,
                "latest_image_url": latest_var["image_url"],
                "latest_created_at": latest_time_var["created_at"],
                "latest_import_date": latest_time_var["import_date"],
                "variants": variants,
            }
        )

    if sort_by == "latest":
        result.sort(key=lambda item: (item["latest_created_at"], item["char"]), reverse=True)
    elif sort_by == "char":
        result.sort(key=lambda item: item["char"])
    else:
        result.sort(key=lambda item: (-item["variant_count"], item["char"]))
    return result


def list_import_dates(
    profile_id: str,
    source_filter: str = "all",
    tz_offset_min: int = 0,
) -> list[dict]:
    """Return distinct local import dates with char/variant counts for a profile."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT char, source, created_at
            FROM glyphs
            WHERE profile_id = ?
            """,
            (profile_id,),
        ).fetchall()

    buckets: dict[str, dict] = {}
    for row in rows:
        src = row["source"]
        if source_filter in ("tablet", "ai_generated") and src != source_filter:
            continue
        local_date = _parse_local_date(row["created_at"], tz_offset_min)
        if not local_date:
            continue
        bucket = buckets.setdefault(
            local_date,
            {
                "date": local_date,
                "variant_count": 0,
                "chars": set(),
                "tablet_count": 0,
                "ai_count": 0,
            },
        )
        bucket["variant_count"] += 1
        bucket["chars"].add(row["char"])
        if src == "tablet":
            bucket["tablet_count"] += 1
        elif src == "ai_generated":
            bucket["ai_count"] += 1

    out = [
        {
            "date": b["date"],
            "variant_count": b["variant_count"],
            "char_count": len(b["chars"]),
            "tablet_count": b["tablet_count"],
            "ai_count": b["ai_count"],
        }
        for b in buckets.values()
    ]
    out.sort(key=lambda item: item["date"], reverse=True)
    return out


def get_glyph_record(glyph_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM glyphs WHERE id = ?", (glyph_id,)).fetchone()
    return dict(row) if row else None


def get_glyphs_by_char(profile_id: str) -> dict[str, list[dict]]:
    """
    Return mapping `char -> list[glyph_row_dict]` ordered deterministically.
    Tablet-first priority: if a character has any `source='tablet'` variants,
    only tablet variants are returned so real handwriting supersedes AI drafts.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, char, source, image_path, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                   visual_width_ratio, visual_height_ratio, ink_center_y
            FROM glyphs
            WHERE profile_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (profile_id,),
        ).fetchall()
    raw: dict[str, list[dict]] = {}
    for r in rows:
        raw.setdefault(r["char"], []).append(dict(r))

    mapping: dict[str, list[dict]] = {}
    for ch, variants in raw.items():
        tablet_only = [v for v in variants if v["source"] == "tablet"]
        mapping[ch] = tablet_only if tablet_only else variants
    return mapping


def delete_glyph(glyph_id: str) -> bool:
    """Delete glyph DB row and remove its PNG file if present."""
    with get_conn() as conn:
        row = conn.execute("SELECT image_path FROM glyphs WHERE id = ?", (glyph_id,)).fetchone()
        if row is None:
            return False
        img_path = Path(row["image_path"])
        conn.execute("DELETE FROM glyphs WHERE id = ?", (glyph_id,))
    if img_path.exists():
        img_path.unlink(missing_ok=True)
    return True


def delete_ai_glyphs(profile_id: str) -> int:
    """Delete all AI-generated glyphs for a profile and remove their PNG files."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, image_path FROM glyphs WHERE profile_id = ? AND source = 'ai_generated'",
            (profile_id,),
        ).fetchall()
        if not rows:
            return 0
        conn.execute(
            "DELETE FROM glyphs WHERE profile_id = ? AND source = 'ai_generated'",
            (profile_id,),
        )
    for r in rows:
        p = Path(r["image_path"])
        if p.exists():
            p.unlink(missing_ok=True)
    return len(rows)


def batch_delete_glyphs(
    profile_id: str,
    glyph_ids: Optional[list[str]] = None,
    chars: Optional[list[str]] = None,
    source_filter: str = "all",
    date_from: str = "",
    date_to: str = "",
    tz_offset_min: int = 0,
) -> dict:
    """
    Delete selected glyph variants by explicit `glyph_ids` or by `chars` scoped by
    `source_filter` and local import date range, removing both DB rows and PNG files.
    """
    clean_ids = list(dict.fromkeys(gid for gid in (glyph_ids or []) if gid))
    clean_chars = list(dict.fromkeys(ch for ch in (chars or []) if ch))
    if not clean_ids and not clean_chars:
        raise ValueError("请至少选择一个要删除的字形")

    norm_from = _normalize_date_str(date_from)
    norm_to = _normalize_date_str(date_to)
    chunk_size = 400

    matched_rows: list[tuple[str, str]] = []
    seen_ids: set[str] = set()

    with get_conn() as conn:
        if clean_ids:
            for i in range(0, len(clean_ids), chunk_size):
                chunk = clean_ids[i : i + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT id, image_path FROM glyphs WHERE profile_id = ? AND id IN ({placeholders})",
                    (profile_id, *chunk),
                ).fetchall()
                for r in rows:
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        matched_rows.append((r["id"], r["image_path"]))
        else:
            for i in range(0, len(clean_chars), chunk_size):
                chunk = clean_chars[i : i + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"""
                    SELECT id, char, source, image_path, created_at
                    FROM glyphs
                    WHERE profile_id = ? AND char IN ({placeholders})
                    """,
                    (profile_id, *chunk),
                ).fetchall()
                for r in rows:
                    if source_filter in ("tablet", "ai_generated") and r["source"] != source_filter:
                        continue
                    local_date = _parse_local_date(r["created_at"], tz_offset_min)
                    if norm_from and local_date < norm_from:
                        continue
                    if norm_to and local_date > norm_to:
                        continue
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        matched_rows.append((r["id"], r["image_path"]))

        matched_ids = [item[0] for item in matched_rows]
        for i in range(0, len(matched_ids), chunk_size):
            chunk = matched_ids[i : i + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            conn.execute(
                f"DELETE FROM glyphs WHERE profile_id = ? AND id IN ({placeholders})",
                (profile_id, *chunk),
            )

    for _, img_path_str in matched_rows:
        p = Path(img_path_str)
        if p.exists():
            p.unlink(missing_ok=True)

    return {"deleted": len(matched_ids), "deleted_ids": matched_ids}


def analyze_text_coverage(profile_id: str, text: str) -> dict:
    """Compute character coverage and missing character frequencies for `text`."""
    chars = extract_required_chars(text)
    counts = Counter(chars)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT char FROM glyphs WHERE profile_id = ?",
            (profile_id,),
        ).fetchall()
    owned = {r["char"] for r in rows}

    unique_chars = len(counts)
    covered_unique = sum(1 for ch in counts if ch in owned)
    missing = [
        {"char": ch, "count": cnt}
        for ch, cnt in counts.most_common()
        if ch not in owned
    ]
    total_chars = len(chars)
    covered_occurrences = sum(cnt for ch, cnt in counts.items() if ch in owned)

    return {
        "total_chars": total_chars,
        "unique_chars": unique_chars,
        "covered_unique": covered_unique,
        "missing_unique": len(missing),
        "coverage_ratio": (covered_occurrences / total_chars) if total_chars > 0 else 1.0,
        "unique_coverage_ratio": (covered_unique / unique_chars) if unique_chars > 0 else 1.0,
        "missing": missing,
        "missing_chars_str": "".join(item["char"] for item in missing),
    }


def export_style_references_96(profile_id: str, out_dir: Path, limit: int = 16) -> list[Path]:
    """
    Export up to `limit` clean 96x96 white-background black-ink reference PNGs
    for Phase 2 FontDiffuser few-shot inference.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, char, image_path FROM glyphs
            WHERE profile_id = ?
            GROUP BY char
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (profile_id, limit),
        ).fetchall()

    exported: list[Path] = []
    for row in rows:
        src_path = Path(row["image_path"])
        if not src_path.exists():
            continue
        rgba = Image.open(src_path).convert("RGBA")
        alpha = np.asarray(rgba.split()[-1], dtype=np.float32) / 255.0
        # Convert black-on-transparent to black-on-white 96x96 RGB
        gray_arr = np.clip((1.0 - alpha) * 255.0, 0, 255).astype(np.uint8)
        ref_img = Image.fromarray(gray_arr, mode="L").resize((96, 96), Image.Resampling.LANCZOS).convert("RGB")
        target = out_dir / f"ref_{row['id']}.png"
        ref_img.save(str(target), format="PNG")
        exported.append(target)
    return exported
