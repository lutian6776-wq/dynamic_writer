"""SQLite connection helpers and schema initialization."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from app.config import ensure_data_dirs, get_db_path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS glyphs (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    char TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'tablet',
    image_path TEXT NOT NULL,
    bbox_x0 REAL NOT NULL,
    bbox_y0 REAL NOT NULL,
    bbox_x1 REAL NOT NULL,
    bbox_y1 REAL NOT NULL,
    visual_width_ratio REAL NOT NULL,
    visual_height_ratio REAL NOT NULL,
    ink_center_y REAL NOT NULL,
    sheet_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_glyphs_profile_char
    ON glyphs(profile_id, char);

CREATE INDEX IF NOT EXISTS idx_glyphs_profile_created
    ON glyphs(profile_id, created_at);

CREATE TABLE IF NOT EXISTS capture_sheets (
    sheet_id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL,
    title TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    cells_json TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'generated',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    template_path TEXT NOT NULL,
    template_kind TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    pages_meta_json TEXT NOT NULL,
    regions_json TEXT NOT NULL,
    style_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    """Return current UTC ISO-8601 timestamp."""
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection with Row factory and automatic commit/rollback."""
    ensure_data_dirs()
    conn = sqlite3.connect(str(get_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Initialize SQLite schema and ensure default profile exists."""
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
        row = conn.execute("SELECT id FROM profiles WHERE id = 'default'").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO profiles (id, name, created_at) VALUES (?, ?, ?)",
                ("default", "我的笔迹", now_iso()),
            )
