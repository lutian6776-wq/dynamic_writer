import React, { useState } from "react";
import { Cpu, Grid, Link2, Sparkles, Strikethrough, Wand2 } from "lucide-react";
import { api } from "../api/client";
import { useAppStore } from "../store/useAppStore";
import type { RegionType, TextAlign } from "../types";

export const RegionInspector: React.FC = () => {
  const {
    activeProject,
    selectedRegionId,
    updateRegion,
    previewStats,
    openCaptureModal,
    openAiModal,
  } = useAppStore();

  const [detectMsg, setDetectMsg] = useState<string | null>(null);
  const [detectBusy, setDetectBusy] = useState(false);

  const region = activeProject?.regions.find((r) => r.id === selectedRegionId) ?? null;

  const insertMistakeSnippet = () => {
    if (!region) return;
    const prefix = region.text && !region.text.endsWith("\n") ? "" : "";
    updateRegion(region.id, { text: `${region.text}${prefix}[错字->正字]` });
  };

  const handleDetectLines = async () => {
    if (!activeProject || !region) return;
    setDetectBusy(true);
    setDetectMsg(null);
    try {
      const res = await api.detectLines(activeProject.id, region.page_index, {
        x: region.x,
        y: region.y,
        width: region.width,
        height: region.height,
      });
      if (res.line_ys.length >= 2) {
        updateRegion(region.id, {
          line_spacing: res.line_spacing,
          baseline_offset: res.baseline_offset,
        });
        setDetectMsg(`已探测 ${res.line_ys.length} 条横线（行距 ${res.line_spacing} pt）`);
      } else {
        setDetectMsg("框内未检测到明显横线，可手动微调行距滑块");
      }
    } catch (e) {
      setDetectMsg((e as Error).message);
    } finally {
      setDetectBusy(false);
    }
  };

  const handleDetectTable = async () => {
    if (!activeProject || !region) return;
    setDetectBusy(true);
    setDetectMsg(null);
    try {
      const res = await api.detectTable(activeProject.id, region.page_index, {
        x: region.x,
        y: region.y,
        width: region.width,
        height: region.height,
      });
      updateRegion(region.id, {
        table_rows: res.rows,
        table_cols: res.cols,
      });
      setDetectMsg(`识别到 ${res.rows.length - 1} 行 × ${res.cols.length - 1} 列`);
    } catch (e) {
      setDetectMsg((e as Error).message);
    } finally {
      setDetectBusy(false);
    }
  };

  const adjustGrid = (axis: "rows" | "cols", delta: number) => {
    if (!region) return;
    const cur = axis === "rows" ? region.table_rows : region.table_cols;
    const count = Math.max(1, Math.min(20, cur.length - 1 + delta));
    const arr = Array.from({ length: count + 1 }, (_, i) => Number((i / count).toFixed(4)));
    updateRegion(region.id, axis === "rows" ? { table_rows: arr } : { table_cols: arr });
  };

  const missingCharsStr = previewStats?.missing_counts.map((m) => m.char).join("") ?? "";
  const totalChars = previewStats?.total_chars ?? 0;
  const missingTotal = previewStats?.missing_counts.reduce((acc, m) => acc + m.count, 0) ?? 0;
  const coveragePct = totalChars > 0 ? Math.round(((totalChars - missingTotal) / totalChars) * 100) : 100;

  return (
    <div className="flex flex-col gap-3 p-3 text-sm">
      {/* Document missing chars banner */}
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-2.5">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-700">当前文档字库覆盖率</span>
          <span className="text-xs font-bold text-blue-600">{coveragePct}%</span>
        </div>
        {previewStats && previewStats.missing_unique > 0 ? (
          <div className="mt-1.5 space-y-1.5">
            <div className="text-xs text-amber-700">
              尚有 <b>{previewStats.missing_unique}</b> 个字未录入：
              <span className="ml-1 font-mono text-slate-800">
                {missingCharsStr.slice(0, 18)}
                {missingCharsStr.length > 18 ? "..." : ""}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              <button
                type="button"
                onClick={() => openAiModal(missingCharsStr)}
                className="flex items-center justify-center gap-1 rounded-md bg-indigo-600 px-2 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700"
              >
                <Cpu className="h-3.5 w-3.5" />
                本地 AI 补全 ({previewStats.missing_unique}字)
              </button>
              <button
                type="button"
                onClick={() =>
                  openCaptureModal(missingCharsStr, `${activeProject?.name ?? "报告"}_缺字补采`)
                }
                className="flex items-center justify-center gap-1 rounded-md bg-amber-500 px-2 py-1.5 text-xs font-semibold text-white hover:bg-amber-600"
              >
                <Sparkles className="h-3.5 w-3.5" />
                平板补写缺字表
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-1 text-xs text-emerald-700">所有已排字符均已录入个人字库！</div>
        )}

        {previewStats?.ai_generated_chars && previewStats.ai_generated_chars.length > 0 && (
          <div className="mt-2 flex items-center justify-between gap-2 rounded-md border border-indigo-200 bg-indigo-50 px-2 py-1.5 text-[11px] text-indigo-800">
            <span>
              含 <b>{previewStats.ai_generated_chars.length}</b> 个 AI 补全字（画布紫色虚线标注，打印无痕）
            </span>
            <button
              type="button"
              onClick={() =>
                openCaptureModal(
                  previewStats.ai_generated_chars!.join(""),
                  `${activeProject?.name ?? "报告"}_AI字换真迹`
                )
              }
              className="shrink-0 rounded bg-indigo-600 px-2 py-0.5 font-semibold text-white hover:bg-indigo-700"
            >
              导出补采表
            </button>
          </div>
        )}
      </div>

      {previewStats?.warnings && previewStats.warnings.length > 0 && (
        <div className="rounded-md border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700">
          {previewStats.warnings.map((w, i) => (
            <div key={i}>{w}</div>
          ))}
        </div>
      )}

      {!region ? (
        <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-xs text-slate-500">
          请在画布上方工具栏选择「多行横线」「单行填空」或「表格区」，在模板上框选区域即可开始输入文字。
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="mb-1 block text-xs text-slate-500">区域名称</label>
              <input
                type="text"
                value={region.name}
                onChange={(e) => updateRegion(region.id, { name: e.target.value })}
                className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-500">区域类型</label>
              <select
                value={region.type}
                onChange={(e) => updateRegion(region.id, { type: e.target.value as RegionType })}
                className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
              >
                <option value="multi_line">多行横线正文</option>
                <option value="single_line">单行填空</option>
                <option value="table">表格批量填充</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="mb-1 block text-xs text-slate-500">
                字号 ({region.font_size.toFixed(1)} pt)
              </label>
              <input
                type="range"
                min={8}
                max={38}
                step={0.5}
                value={region.font_size}
                onChange={(e) => updateRegion(region.id, { font_size: Number(e.target.value) })}
                className="w-full"
              />
            </div>
            {region.type !== "multi_line" && (
              <div>
                <label className="mb-1 block text-xs text-slate-500">对齐方式</label>
                <select
                  value={region.align}
                  onChange={(e) => updateRegion(region.id, { align: e.target.value as TextAlign })}
                  className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
                >
                  <option value="left">左对齐</option>
                  <option value="center">居中</option>
                  <option value="right">右对齐</option>
                </select>
              </div>
            )}
          </div>

          {region.type === "multi_line" && (
            <div className="space-y-2 rounded-lg border border-blue-100 bg-blue-50/60 p-2.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-blue-900">横线与续写设置</span>
                <button
                  type="button"
                  disabled={detectBusy}
                  onClick={handleDetectLines}
                  className="flex items-center gap-1 rounded bg-blue-600 px-2 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  <Wand2 className="h-3 w-3" />
                  自动探测横线行距
                </button>
              </div>
              {detectMsg && <div className="text-xs text-blue-700">{detectMsg}</div>}

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs text-slate-600">
                    行距 ({region.line_spacing.toFixed(1)} pt)
                  </label>
                  <input
                    type="range"
                    min={10}
                    max={60}
                    step={0.5}
                    value={region.line_spacing}
                    onChange={(e) => updateRegion(region.id, { line_spacing: Number(e.target.value) })}
                    className="w-full"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-600">
                    首行基线 ({region.baseline_offset.toFixed(1)} pt)
                  </label>
                  <input
                    type="range"
                    min={6}
                    max={60}
                    step={0.5}
                    value={region.baseline_offset}
                    onChange={(e) =>
                      updateRegion(region.id, { baseline_offset: Number(e.target.value) })
                    }
                    className="w-full"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs text-slate-600">
                  首行左侧缩进 / 避让印刷标题 ({region.first_line_indent.toFixed(0)} pt)
                </label>
                <input
                  type="range"
                  min={0}
                  max={220}
                  step={2}
                  value={region.first_line_indent}
                  onChange={(e) =>
                    updateRegion(region.id, { first_line_indent: Number(e.target.value) })
                  }
                  className="w-full"
                />
              </div>

              <div>
                <label className="mb-1 flex items-center gap-1 text-xs text-slate-600">
                  <Link2 className="h-3 w-3" />
                  写满后自动续写至（支持跨页串联）
                </label>
                <select
                  value={region.next_region_id ?? ""}
                  onChange={(e) =>
                    updateRegion(region.id, { next_region_id: e.target.value || null })
                  }
                  className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs"
                >
                  <option value="">不串联（仅当前区域）</option>
                  {activeProject?.regions
                    .filter((r) => r.id !== region.id && r.type !== "table")
                    .map((r) => (
                      <option key={r.id} value={r.id}>
                        第 {r.page_index + 1} 页 · {r.name}
                      </option>
                    ))}
                </select>
              </div>
            </div>
          )}

          {region.type === "table" && (
            <div className="space-y-2 rounded-lg border border-purple-100 bg-purple-50/60 p-2.5">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1 text-xs font-semibold text-purple-900">
                  <Grid className="h-3.5 w-3.5" />
                  表格行列 ({region.table_rows.length - 1}行 × {region.table_cols.length - 1}列)
                </span>
                <button
                  type="button"
                  disabled={detectBusy}
                  onClick={handleDetectTable}
                  className="flex items-center gap-1 rounded bg-purple-600 px-2 py-1 text-xs font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                >
                  <Wand2 className="h-3 w-3" />
                  自动识别表格
                </button>
              </div>
              {detectMsg && <div className="text-xs text-purple-700">{detectMsg}</div>}
              <div className="flex flex-wrap gap-1.5 text-xs">
                <button
                  type="button"
                  onClick={() => adjustGrid("rows", 1)}
                  className="rounded border border-purple-200 bg-white px-2 py-0.5 hover:bg-purple-100"
                >
                  +行
                </button>
                <button
                  type="button"
                  onClick={() => adjustGrid("rows", -1)}
                  className="rounded border border-purple-200 bg-white px-2 py-0.5 hover:bg-purple-100"
                >
                  -行
                </button>
                <button
                  type="button"
                  onClick={() => adjustGrid("cols", 1)}
                  className="rounded border border-purple-200 bg-white px-2 py-0.5 hover:bg-purple-100"
                >
                  +列
                </button>
                <button
                  type="button"
                  onClick={() => adjustGrid("cols", -1)}
                  className="rounded border border-purple-200 bg-white px-2 py-0.5 hover:bg-purple-100"
                >
                  -列
                </button>
              </div>
              <div className="text-[11px] text-purple-700">
                提示：可在画布上直接拖动紫色的内部行列线对齐表格边框。
              </div>
            </div>
          )}

          <div>
            <div className="mb-1 flex items-center justify-between">
              <label className="text-xs font-medium text-slate-600">
                {region.type === "table"
                  ? "表格数据（支持直接从 Excel 粘贴，Tab 分列 / 换行分行）"
                  : "手写文本内容"}
              </label>
              <button
                type="button"
                onClick={insertMistakeSnippet}
                className="flex items-center gap-1 rounded border border-slate-200 px-1.5 py-0.5 text-[11px] text-slate-600 hover:bg-slate-100"
                title="插入错别字划掉重写标记"
              >
                <Strikethrough className="h-3 w-3" />
                [错-&gt;正]
              </button>
            </div>
            <textarea
              rows={8}
              value={region.text}
              onChange={(e) => updateRegion(region.id, { text: e.target.value })}
              placeholder={
                region.type === "table"
                  ? "1\t2.45\t0.12\n2\t4.91\t0.24"
                  : "输入要模拟手写填入的内容...\n需要模拟涂改错别字可写：[实脸->实验]"
              }
              className="w-full rounded-lg border border-slate-300 p-2 font-mono text-xs leading-relaxed focus:border-blue-500 focus:outline-none"
            />
          </div>
        </>
      )}
    </div>
  );
};
