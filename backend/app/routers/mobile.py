"""Mobile-first LAN tablet page for one-tap capture sheet download & upload."""

from __future__ import annotations

import html

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.db import get_conn
from app.services.sheet_generator import list_capture_sheets

router = APIRouter(tags=["mobile"])


@router.get("/mobile", response_class=HTMLResponse)
def mobile_tablet_page() -> HTMLResponse:
    sheets = list_capture_sheets()[:12]
    with get_conn() as conn:
        profiles = [dict(r) for r in conn.execute("SELECT id, name FROM profiles ORDER BY created_at ASC").fetchall()]

    profile_opts = "".join(
        f'<option value="{html.escape(p["id"])}">{html.escape(p["name"])}</option>'
        for p in profiles
    )
    if sheets:
        sheet_items = "".join(
            f"""
            <div class="sheet-card">
              <div>
                <div class="sheet-title">#{s['sheet_id']} · {html.escape(s['title'])}</div>
                <div class="sheet-meta">共 {s['page_count']} 页 · 状态: {'已导入' if s['status'] == 'imported' else '待书写'}</div>
              </div>
              <a class="btn-secondary" href="/api/sheets/{s['sheet_id']}/pdf" target="_blank">下载 PDF</a>
            </div>
            """
            for s in sheets
        )
    else:
        sheet_items = '<div class="empty">暂无采集表，请先在电脑端生成采集表。</div>'

    page_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>墨迹 · 平板字迹采集互传</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; padding: 16px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: #f4f6f9; color: #1e293b;
    }}
    .container {{ max-width: 560px; margin: 0 auto; }}
    h1 {{ font-size: 20px; margin: 4px 0 6px; }}
    .sub {{ font-size: 13px; color: #64748b; margin-bottom: 16px; }}
    .card {{
      background: #fff; border-radius: 14px; padding: 16px;
      box-shadow: 0 2px 10px rgba(15, 23, 42, 0.06); margin-bottom: 16px;
    }}
    .card h2 {{ font-size: 16px; margin: 0 0 12px; }}
    .sheet-card {{
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
      padding: 12px 0; border-bottom: 1px solid #f1f5f9;
    }}
    .sheet-card:last-child {{ border-bottom: none; }}
    .sheet-title {{ font-weight: 600; font-size: 15px; }}
    .sheet-meta {{ font-size: 12px; color: #64748b; margin-top: 2px; }}
    .btn-primary {{
      width: 100%; border: none; border-radius: 10px; padding: 13px 16px;
      background: #2563eb; color: #fff; font-size: 15px; font-weight: 600; cursor: pointer;
    }}
    .btn-primary:disabled {{ opacity: 0.6; }}
    .btn-secondary {{
      text-decoration: none; white-space: nowrap;
      background: #eff6ff; color: #1d4ed8; padding: 9px 14px; border-radius: 8px;
      font-size: 13px; font-weight: 600;
    }}
    label {{ display: block; font-size: 13px; font-weight: 600; margin: 10px 0 6px; }}
    select, input[type="file"] {{
      width: 100%; padding: 10px; border: 1px solid #cbd5e1; border-radius: 8px;
      font-size: 14px; background: #fff;
    }}
    .result {{ margin-top: 12px; padding: 10px 12px; border-radius: 8px; font-size: 13px; display: none; }}
    .ok {{ background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }}
    .err {{ background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }}
    .empty {{ font-size: 13px; color: #94a3b8; padding: 8px 0; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>墨迹 · 平板采集互传</h1>
    <div class="sub">下载 PDF 到平板笔记 App 书写，完成后直接导出回传</div>

    <div class="card">
      <h2>1. 下载待写采集表</h2>
      {sheet_items}
    </div>

    <div class="card">
      <h2>2. 回传写好的采集表（PDF 或图片）</h2>
      <form id="uploadForm">
        <label for="profileSelect">入库档案</label>
        <select id="profileSelect" name="profile_id">{profile_opts}</select>

        <label for="fileInput">选择写好的 PDF 或 PNG/JPG 文件</label>
        <input id="fileInput" name="file" type="file" accept="application/pdf,image/*" required />

        <div style="margin-top: 14px;">
          <button id="submitBtn" class="btn-primary" type="submit">上传并自动切字入库</button>
        </div>
      </form>
      <div id="resultBox" class="result"></div>
    </div>
  </div>

  <script>
    const form = document.getElementById('uploadForm');
    const btn = document.getElementById('submitBtn');
    const resBox = document.getElementById('resultBox');
    form.addEventListener('submit', async (e) => {{
      e.preventDefault();
      const fileInput = document.getElementById('fileInput');
      if (!fileInput.files.length) return;
      btn.disabled = true;
      btn.textContent = '正在定位对齐并切字...';
      resBox.style.display = 'none';
      const fd = new FormData(form);
      try {{
        const resp = await fetch('/api/sheets/upload', {{ method: 'POST', body: fd }});
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || '上传失败');
        resBox.className = 'result ok';
        let msg = `入库成功！已提取 ${{data.extracted_count}} 个手写字（跳过空白格 ${{data.skipped_blank_count}} 个）。`;
        if (data.warnings && data.warnings.length) {{
          msg += '<br/>提示：' + data.warnings.join('；');
        }}
        resBox.innerHTML = msg;
      }} catch (err) {{
        resBox.className = 'result err';
        resBox.textContent = '处理失败：' + err.message;
      }} finally {{
        resBox.style.display = 'block';
        btn.disabled = false;
        btn.textContent = '上传并自动切字入库';
      }}
    }});
  </script>
</body>
</html>
"""
    return HTMLResponse(content=page_html)
