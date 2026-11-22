import React, { useEffect, useState } from "react";
import { Download, FileUp, QrCode, Smartphone, X } from "lucide-react";
import { api } from "../api/client";
import { useAppStore } from "../store/useAppStore";
import type { CaptureSheetMeta, LanQrInfo, SheetExtractResult } from "../types";

export const SheetCaptureModal: React.FC = () => {
  const {
    captureModalOpen,
    captureInitialChars,
    captureInitialTitle,
    closeCaptureModal,
    activeProfileId,
    presets,
    refreshGlyphs,
    refreshPreview,
  } = useAppStore();

  const [tab, setTab] = useState<"generate" | "upload">("generate");
  const [sourceMode, setSourceMode] = useState<"custom" | "preset">("preset");
  const [presetId, setPresetId] = useState("lab_report");
  const [customChars, setCustomChars] = useState("");
  const [title, setTitle] = useState("实验报告高频采集表");
  const [variantsPerChar, setVariantsPerChar] = useState(1);
  const [highFreqVariants, setHighFreqVariants] = useState(2);

  const [lanQr, setLanQr] = useState<LanQrInfo | null>(null);
  const [recentSheets, setRecentSheets] = useState<CaptureSheetMeta[]>([]);
  const [genBusy, setGenBusy] = useState(false);
  const [generatedSheet, setGeneratedSheet] = useState<CaptureSheetMeta | null>(null);

  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [overrideSheetId, setOverrideSheetId] = useState("");
  const [uploadBusy, setUploadBusy] = useState(false);
  const [extractResult, setExtractResult] = useState<SheetExtractResult | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!captureModalOpen) return;
    setErrMsg(null);
    setExtractResult(null);
    if (captureInitialChars) {
      setSourceMode("custom");
      setCustomChars(captureInitialChars);
      setTitle(captureInitialTitle || "本篇缺字补采表");
      setTab("generate");
    } else if (captureInitialTitle) {
      setTitle(captureInitialTitle);
    }
    void api.getLanQr().then(setLanQr).catch(() => {});
    void api.listSheets(activeProfileId).then(setRecentSheets).catch(() => {});
  }, [captureModalOpen, captureInitialChars, captureInitialTitle, activeProfileId]);

  if (!captureModalOpen) return null;

  const handleGenerate = async () => {
    setGenBusy(true);
    setErrMsg(null);
    try {
      const selectedPreset = presets.find((p) => p.id === presetId);
      const chars = sourceMode === "custom" ? customChars : selectedPreset?.chars ?? "";
      const res = await api.generateSheet({
        profile_id: activeProfileId,
        title: title.trim() || "手写采集表",
        chars,
        preset_id: sourceMode === "preset" ? presetId : undefined,
        variants_per_char: variantsPerChar,
        high_freq_chars: "的一是不了人在有我他这为之大来以个中上们实验目的原理步骤数据结果",
        high_freq_variants: highFreqVariants,
      });
      setGeneratedSheet(res);
      const list = await api.listSheets(activeProfileId);
      setRecentSheets(list);
    } catch (e) {
      setErrMsg((e as Error).message);
    } finally {
      setGenBusy(false);
    }
  };

  const handleUpload = async () => {
    if (!uploadFile) return;
    setUploadBusy(true);
    setErrMsg(null);
    setExtractResult(null);
    try {
      const ovId = overrideSheetId.trim() ? Number(overrideSheetId.trim()) : null;
      const res = await api.uploadSheet(uploadFile, activeProfileId, ovId);
      setExtractResult(res);
      await refreshGlyphs();
      void refreshPreview();
      const list = await api.listSheets(activeProfileId);
      setRecentSheets(list);
    } catch (e) {
      setErrMsg((e as Error).message);
    } finally {
      setUploadBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3.5">
          <div className="flex items-center gap-2">
            <QrCode className="h-5 w-5 text-blue-600" />
            <h3 className="text-base font-bold text-slate-800">EMR 安卓平板手写采集表</h3>
          </div>
          <button
            type="button"
            onClick={closeCaptureModal}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="grid grid-cols-2 border-b border-slate-200 bg-slate-50 text-sm font-semibold">
          <button
            type="button"
            onClick={() => setTab("generate")}
            className={`py-2.5 ${
              tab === "generate"
                ? "border-b-2 border-blue-600 bg-white text-blue-600"
                : "text-slate-600"
            }`}
          >
            1. 生成采集表 &amp; 平板扫码下载
          </button>
          <button
            type="button"
            onClick={() => setTab("upload")}
            className={`py-2.5 ${
              tab === "upload"
                ? "border-b-2 border-blue-600 bg-white text-blue-600"
                : "text-slate-600"
            }`}
          >
            2. 回传写好的采集表自动切字
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {errMsg && (
            <div className="mb-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              {errMsg}
            </div>
          )}

          {tab === "generate" ? (
            <div className="grid gap-5 md:grid-cols-3">
              <div className="space-y-3 md:col-span-2">
                <div>
                  <label className="mb-1 block text-xs font-semibold text-slate-600">采集表标题</label>
                  <input
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
                  />
                </div>

                <div className="flex gap-2 text-xs">
                  <button
                    type="button"
                    onClick={() => setSourceMode("preset")}
                    className={`rounded-md border px-3 py-1.5 font-medium ${
                      sourceMode === "preset"
                        ? "border-blue-600 bg-blue-50 text-blue-700"
                        : "border-slate-200 text-slate-600"
                    }`}
                  >
                    内置高频字包
                  </button>
                  <button
                    type="button"
                    onClick={() => setSourceMode("custom")}
                    className={`rounded-md border px-3 py-1.5 font-medium ${
                      sourceMode === "custom"
                        ? "border-blue-600 bg-blue-50 text-blue-700"
                        : "border-slate-200 text-slate-600"
                    }`}
                  >
                    自定义 / 缺字列表
                  </button>
                </div>

                {sourceMode === "preset" ? (
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-600">选择字表预设</label>
                    <select
                      value={presetId}
                      onChange={(e) => setPresetId(e.target.value)}
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    >
                      {presets.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} — {p.description}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : (
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-600">
                      待采集字符（自动去重与忽略空格）
                    </label>
                    <textarea
                      rows={4}
                      value={customChars}
                      onChange={(e) => setCustomChars(e.target.value)}
                      placeholder="粘贴文章或输入要采集的汉字/英文/标点..."
                      className="w-full rounded-lg border border-slate-300 p-2.5 text-sm"
                    />
                  </div>
                )}

                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <label className="mb-1 block font-semibold text-slate-600">普通字变体数</label>
                    <select
                      value={variantsPerChar}
                      onChange={(e) => setVariantsPerChar(Number(e.target.value))}
                      className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5"
                    >
                      <option value={1}>每字 1 格</option>
                      <option value={2}>每字 2 格（同字异形）</option>
                      <option value={3}>每字 3 格（高随机度）</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block font-semibold text-slate-600">核心高频字变体数</label>
                    <select
                      value={highFreqVariants}
                      onChange={(e) => setHighFreqVariants(Number(e.target.value))}
                      className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5"
                    >
                      <option value={1}>1 格</option>
                      <option value={2}>2 格（推荐）</option>
                      <option value={3}>3 格</option>
                    </select>
                  </div>
                </div>

                <button
                  type="button"
                  disabled={genBusy}
                  onClick={() => void handleGenerate()}
                  className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {genBusy ? "正在生成 A4 矢量 PDF..." : "生成采集表 PDF"}
                </button>

                {generatedSheet && (
                  <div className="flex items-center justify-between rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs">
                    <div className="text-emerald-900">
                      <b>采集表 #{generatedSheet.sheet_id}</b> 生成完成（{generatedSheet.page_count} 页 /{" "}
                      {generatedSheet.total_slots} 格）
                    </div>
                    <a
                      href={`/api/sheets/${generatedSheet.sheet_id}/pdf`}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 font-semibold text-white hover:bg-emerald-700"
                    >
                      <Download className="h-3.5 w-3.5" />
                      下载 PDF
                    </a>
                  </div>
                )}
              </div>

              {/* LAN QR card */}
              <div className="flex flex-col items-center rounded-xl border border-slate-200 bg-slate-50 p-3.5 text-center">
                <div className="mb-1 flex items-center gap-1 text-xs font-bold text-slate-700">
                  <Smartphone className="h-4 w-4 text-blue-600" />
                  平板扫码直接互传
                </div>
                <p className="mb-2 text-[11px] text-slate-500">
                  同一 Wi-Fi 下用平板浏览器/相机扫码即可直接下载采集表与回传结果
                </p>
                {lanQr ? (
                  <>
                    <div
                      className="rounded-lg bg-white p-2 shadow-sm"
                      dangerouslySetInnerHTML={{ __html: lanQr.svg }}
                    />
                    <a
                      href={lanQr.url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 break-all font-mono text-[11px] text-blue-600 underline"
                    >
                      {lanQr.url}
                    </a>
                  </>
                ) : (
                  <div className="py-8 text-xs text-slate-400">正在生成二维码...</div>
                )}
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 p-6 text-center">
                <FileUp className="mx-auto mb-2 h-8 w-8 text-blue-500" />
                <div className="text-sm font-semibold text-slate-700">
                  上传你在安卓平板笔记 App 中写完导出的 PDF 或 PNG/JPG
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  系统会自动识别四角定位标与页眉条码，滤除浅青辅助格，空白未写的格子自动跳过
                </p>
                <input
                  type="file"
                  accept="application/pdf,image/*"
                  onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                  className="mx-auto mt-3 block text-xs"
                />
              </div>

              <div className="flex items-center gap-3 text-xs">
                <label className="text-slate-600">可选：手动指定采集表 ID（仅当页眉条码识别失败时填写）</label>
                <input
                  type="number"
                  value={overrideSheetId}
                  onChange={(e) => setOverrideSheetId(e.target.value)}
                  placeholder={recentSheets[0] ? `如 ${recentSheets[0].sheet_id}` : "自动识别"}
                  className="w-28 rounded border border-slate-300 px-2 py-1"
                />
              </div>

              <button
                type="button"
                disabled={!uploadFile || uploadBusy}
                onClick={() => void handleUpload()}
                className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {uploadBusy ? "正在透视对齐、去格切字..." : "开始自动切字入库"}
              </button>

              {extractResult && (
                <div className="space-y-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3.5 text-xs">
                  <div className="font-semibold text-emerald-900">
                    入库成功！已提取 {extractResult.extracted_count} 个手写字（跳过空白格{" "}
                    {extractResult.skipped_blank_count} 个）
                  </div>
                  {extractResult.warnings.length > 0 && (
                    <div className="text-amber-700">提示：{extractResult.warnings.join("；")}</div>
                  )}
                  <div className="grid max-h-44 grid-cols-6 gap-2 overflow-y-auto pt-1 sm:grid-cols-8">
                    {extractResult.extracted_glyphs.slice(0, 48).map((g) => (
                      <div
                        key={g.id}
                        className="flex flex-col items-center rounded border border-emerald-200 bg-white p-1"
                      >
                        <img src={g.image_url} alt={g.char} className="h-10 w-10 object-contain" />
                        <span className="text-[11px] font-bold text-slate-700">{g.char}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
