"""Profile management API routes."""

from __future__ import annotations

import uuid
from fastapi import APIRouter, HTTPException

from app.db import get_conn, now_iso
from app.models import ProfileCreate, ProfileOut

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.get("", response_model=list[ProfileOut])
def list_profiles() -> list[ProfileOut]:
    with get_conn() as conn:
        rows = conn.execute("SELECT id, name, created_at FROM profiles ORDER BY created_at ASC").fetchall()
    return [ProfileOut(**dict(r)) for r in rows]


@router.post("", response_model=ProfileOut)
def create_profile(body: ProfileCreate) -> ProfileOut:
    pid = uuid.uuid4().hex[:12]
    created_at = now_iso()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO profiles (id, name, created_at) VALUES (?, ?, ?)",
            (pid, body.name.strip(), created_at),
        )
    return ProfileOut(id=pid, name=body.name.strip(), created_at=created_at)


@router.delete("/{profile_id}")
def delete_profile(profile_id: str) -> dict:
    if profile_id == "default":
        raise HTTPException(status_code=400, detail="不能删除默认笔迹档案")
    with get_conn() as conn:
        res = conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="档案不存在")
    return {"deleted": True}
