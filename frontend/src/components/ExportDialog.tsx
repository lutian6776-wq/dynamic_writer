import React, { useState } from "react";
import { Download, Printer, Ruler, X } from "lucide-react";
import { api } from "../api/client";
import { useAppStore } from "../store/useAppStore";

export const ExportDialog: React.FC = () => {
  const {
    exportModalOpen,
    setExportModalOpen,
    activeProject,
    previewStats,
  } = useAppStore();

  const [mode, setMode] = useState<"composite" | "overlay_only">("composite");
  const [dpi, setDpi] = useState<300 | 600>(300);
  const [offsetX, setOffsetX] = useState(0.0);
  const [offsetY, setOffsetY] = useState(0.0);
  const [blankMissing, setBlankMissing] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!exportModalOpen || !activeProject) return null;

  const missingCount = previewStats?.missing_unique ?? 0;

  const handleExport = async () => {
    setBusy(true);
    setErr(null);
    try {
      const blob = await api.exportPdf(activeProject.id, {
        dpi,
        mode,
        offset_x_mm: mode === "overlay_only" ? offsetX : 0,
        offset_y_mm: mode === "overlay_only" ? offsetY : 0,
        missing_char_mode: blankMissing ? "blank" : "highlight",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${activeProject.name}_${mode === "composite" ? "整体打印" : "套打手写层"}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setExportModalOpen(false);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="w-full max-w-lg rounded-2xl bg-white p-5 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Printer className="h-5 w-5 text-blue-600" />
            <h3 className="text-base font-bold text-slate-800">导出高清打印 PDF</h3>
          </div>
          <button
            type="button"
            onClick={() => setExportModalOpen(false)}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {err && (
          <div className="mb-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {err}
          </div>
        )}

        {missingCount > 0 && (
          <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
            <div>
              当前文档尚有 <b>{missingCount}</b> 个未录入字库的新字（可在导出后留出标准字宽，用真笔直接补写，真假混写更自然）。
            </div>
            <label className="mt-2 flex items-center gap-2 font-semibold">
              <input
                type="checkbox"
                checked={blankMissing}
                onChange={(e) => setBlankMissing(e.target.checked)}
              />
              缺字精准留白（推荐：打印纸上不印红框，留白位置供亲手补写）
            </label>
          </div>
        )}

        <div className="space-y-4 text-xs">
          <div>
            <div className="mb-1.5 font-semibold text-slate-700">打印输出模式</div>
            <div className="grid grid-cols-2 gap-2.5">
              <button
                type="button"
                onClick={() => setMode("composite")}
                className={`rounded-xl border p-3 text-left ${
                  mode === "composite"
                    ? "border-blue-600 bg-blue-50 text-blue-900"
                    : "border-slate-200 text-slate-700 hover:bg-slate-50"
                }`}
              >
                <div className="font-bold">含底图整体打印</div>
                <div className="mt-1 text-[11px] text-slate-500">
                  保留原矢量底图与高清手写层，直接打到空白 A4 纸上
                </div>
              </button>
              <button
                type="button"
                onClick={() => setMode("overlay_only")}
                className={`rounded-xl border p-3 text-left ${
                  mode === "overlay_only"
                    ? "border-blue-600 bg-blue-50 text-blue-900"
                    : "border-slate-200 text-slate-700 hover:bg-slate-50"
                }`}
              >
                <div className="font-bold">纯手写层套打</div>
                <div className="mt-1 text-[11px] text-slate-500">
                  隐藏底图，将现有纸质实验报告本放进打印机精准套印
                </div>
              </button>
            </div>
          </div>

          {mode === "overlay_only" && (
            <div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1 font-semibold text-slate-700">
                  <Ruler className="h-3.5 w-3.5" />
                  打印机进纸偏移校准 (mm)
                </span>
                <a
                  href="/api/export/calibration-pdf"
                  target="_blank"
                  rel="noreferrer"
                  className="text-blue-600 underline"
                >
                  下载套打校准十字页
                </a>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-slate-600">X 水平偏移 (mm，右正左负)</label>
                  <input
                    type="number"
                    step={0.5}
                    value={offsetX}
                    onChange={(e) => setOffsetX(Number(e.target.value))}
                    className="w-full rounded border border-slate-300 bg-white px-2.5 py-1"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-slate-600">Y 垂直偏移 (mm，下正上负)</label>
                  <input
                    type="number"
                    step={0.5}
                    value={offsetY}
                    onChange={(e) => setOffsetY(Number(e.target.value))}
                    className="w-full rounded border border-slate-300 bg-white px-2.5 py-1"
                  />
                </div>
              </div>
            </div>
          )}

          <div>
            <div className="mb-1.5 font-semibold text-slate-700">输出分辨率</div>
            <div className="flex gap-2">
              {([300, 600] as const).map((val) => (
                <button
                  key={val}
                  type="button"
                  onClick={() => setDpi(val)}
                  className={`flex-1 rounded-lg border py-2 font-semibold ${
                    dpi === val
                      ? "border-blue-600 bg-blue-50 text-blue-700"
                      : "border-slate-200 text-slate-600"
                  }`}
                >
                  {val} DPI {val === 300 ? "（日常推荐 · 速度最快）" : "（极清笔锋 · 体积较大）"}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => setExportModalOpen(false)}
            className="rounded-lg border border-slate-300 px-4 py-2 text-xs font-semibold text-slate-700"
          >
            取消
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void handleExport()}
            className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            <Download className="h-4 w-4" />
            {busy ? "正在无损渲染导出..." : "生成并下载 PDF"}
          </button>
        </div>
      </div>
    </div>
  );
};
