"""Application configuration and dynamic local data paths."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


def get_data_dir() -> Path:
    """Return the root runtime data directory, honoring WRITER_DATA_DIR env var."""
    override = os.environ.get("WRITER_DATA_DIR")
    if override:
        return Path(override)
    return BASE_DIR / "data"


def get_glyphs_dir() -> Path:
    return get_data_dir() / "glyphs"


def get_sheets_dir() -> Path:
    return get_data_dir() / "sheets"


def get_projects_dir() -> Path:
    return get_data_dir() / "projects"


def get_db_path() -> Path:
    return get_data_dir() / "writer.db"


def get_models_dir() -> Path:
    return get_data_dir() / "models"


def get_fontdiffuser_ckpt_dir() -> Path:
    override = os.environ.get("WRITER_FONTDIFFUSER_CKPT_DIR")
    if override:
        return Path(override)
    return get_models_dir() / "fontdiffuser"


def ensure_data_dirs() -> None:
    """Ensure all local data directories exist."""
    for d in (get_data_dir(), get_glyphs_dir(), get_sheets_dir(), get_projects_dir(), get_models_dir()):
        d.mkdir(parents=True, exist_ok=True)


_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\simkai.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
]


def get_reference_font_path() -> str:
    """Locate a reliable local CJK reference font on Windows."""
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError(
        "No Windows CJK reference font found in C:\\Windows\\Fonts (checked simkai, msyh, simsun, simhei)."
    )


_CONTENT_FONT_CANDIDATES = [
    str(BASE_DIR / "backend" / "third_party" / "fontdiffuser" / "ttf" / "KaiXinSongA.ttf"),
    str(BASE_DIR / "backend" / "third_party" / "fontdiffuser" / "ttf" / "KaiXinSongB.ttf"),
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simkai.ttf",
]


def get_content_font_candidates() -> list[str]:
    """Return existing content fonts ordered by preference (KaiXinSong first for FontDiffuser)."""
    existing = [p for p in _CONTENT_FONT_CANDIDATES if Path(p).exists()]
    return existing or [get_reference_font_path()]


def get_content_font_path() -> str:
    """Locate the primary standard Song font used as FontDiffuser content structure input."""
    return get_content_font_candidates()[0]
