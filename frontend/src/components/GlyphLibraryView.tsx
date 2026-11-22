import React, { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Calendar,
  Check,
  CheckSquare,
  Cpu,
  Eye,
  Loader2,
  QrCode,
  RotateCcw,
  Search,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { api } from "../api/client";
import { useAppStore } from "../store/useAppStore";
import type { GlyphSortBy, GlyphSummary, GlyphVariant } from "../types";

function formatLocalYmd(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function daysAgoYmd(days: number): string {
  const dt = new Date();
  dt.setDate(dt.getDate() - days);
  return formatLocalYmd(dt);
}

function formatIsoDateTime(iso: string): string {
  if (!iso) return "";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) {
    return iso.slice(0, 16).replace("T", " ");
  }
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, "0");
  const d = String(dt.getDate()).padStart(2, "0");
  const hh = String(dt.getHours()).padStart(2, "0");
  const mm = String(dt.getMinutes()).padStart(2, "0");
  return `${y}-${m}-${d} ${hh}:${mm}`;
}

function getMatchingVariants(
  g: GlyphSummary,
  sourceFilter: "all" | "tablet" | "ai_generated"
): GlyphVariant[] {
  if (sourceFilter === "all") return g.variants;
  return g.variants.filter((v) => v.source === sourceFilter);
}

export const GlyphLibraryView: React.FC = () => {
  const {
    glyphs,
    glyphSearch,
    glyphSourceFilter,
    glyphDateFrom,
    glyphDateTo,
    glyphSort,
    glyphImportDates,
    setGlyphSearch,
    setGlyphSourceFilter,
    setGlyphDateRange,
    setGlyphSort,
    resetGlyphFilters,
    deleteGlyphVariant,
    batchDeleteGlyphs,
    openCaptureModal,
    openAiModal,
    aiStatus,
    refreshAiStatus,
  } = useAppStore();

  const [inspectChar, setInspectChar] = useState<GlyphSummary | null>(null);
  const [batchMode, setBatchMode] = useState(false);
  const [selectedChars, setSelectedChars] = useState<Set<string>>(() => new Set());
  const [lastClickedIdx, setLastClickedIdx] = useState<number | null>(null);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [isDeletingBatch, setIsDeletingBatch] = useState(false);
  const [batchNotice, setBatchNotice] = useState<string | null>(null);

  // Prune selection when active filters/search hide characters
  useEffect(() => {
    const visibleSet = new Set(glyphs.map((g) => g.char));
    setSelectedChars((prev) => {
      if (prev.size === 0) return prev;
      let changed = false;
      const next = new Set<string>();
      for (const ch of prev) {
        if (visibleSet.has(ch)) {
          next.add(ch);
        } else {
          changed = true;
        }
      }
      return changed ? next : prev;
    });
    setLastClickedIdx(null);
  }, [glyphs]);

  const handleUnloadGpu = async () => {
    await api.unloadAiModel();
    await refreshAiStatus();
  };

  const todayYmd = formatLocalYmd(new Date());
  const last3Ymd = daysAgoYmd(2);
  const last7Ymd = daysAgoYmd(6);

  const datePresetValue = useMemo(() => {
    if (!glyphDateFrom && !glyphDateTo) return "";
    if (glyphDateFrom === todayYmd && glyphDateTo === todayYmd) return "today";
    if (glyphDateFrom === last3Ymd && glyphDateTo === todayYmd) return "last3";
    if (glyphDateFrom === last7Ymd && glyphDateTo === todayYmd) return "last7";
    if (
      glyphDateFrom &&
      glyphDateFrom === glyphDateTo &&
      glyphImportDates.some((d) => d.date === glyphDateFrom)
    ) {
      return `date:${glyphDateFrom}`;
    }
    return "custom";
  }, [glyphDateFrom, glyphDateTo, glyphImportDates, todayYmd, last3Ymd, last7Ymd]);

  const handleDatePresetChange = (val: string) => {
    if (!val) {
      void setGlyphDateRange("", "");
      return;
    }
    if (val === "today") {
      void setGlyphDateRange(todayYmd, todayYmd);
      return;
    }
    if (val === "last3") {
      void setGlyphDateRange(last3Ymd, todayYmd);
      return;
    }
    if (val === "last7") {
      void setGlyphDateRange(last7Ymd, todayYmd);
      return;
    }
    if (val.startsWith("date:")) {
      const d = val.slice(5);
      void setGlyphDateRange(d, d);
    }
  };

  const handleDateFromChange = (nextFrom: string) => {
    if (nextFrom && glyphDateTo && nextFrom > glyphDateTo) {
      void setGlyphDateRange(nextFrom, nextFrom);
    } else {
      void setGlyphDateRange(nextFrom, glyphDateTo);
    }
  };

  const handleDateToChange = (nextTo: string) => {
    if (nextTo && glyphDateFrom && nextTo < glyphDateFrom) {
      void setGlyphDateRange(nextTo, nextTo);
    } else {
      void setGlyphDateRange(glyphDateFrom, nextTo);
    }
  };

  const toggleBatchMode = () => {
    setBatchMode((prev) => {
      if (prev) {
        setSelectedChars(new Set());
        setLastClickedIdx(null);
        setConfirmDeleteOpen(false);
      }
      return !prev;
    });
  };

  const handleCardClick = (g: GlyphSummary, idx: number, e: React.MouseEvent) => {
    if (!batchMode) {
      setInspectChar(g);
      return;
    }

    if (e.shiftKey && lastClickedIdx !== null && lastClickedIdx >= 0 && lastClickedIdx < glyphs.length) {
      const start = Math.min(lastClickedIdx, idx);
      const end = Math.max(lastClickedIdx, idx);
      setSelectedChars((prev) => {
        const next = new Set(prev);
        for (let i = start; i <= end; i++) {
          next.add(glyphs[i].char);
        }
        return next;
      });
      setLastClickedIdx(idx);
      return;
    }

    setSelectedChars((prev) => {
      const next = new Set(prev);
      if (next.has(g.char)) {
        next.delete(g.char);
      } else {
        next.add(g.char);
      }
      return next;
    });
    setLastClickedIdx(idx);
  };

  const selectedSummaries = useMemo(
    () => glyphs.filter((g) => selectedChars.has(g.char)),
    [glyphs, selectedChars]
  );

  const selectedMatchingVariants = useMemo(
    () => selectedSummaries.flatMap((g) => getMatchingVariants(g, glyphSourceFilter)),
    [selectedSummaries, glyphSourceFilter]
  );

  const selectedVariantIds = useMemo(
    () => selectedMatchingVariants.map((v) => v.id),
    [selectedMatchingVariants]
  );

  const selectedTabletVariantCount = useMemo(
    () => selectedMatchingVariants.filter((v) => v.source === "tablet").length,
    [selectedMatchingVariants]
  );

  const selectedAiVariantCount = useMemo(
    () => selectedMatchingVariants.filter((v) => v.source === "ai_generated").length,
    [selectedMatchingVariants]
  );

  const selectedCharsStr = useMemo(
    () => selectedSummaries.map((g) => g.char).join(""),
    [selectedSummaries]
  );

  const allVisibleSelected = glyphs.length > 0 && selectedSummaries.length === glyphs.length;

  const handleSelectAllToggle = () => {
    if (allVisibleSelected) {
      setSelectedChars(new Set());
    } else {
      setSelectedChars(new Set(glyphs.map((g) => g.char)));
    }
    setLastClickedIdx(null);
  };

  const handleInvertSelection = () => {
    setSelectedChars((prev) => {
      const next = new Set<string>();
      for (const g of glyphs) {
        if (!prev.has(g.char)) {
          next.add(g.char);
        }
      }
      return next;
    });
    setLastClickedIdx(null);
  };

  const handleSelectAiOnly = () => {
    setSelectedChars(new Set(glyphs.filter((g) => g.has_ai).map((g) => g.char)));
    setLastClickedIdx(null);
  };

  const handleConfirmBatchDelete = async () => {
    if (selectedVariantIds.length === 0) return;
    setIsDeletingBatch(true);
    try {
      const deletedCount = await batchDeleteGlyphs(selectedVariantIds);
      setConfirmDeleteOpen(false);
      setSelectedChars(new Set());
      setLastClickedIdx(null);
      setBatchNotice(`已批量删除 ${deletedCount} 枚字形变体`);
    } catch (err) {
      setConfirmDeleteOpen(false);
      useAppStore.setState({ errorMessage: (err as Error).message });
    } finally {
      setIsDeletingBatch(false);
    }
  };

  const totalVariants = glyphs.reduce((acc, g) => acc + g.variant_count, 0);
  const hasActiveFilters =
    glyphSourceFilter !== "all" || Boolean(glyphSearch) || Boolean(glyphDateFrom) || Boolean(glyphDateTo);

  const filterScopeText = useMemo(() => {
    const parts: string[] = [];
    if (glyphSourceFilter === "tablet") parts.push("仅平板真迹");
    if (glyphSourceFilter === "ai_generated") parts.push("仅 AI 补全");
    if (glyphDateFrom && glyphDateTo) {
      parts.push(glyphDateFrom === glyphDateTo ? glyphDateFrom : `${glyphDateFrom} ~ ${glyphDateTo}`);
    } else if (glyphDateFrom) {
      parts.push(`${glyphDateFrom} 起`);
    } else if (glyphDateTo) {
      parts.push(`截至 ${glyphDateTo}`);
    }
    return parts.join(" · ");
  }, [glyphSourceFilter, glyphDateFrom, glyphDateTo]);

  // Sync inspectChar with latest store state if a variant was deleted
  const activeInspect = inspectChar
    ? glyphs.find((g) => g.char === inspectChar.char) ?? null
    : null;

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-slate-50 p-5">
      {/* Header Row */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-bold text-slate-800">个人手写字库</h2>
            {aiStatus?.loaded && (
              <span className="inline-flex items-center gap-1 rounded-full bg-indigo-100 px-2.5 py-0.5 text-[11px] font-semibold text-indigo-700">
                <Cpu className="h-3 w-3" />
                GPU 模型常驻 ({aiStatus.vram_allocated_mb} MB)
                <button
                  type="button"
                  onClick={() => void handleUnloadGpu()}
                  className="ml-1 underline hover:text-indigo-900"
                >
                  释放显存
                </button>
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500">
            当前显示 <b>{glyphs.length}</b> 个不同字符，共 <b>{totalVariants}</b> 份笔迹变体（同一字符录入平板真迹后将自动覆盖 AI 补全版本）
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={toggleBatchMode}
            className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-semibold transition ${
              batchMode
                ? "border-blue-600 bg-blue-50 text-blue-700"
                : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
            }`}
          >
            <CheckSquare className="h-4 w-4" />
            {batchMode ? "退出批量" : "批量管理"}
          </button>

          <button
            type="button"
            onClick={() => openAiModal("")}
            className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700"
          >
            <Cpu className="h-4 w-4" />
            AI 推理补字
          </button>

          <button
            type="button"
            onClick={() => openCaptureModal("", "高频字采集表")}
            className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-1.5 text-sm font-semibold text-white hover:bg-blue-700"
          >
            <QrCode className="h-4 w-4" />
            生成采集表 / 平板导入
          </button>
        </div>
      </div>

      {/* Filter & Sort Toolbar */}
      <div className="mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm">
        {/* Source Filter */}
        <div className="flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-xs font-medium">
          {(
            [
              ["all", "全部"],
              ["tablet", "平板真迹"],
              ["ai_generated", "AI 补全"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => void setGlyphSourceFilter(key)}
              className={`rounded-md px-2.5 py-1 transition ${
                glyphSourceFilter === key
                  ? "bg-blue-600 text-white shadow-sm"
                  : "text-slate-600 hover:bg-white"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Import Date Filter */}
        <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-xs">
          <Calendar className="h-3.5 w-3.5 text-slate-500" />
          <span className="font-medium text-slate-600">导入日期:</span>
          <select
            value={datePresetValue}
            onChange={(e) => handleDatePresetChange(e.target.value)}
            aria-label="导入日期快捷筛选"
            className="rounded border border-slate-200 bg-white px-1.5 py-0.5 text-xs font-medium text-slate-700 focus:border-blue-500 focus:outline-none"
          >
            <option value="">全部导入日期</option>
            <option value="today">今天 ({todayYmd})</option>
            <option value="last3">近 3 天</option>
            <option value="last7">近 7 天</option>
            {glyphImportDates.length > 0 && (
              <optgroup label="按具体导入日期">
                {glyphImportDates.map((d) => (
                  <option key={d.date} value={`date:${d.date}`}>
                    {d.date} ({d.char_count}字 / {d.variant_count}枚)
                  </option>
                ))}
              </optgroup>
            )}
            {datePresetValue === "custom" && <option value="custom">自定义区间</option>}
          </select>

          <input
            type="date"
            value={glyphDateFrom}
            onChange={(e) => handleDateFromChange(e.target.value)}
            aria-label="开始导入日期"
            className="rounded border border-slate-200 bg-white px-1.5 py-0.5 text-xs text-slate-700 focus:border-blue-500 focus:outline-none"
          />
          <span className="text-slate-400">至</span>
          <input
            type="date"
            value={glyphDateTo}
            onChange={(e) => handleDateToChange(e.target.value)}
            aria-label="结束导入日期"
            className="rounded border border-slate-200 bg-white px-1.5 py-0.5 text-xs text-slate-700 focus:border-blue-500 focus:outline-none"
          />
          {(glyphDateFrom || glyphDateTo) && (
            <button
              type="button"
              title="清除日期筛选"
              onClick={() => void setGlyphDateRange("", "")}
              className="rounded p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* Sort Selector */}
        <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-xs">
          <span className="text-slate-500">排序:</span>
          <select
            value={glyphSort}
            onChange={(e) => void setGlyphSort(e.target.value as GlyphSortBy)}
            className="bg-transparent font-medium text-slate-700 focus:outline-none"
          >
            <option value="variant_count">按变体数</option>
            <option value="latest">按最新导入</option>
            <option value="char">按字符编码</option>
          </select>
        </div>

        {/* Search Input */}
        <div className="relative ml-auto min-w-[180px]">
          <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-slate-400" />
          <input
            type="text"
            value={glyphSearch}
            onChange={(e) => void setGlyphSearch(e.target.value)}
            placeholder="搜索已录入字符..."
            className="w-full rounded-lg border border-slate-200 bg-white py-1 pl-8 pr-7 text-xs focus:border-blue-500 focus:outline-none"
          />
          {glyphSearch && (
            <button
              type="button"
              onClick={() => void setGlyphSearch("")}
              className="absolute right-2 top-1.5 rounded p-0.5 text-slate-400 hover:text-slate-600"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>

        {hasActiveFilters && (
          <button
            type="button"
            onClick={() => void resetGlyphFilters()}
            className="flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
          >
            <RotateCcw className="h-3 w-3" />
            重置筛选
          </button>
        )}
      </div>

      {/* Batch Notice Banner */}
      {batchNotice && (
        <div className="mb-3 flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs text-emerald-800">
          <span>{batchNotice}</span>
          <button
            type="button"
            onClick={() => setBatchNotice(null)}
            className="rounded p-0.5 text-emerald-600 hover:bg-emerald-100"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* Batch Management Action Bar */}
      {batchMode && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-blue-200 bg-blue-50/90 px-3.5 py-2.5 text-xs shadow-sm">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleSelectAllToggle}
              disabled={glyphs.length === 0}
              className="rounded-md border border-blue-200 bg-white px-2.5 py-1 font-semibold text-blue-700 hover:bg-blue-100 disabled:opacity-40"
            >
              {allVisibleSelected ? "取消全选" : `全选当前 (${glyphs.length})`}
            </button>
            <button
              type="button"
              onClick={handleInvertSelection}
              disabled={glyphs.length === 0}
              className="rounded-md border border-slate-200 bg-white px-2.5 py-1 font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"
            >
              反选
            </button>
            <button
              type="button"
              onClick={handleSelectAiOnly}
              disabled={glyphs.length === 0}
              className="rounded-md border border-indigo-200 bg-white px-2.5 py-1 font-medium text-indigo-700 hover:bg-indigo-50 disabled:opacity-40"
            >
              仅选含 AI 字
            </button>
            {selectedChars.size > 0 && (
              <button
                type="button"
                onClick={() => {
                  setSelectedChars(new Set());
                  setLastClickedIdx(null);
                }}
                className="rounded-md px-2 py-1 text-slate-600 underline hover:text-slate-900"
              >
                清空选择
              </button>
            )}
            <span className="ml-1 text-slate-700">
              已选 <b>{selectedSummaries.length}</b> 个字符（命中 <b>{selectedVariantIds.length}</b> 枚变体）
              <span className="ml-2 hidden text-[11px] text-slate-500 sm:inline">
                提示：按住 Shift 点击可连续多选
              </span>
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={selectedSummaries.length === 0}
              onClick={() => openAiModal(selectedCharsStr, { replaceExistingAi: true })}
              className="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 font-semibold text-white hover:bg-indigo-700 disabled:opacity-40"
            >
              <Sparkles className="h-3.5 w-3.5" />
              批量 AI 重绘
            </button>
            <button
              type="button"
              disabled={selectedSummaries.length === 0}
              onClick={() => openCaptureModal(selectedCharsStr, "批量补采表")}
              className="flex items-center gap-1 rounded-lg border border-blue-300 bg-white px-3 py-1.5 font-semibold text-blue-700 hover:bg-blue-50 disabled:opacity-40"
            >
              <QrCode className="h-3.5 w-3.5" />
              批量补采表
            </button>
            <button
              type="button"
              disabled={selectedVariantIds.length === 0}
              onClick={() => setConfirmDeleteOpen(true)}
              className="flex items-center gap-1 rounded-lg bg-rose-600 px-3 py-1.5 font-semibold text-white hover:bg-rose-700 disabled:opacity-40"
            >
              <Trash2 className="h-3.5 w-3.5" />
              批量删除 ({selectedVariantIds.length})
            </button>
          </div>
        </div>
      )}

      {/* Glyph Grid / Empty State */}
      {glyphs.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-200 bg-white p-10 text-center">
          <div className="text-base font-semibold text-slate-700">当前筛选下暂无字符</div>
          <p className="mt-1 max-w-md text-xs text-slate-500">
            {hasActiveFilters
              ? "没有符合当前来源、导入日期或搜索关键词的字形，您可以重置筛选条件或调整导入日期范围。"
              : "点击右上角「生成采集表 / 平板导入」，导出带定位标的 A4 采集表 PDF 到安卓平板书写后回传，即可秒级自动切字入库；或使用「AI 推理补字」从已有风格自动生成缺字。"}
          </p>
          <div className="mt-4 flex items-center gap-2">
            {hasActiveFilters && (
              <button
                type="button"
                onClick={() => void resetGlyphFilters()}
                className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
              >
                重置筛选条件
              </button>
            )}
            <button
              type="button"
              onClick={() => openCaptureModal("", "实验报告高频字采集")}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
            >
              立即生成第一张采集表
            </button>
          </div>
        </div>
      ) : (
        <div className="grid flex-1 grid-cols-4 content-start gap-3 overflow-y-auto pr-1 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-10 xl:grid-cols-12">
          {glyphs.map((g, idx) => {
            const isSelected = batchMode && selectedChars.has(g.char);
            const shortDate = g.latest_import_date ? g.latest_import_date.slice(5) : "";
            return (
              <div
                key={g.char}
                role="button"
                tabIndex={0}
                onClick={(e) => handleCardClick(g, idx, e)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    handleCardClick(g, idx, e as unknown as React.MouseEvent);
                  }
                }}
                className={`group relative flex cursor-pointer flex-col items-center rounded-xl border p-2 text-left transition ${
                  isSelected
                    ? "border-blue-500 bg-blue-50/70 ring-2 ring-blue-200"
                    : "border-slate-200 bg-white hover:border-blue-400 hover:shadow-sm"
                }`}
              >
                {batchMode && (
                  <span
                    className={`absolute left-1.5 top-1.5 z-10 flex h-4 w-4 items-center justify-center rounded border transition ${
                      isSelected
                        ? "border-blue-600 bg-blue-600 text-white"
                        : "border-slate-300 bg-white/90 text-transparent group-hover:border-blue-400"
                    }`}
                  >
                    <Check className="h-3 w-3" />
                  </span>
                )}

                {!batchMode && !g.has_tablet && g.has_ai && (
                  <span className="absolute right-1.5 top-1.5 rounded bg-indigo-600 px-1 py-0.5 text-[10px] font-bold leading-none text-white">
                    AI
                  </span>
                )}

                {batchMode && (
                  <div className="absolute right-1.5 top-1.5 z-10 flex items-center gap-1">
                    {!g.has_tablet && g.has_ai && (
                      <span className="rounded bg-indigo-600 px-1 py-0.5 text-[10px] font-bold leading-none text-white">
                        AI
                      </span>
                    )}
                    <button
                      type="button"
                      title="查看变体详情"
                      onClick={(e) => {
                        e.stopPropagation();
                        setInspectChar(g);
                      }}
                      className="rounded border border-slate-200 bg-white/95 p-0.5 text-slate-500 shadow-sm hover:border-blue-300 hover:text-blue-600"
                    >
                      <Eye className="h-3 w-3" />
                    </button>
                  </div>
                )}

                <div className="checkerboard-bg flex h-20 w-20 items-center justify-center overflow-hidden rounded-lg border border-slate-100">
                  <img
                    src={g.latest_image_url}
                    alt={g.char}
                    className="h-full w-full object-contain"
                  />
                </div>
                <div className="mt-1.5 flex w-full items-center justify-between px-0.5 text-xs">
                  <span className="font-bold text-slate-800">{g.char}</span>
                  <div className="flex items-center gap-1">
                    {shortDate && (
                      <span
                        title={`最近导入：${g.latest_import_date}`}
                        className="text-[10px] text-slate-400"
                      >
                        {shortDate}
                      </span>
                    )}
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">
                      {g.variant_count}枚
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Batch Delete Confirmation Modal */}
      {confirmDeleteOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl">
            <div className="mb-3 flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-rose-100 text-rose-600">
                <AlertTriangle className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-base font-bold text-slate-800">确认批量删除字形</h3>
                <p className="mt-1 text-xs text-slate-600">
                  即将永久删除所选 <b>{selectedSummaries.length}</b> 个字符下命中的{" "}
                  <b>{selectedVariantIds.length}</b> 枚字形变体及对应图片文件（不可恢复）。
                </p>
              </div>
            </div>

            <div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
              <div className="flex items-center justify-between">
                <span>包含平板真迹</span>
                <span className="font-semibold text-emerald-700">{selectedTabletVariantCount} 枚</span>
              </div>
              <div className="flex items-center justify-between">
                <span>包含 AI 补全</span>
                <span className="font-semibold text-indigo-700">{selectedAiVariantCount} 枚</span>
              </div>
              {filterScopeText && (
                <div className="border-t border-slate-200 pt-2 text-[11px] text-slate-500">
                  当前筛选范围：{filterScopeText}（仅删除命中当前筛选条件的变体，其它日期或来源的变体不受影响）
                </div>
              )}
            </div>

            {selectedTabletVariantCount > 0 && (
              <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                注意：选中范围包含 {selectedTabletVariantCount} 枚平板真迹，删除后需要重新通过采集表录入。
              </div>
            )}

            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                disabled={isDeletingBatch}
                onClick={() => setConfirmDeleteOpen(false)}
                className="rounded-lg border border-slate-300 bg-white px-3.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
              >
                取消
              </button>
              <button
                type="button"
                disabled={isDeletingBatch}
                onClick={() => void handleConfirmBatchDelete()}
                className="flex items-center gap-1.5 rounded-lg bg-rose-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
              >
                {isDeletingBatch ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Trash2 className="h-3.5 w-3.5" />
                )}
                确认删除 ({selectedVariantIds.length} 枚)
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Variant inspection drawer/modal */}
      {activeInspect && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-5 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-lg font-bold text-blue-700">
                  {activeInspect.char}
                </span>
                <div>
                  <div className="font-semibold text-slate-800">
                    字符「{activeInspect.char}」的所有变体
                  </div>
                  <div className="text-xs text-slate-500">
                    平板真迹 {activeInspect.tablet_count} 枚 · AI 补全 {activeInspect.ai_count} 枚
                    {activeInspect.has_tablet && activeInspect.has_ai
                      ? "（已优先使用真迹）"
                      : ""}
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setInspectChar(null)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-100"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="grid max-h-80 grid-cols-3 gap-3 overflow-y-auto p-1">
              {activeInspect.variants.map((v, idx) => (
                <div
                  key={v.id}
                  className="relative flex flex-col items-center rounded-xl border border-slate-200 p-2"
                >
                  <span
                    className={`absolute left-2 top-2 rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                      v.source === "ai_generated"
                        ? "bg-indigo-100 text-indigo-700"
                        : "bg-emerald-100 text-emerald-700"
                    }`}
                  >
                    {v.source === "ai_generated" ? "AI 补全" : "真迹"}
                  </span>
                  <div className="checkerboard-bg h-24 w-24 overflow-hidden rounded-lg">
                    <img src={v.image_url} alt={v.char} className="h-full w-full object-contain" />
                  </div>
                  <div className="mt-1.5 flex w-full items-center justify-between text-[11px] text-slate-500">
                    <span>#{idx + 1}</span>
                    <button
                      type="button"
                      onClick={() => void deleteGlyphVariant(v.id)}
                      className="flex items-center gap-0.5 rounded px-1.5 py-0.5 text-rose-600 hover:bg-rose-50"
                    >
                      <Trash2 className="h-3 w-3" />
                      删除
                    </button>
                  </div>
                  <div className="mt-0.5 w-full truncate text-center text-[10px] text-slate-400">
                    {formatIsoDateTime(v.created_at)}
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  const c = activeInspect.char;
                  const shouldReplaceAi = activeInspect.has_ai && !activeInspect.has_tablet;
                  setInspectChar(null);
                  openAiModal(c, { replaceExistingAi: shouldReplaceAi });
                }}
                className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-100"
              >
                AI 重绘新变体
              </button>
              <button
                type="button"
                onClick={() => {
                  const c = activeInspect.char;
                  setInspectChar(null);
                  openCaptureModal(c, `单字补采_${c}`);
                }}
                className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-100"
              >
                为该字生成平板补采表
              </button>
              <button
                type="button"
                onClick={() => setInspectChar(null)}
                className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-semibold text-white"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
