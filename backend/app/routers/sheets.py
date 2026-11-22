"""Capture sheet generation, PDF download, upload extraction, and LAN QR endpoints."""

from __future__ import annotations

import io
import socket
from pathlib import Path
from typing import Optional

import segno
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app.data.common_chars import PRESETS_BY_ID
from app.models import SheetGenerateRequest
from app.services.sheet_extractor import extract_from_upload
from app.services.sheet_generator import (
    generate_capture_sheet,
    get_capture_sheet_record,
    list_capture_sheets,
)

router = APIRouter(prefix="/api/sheets", tags=["sheets"])


def _detect_lan_ip() -> str:
    """Detect real private LAN IPv4 address instantaneously via psutil (avoids DNS timeouts & TUN 198.18.*)."""
    import ipaddress
    import psutil

    candidates: list[tuple[int, str]] = []
    try:
        for iface_name, addrs in psutil.net_if_addrs().items():
            low_name = iface_name.lower()
            # Skip known virtual/VPN/loopback adapters when ranking
            is_virtual = any(k in low_name for k in ("loopback", "vethernet", "wsl", "docker", "tun", "tap", "clash", "mihomo", "tailscale"))
            for a in addrs:
                if a.family == socket.AF_INET and a.address and not a.address.startswith("127.") and not a.address.startswith("169.254."):
                    candidates.append((0 if not is_virtual else 1, a.address))
    except Exception:
        pass

    if not candidates:
        return "127.0.0.1"

    # Sort non-virtual first, and prefer 192.168.x.x (not .1) -> 192.168.x.1 -> 10.x.x.x -> other RFC1918
    def _rank(item: tuple[int, str]) -> tuple[int, int, str]:
        virt_flag, ip_str = item
        try:
            addr = ipaddress.IPv4Address(ip_str)
            in_tun = ipaddress.IPv4Address("198.18.0.0") <= addr <= ipaddress.IPv4Address("198.19.255.255")
            in_cgnat = ipaddress.IPv4Address("100.64.0.0") <= addr <= ipaddress.IPv4Address("100.127.255.255")
            if in_tun or in_cgnat or not addr.is_private:
                return (virt_flag + 2, 9, ip_str)
        except ValueError:
            return (9, 9, ip_str)

        if ip_str.startswith("192.168."):
            return (virt_flag, 0 if not ip_str.endswith(".1") else 1, ip_str)
        if ip_str.startswith("10."):
            return (virt_flag, 2, ip_str)
        return (virt_flag, 3, ip_str)

    candidates.sort(key=_rank)
    return candidates[0][1]


@router.get("")
def get_sheets(profile_id: Optional[str] = Query(default=None)) -> list[dict]:
    return list_capture_sheets(profile_id)


@router.get("/lan-qr")
def get_lan_qr(request: Request) -> dict:
    lan_ip = _detect_lan_ip()
    port = request.url.port or 8000
    url = f"http://{lan_ip}:{port}/mobile"
    qr = segno.make(url)
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=5, border=2, xmldecl=False)
    return {
        "url": url,
        "ip": lan_ip,
        "svg": buf.getvalue().decode("utf-8"),
    }


@router.post("/generate")
def create_sheet(body: SheetGenerateRequest) -> dict:
    chars = body.chars
    if not chars.strip() and body.preset_id:
        preset = PRESETS_BY_ID.get(body.preset_id)
        if preset is None:
            raise HTTPException(status_code=400, detail="未知字表预设")
        chars = preset["chars"]
    try:
        return generate_capture_sheet(
            profile_id=body.profile_id,
            title=body.title,
            chars=chars,
            variants_per_char=body.variants_per_char,
            high_freq_chars=body.high_freq_chars,
            high_freq_variants=body.high_freq_variants,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{sheet_id}/pdf")
def download_sheet_pdf(sheet_id: int) -> FileResponse:
    rec = get_capture_sheet_record(sheet_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="采集表不存在")
    path = Path(rec["pdf_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="采集表 PDF 文件不存在")
    return FileResponse(
        str(path),
        media_type="application/pdf",
        filename=f"capture_sheet_{sheet_id}.pdf",
    )


@router.post("/upload")
async def upload_completed_sheet(
    file: UploadFile = File(...),
    profile_id: str = Form(default="default"),
    override_sheet_id: Optional[int] = Form(default=None),
    override_page_index: Optional[int] = Form(default=None),
) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传文件为空")
    try:
        return extract_from_upload(
            file_bytes=data,
            filename=file.filename or "upload.pdf",
            profile_id=profile_id,
            override_sheet_id=override_sheet_id,
            override_page_index=override_page_index,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
