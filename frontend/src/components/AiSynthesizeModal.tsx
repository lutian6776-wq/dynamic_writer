import React, { useEffect, useRef, useState } from "react";
import { CheckCircle2, Cpu, Loader2, RefreshCw, Trash2, X } from "lucide-react";
import { api } from "../api/client";
import { useAppStore } from "../store/useAppStore";
import type { AiJobStatus, GlyphSummary } from "../types";

export const AiSynthesizeModal: React.FC = () => {
  const {
    aiModalOpen,
    aiInitialChars,
    aiReplaceExisting,
    closeAiModal,
    activeProfileId,
    aiStatus,
    refreshAiStatus,
    refreshGlyphs,
    refreshPreview,
  } = useAppStore();

  const [chars, setChars] = useState("");
  const [variantsPerChar, setVariantsPerChar] = useState(1);
  const [steps, setSteps] = useState(20);
  const [guidance, setGuidance] = useState(7.5);
  const [seed, setSeed] = useState(42);
  const [replaceExistingAi, setReplaceExistingAi] = useState(false);
  const [selectedRefIds, setSelectedRefIds] = useState<string[]>([]);
  const [showRefPicker, setShowRefPicker] = useState(false);
  const [allTabletGlyphs, setAllTabletGlyphs] = useState<GlyphSummary[]>([]);

  const [job, setJob] = useState<AiJobStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const pollRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!aiModalOpen) {
      window.clearInterval(pollRef.current);
      return;
    }
    let cancelled = false;
    setErrMsg(null);
    setJob(null);
    setChars(aiInitialChars || "");
    setReplaceExistingAi(aiReplaceExisting);
    if (aiReplaceExisting) {
      setSeed(Math.floor(Math.random() * 90000) + 100);
    }
    setSelectedRefIds([]);
    void refreshAiStatus();
    void api
      .listGlyphs(activeProfileId, "", "tablet")
      .then((list) => {
        if (!cancelled) {
          setAllTabletGlyphs(list);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAllTabletGlyphs([]);
        }
      });
    return () => {
      cancelled = true;
      window.clearInterval(pollRef.current);
    };
  }, [aiModalOpen, aiInitialChars, aiReplaceExisting, activeProfileId, refreshAiStatus]);

  if (!aiModalOpen) return null;

  const tabletGlyphs = allTabletGlyphs;
  const tabletCharSet = new Set(tabletGlyphs.map((g) => g.char));
  const uniqueChars = Array.from(new Set(Array.from(chars).filter((c) => !/\s/.test(c))));
  const overlappingTabletCount = uniqueChars.filter((ch) => tabletCharSet.has(ch)).length;

  const toggleRefId = (id: string) => {
    setSelectedRefIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : prev.length < 4 ? [...prev, id] : prev
    );
  };

  const handleStart = async () => {
    if (uniqueChars.length === 0) {
      setErrMsg("请输入至少一个需要推理补全的字符");
      return;
    }
    setBusy(true);
    setErrMsg(null);
    try {
      const started = await api.startAiSynthesize({
        profile_id: activeProfileId,
        chars: uniqueChars.join(""),
        variants_per_char: variantsPerChar,
        num_inference_steps: steps,
        guidance_scale: guidance,
        style_glyph_ids: selectedRefIds.length > 0 ? selectedRefIds : null,
        seed,
        replace_existing_ai: replaceExistingAi,
      });
      setJob(started);
      window.clearInterval(pollRef.current);
      pollRef.current = window.setInterval(async () => {
        try {
          const latest = await api.getAiJob(started.job_id);
          setJob(latest);
          if (latest.status !== "running") {
            window.clearInterval(pollRef.current);
            setBusy(false);
            await refreshGlyphs();
            await refreshAiStatus();
            void refreshPreview();
          }
        } catch (err) {
          window.clearInterval(pollRef.current);
          setBusy(false);
          setErrMsg((err as Error).message);
        }
      }, 700);
    } catch (e) {
      setBusy(false);
      setErrMsg((e as Error).message);
    }
  };

  const handleUnload = async () => {
    await api.unloadAiModel();
    await refreshAiStatus();
  };

  const handleClearAi = async () => {
    if (!window.confirm("确定删除当前笔迹档案下所有 AI 推理生成的字形吗？（不影响平板采集的真迹）")) {
      return;
    }
    await api.deleteAllAiGlyphs(activeProfileId);
    await refreshGlyphs();
    void refreshPreview();
  };

  const pct = job && job.total > 0 ? Math.round((job.completed / job.total) * 100) : 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3.5">
          <div className="flex items-center gap-2">
            <Cpu className="h-5 w-5 text-indigo-600" />
            <h3 className="text-base font-bold text-slate-800">
              {replaceExistingAi
                ? "本地 GPU 批量 AI 重绘（FontDiffuser）"
                : "本地 GPU 少样本 AI 缺字补全（FontDiffuser）"}
            </h3>
          </div>
          <button
            type="button"
            onClick={closeAiModal}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-5 text-xs">
          {/* GPU & Model Status Card */}
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-slate-50 p-3">
            <div>
              <div className="font-semibold text-slate-800">
                {aiStatus?.available
                  ? `就绪：${aiStatus.gpu_name ?? aiStatus.device} (${aiStatus.vram_total_mb} MB 显存)`
                  : `未就绪：${aiStatus?.error ?? "正在检查环境..."}`}
              </div>
              <div className="mt-0.5 text-[11px] text-slate-500">
                权重目录：{aiStatus?.ckpt_dir ?? "..."} ·{" "}
                {aiStatus?.loaded
                  ? `模型已加载（占用约 ${aiStatus.vram_allocated_mb} MB）`
                  : "模型将在开始推理时按需加载"}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {aiStatus?.loaded && (
                <button
                  type="button"
                  onClick={() => void handleUnload()}
                  className="rounded-md border border-slate-300 bg-white px-2.5 py-1 font-medium text-slate-700 hover:bg-slate-100"
                >
                  释放显存
                </button>
              )}
              <button
                type="button"
                onClick={() => void handleClearAi()}
                className="flex items-center gap-1 rounded-md border border-rose-200 bg-white px-2.5 py-1 font-medium text-rose-600 hover:bg-rose-50"
              >
                <Trash2 className="h-3 w-3" />
                清空旧 AI 字
              </button>
            </div>
          </div>

          {tabletGlyphs.length === 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800">
              提示：当前档案还没有任何平板真迹样本。请先用采集表录入几个汉字作为风格参考，AI 才能模仿你的笔迹。
            </div>
          )}

          {errMsg && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-rose-700">
              {errMsg}
            </div>
          )}

          <div>
            <div className="mb-1 flex items-center justify-between">
              <label className="font-semibold text-slate-700">
                待推理补全的字符（共 {uniqueChars.length} 个不重复字，预计约{" "}
                {Math.max(1, Math.round(uniqueChars.length * variantsPerChar * 1.4))} 秒）
              </label>
            </div>
            <textarea
              rows={3}
              value={chars}
              onChange={(e) => setChars(e.target.value)}
              placeholder="输入或粘贴缺字（例如：熵谱衍射共振），系统自动去重..."
              className="w-full rounded-lg border border-slate-300 p-2.5 text-sm focus:border-indigo-500 focus:outline-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div>
              <label className="mb-1 block font-semibold text-slate-600">每字变体数</label>
              <select
                value={variantsPerChar}
                onChange={(e) => setVariantsPerChar(Number(e.target.value))}
                className="w-full rounded-lg border border-slate-300 px-2 py-1.5"
              >
                <option value={1}>1 个</option>
                <option value={2}>2 个</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block font-semibold text-slate-600">采样步数</label>
              <select
                value={steps}
                onChange={(e) => setSteps(Number(e.target.value))}
                className="w-full rounded-lg border border-slate-300 px-2 py-1.5"
              >
                <option value={15}>15 步（极速）</option>
                <option value={20}>20 步（推荐）</option>
                <option value={30}>30 步（精细）</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block font-semibold text-slate-600">
                风格强度 ({guidance.toFixed(1)})
              </label>
              <input
                type="range"
                min={4.5}
                max={10.5}
                step={0.5}
                value={guidance}
                onChange={(e) => setGuidance(Number(e.target.value))}
                className="mt-1.5 w-full"
              />
            </div>
            <div>
              <label className="mb-1 block font-semibold text-slate-600">随机种子</label>
              <div className="flex items-center gap-1">
                <input
                  type="number"
                  value={seed}
                  onChange={(e) => setSeed(Number(e.target.value))}
                  className="w-full rounded-lg border border-slate-300 px-2 py-1"
                />
                <button
                  type="button"
                  title="随机换一个种子"
                  onClick={() => setSeed(Math.floor(Math.random() * 90000) + 100)}
                  className="rounded-lg border border-slate-300 p-1.5 text-slate-600 hover:bg-slate-100"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </div>

          <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-slate-700">
            <input
              type="checkbox"
              checked={replaceExistingAi}
              onChange={(e) => setReplaceExistingAi(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
            />
            <span>重绘时自动替换所选字符的旧 AI 变体（仅替换 AI 变体，不影响平板真迹）</span>
          </label>

          {replaceExistingAi && overlappingTabletCount > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800">
              提示：待重绘字符中有 {overlappingTabletCount} 个已存在平板真迹。AI 重绘会保留真迹，排版时仍优先使用真迹；如需改用 AI 版本请先在字库中删除对应真迹。
            </div>
          )}

          {/* Optional style reference picker */}
          <div className="rounded-xl border border-slate-200 p-3">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-slate-700">
                风格参考字选择：
                {selectedRefIds.length === 0
                  ? "自动精选代表性真迹字（推荐）"
                  : `已手动指定 ${selectedRefIds.length} 枚参考字`}
              </span>
              <button
                type="button"
                onClick={() => setShowRefPicker(!showRefPicker)}
                className="text-indigo-600 underline"
              >
                {showRefPicker ? "收起" : "手动挑选参考字"}
              </button>
            </div>
            {showRefPicker && (
              <div className="mt-2.5 grid max-h-36 grid-cols-6 gap-1.5 overflow-y-auto pt-1 sm:grid-cols-8">
                {tabletGlyphs.slice(0, 48).map((g) => {
                  const vid = g.variants.find((v) => v.source === "tablet")?.id;
                  if (!vid) return null;
                  const active = selectedRefIds.includes(vid);
                  return (
                    <button
                      key={vid}
                      type="button"
                      onClick={() => toggleRefId(vid)}
                      className={`flex flex-col items-center rounded border p-1 ${
                        active ? "border-indigo-600 bg-indigo-50" : "border-slate-200"
                      }`}
                    >
                      <img src={g.latest_image_url} alt={g.char} className="h-9 w-9 object-contain" />
                      <span className="text-[10px] font-bold">{g.char}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <button
            type="button"
            disabled={busy || !aiStatus?.available || tabletGlyphs.length === 0}
            onClick={() => void handleStart()}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Cpu className="h-4 w-4" />}
            {busy ? "正在本地 GPU 推理生成..." : "开始本地 GPU 推理补全"}
          </button>

          {job && (
            <div className="space-y-2 rounded-xl border border-indigo-200 bg-indigo-50/70 p-3">
              <div className="flex items-center justify-between font-semibold text-indigo-900">
                <span className="flex items-center gap-1.5">
                  {job.status === "done" && <CheckCircle2 className="h-4 w-4 text-emerald-600" />}
                  {job.status === "running"
                    ? `正在推理「${job.current_char}」 (${job.completed}/${job.total})`
                    : `生成完成！共生成 ${job.generated_glyphs.length} 枚字形，耗时 ${job.elapsed_sec} 秒${
                        (job.replaced_count ?? 0) > 0
                          ? `（已替换旧 AI 变体 ${job.replaced_count} 枚）`
                          : ""
                      }`}
                </span>
                <span>{pct}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-indigo-100">
                <div
                  className="h-full bg-indigo-600 transition-all"
                  style={{ width: `${pct}%` }}
                />
              </div>
              {job.errors.length > 0 && (
                <div className="text-rose-700">错误：{job.errors.join("；")}</div>
              )}
              {job.generated_glyphs.length > 0 && (
                <div className="grid max-h-40 grid-cols-6 gap-2 overflow-y-auto pt-1 sm:grid-cols-8">
                  {job.generated_glyphs.map((g) => (
                    <div
                      key={g.id}
                      className="flex flex-col items-center rounded border border-indigo-200 bg-white p-1"
                    >
                      <img src={g.image_url} alt={g.char} className="h-10 w-10 object-contain" />
                      <span className="text-[11px] font-bold text-slate-700">{g.char}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
