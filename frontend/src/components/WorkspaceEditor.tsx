import React, { useRef, useState } from "react";
import {
  AlignLeft,
  Eye,
  EyeOff,
  FilePlus2,
  Grid,
  MousePointer2,
  RefreshCw,
  Trash2,
  Type,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useAppStore, type ToolMode } from "../store/useAppStore";
import { TemplateCanvas } from "./TemplateCanvas";
import { RegionInspector } from "./RegionInspector";
import { StylePanel } from "./StylePanel";

export const WorkspaceEditor: React.FC = () => {
  const {
    projects,
    activeProject,
    activePageIndex,
    selectedRegionId,
    toolMode,
    showHelpers,
    isRenderingPreview,
    uploadProject,
    selectProject,
    deleteProject,
    setActivePageIndex,
    setSelectedRegionId,
    deleteRegion,
    setToolMode,
    setShowHelpers,
    refreshPreview,
  } = useAppStore();

  const [rightTab, setRightTab] = useState<"region" | "style">("region");
  const [zoom, setZoom] = useState(1.0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleUploadTemplate = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    await uploadProject(f);
    e.target.value = "";
  };

  const currentRegions =
    activeProject?.regions.filter((r) => r.page_index === activePageIndex) ?? [];

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden">
      {/* Left Sidebar: Projects, Pages & Regions */}
      <aside className="flex w-60 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-200 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-600">模板项目</span>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="flex items-center gap-1 rounded bg-blue-600 px-2 py-1 text-xs font-medium text-white hover:bg-blue-700"
            >
              <FilePlus2 className="h-3.5 w-3.5" />
              上传模板
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf,image/*"
              onChange={handleUploadTemplate}
              className="hidden"
            />
          </div>
          <div className="max-h-36 space-y-1 overflow-y-auto">
            {projects.length === 0 ? (
              <div className="py-3 text-center text-xs text-slate-400">暂无模板，请上传 PDF/图片</div>
            ) : (
              projects.map((p) => (
                <div
                  key={p.id}
                  onClick={() => void selectProject(p.id)}
                  className={`flex cursor-pointer items-center justify-between rounded px-2 py-1.5 text-xs ${
                    activeProject?.id === p.id
                      ? "bg-blue-50 font-semibold text-blue-700"
                      : "text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  <span className="truncate">{p.name}</span>
                  <button
                    type="button"
                    onClick={(ev) => {
                      ev.stopPropagation();
                      void deleteProject(p.id);
                    }}
                    className="rounded p-0.5 text-slate-400 hover:text-rose-600"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Page switcher */}
        {activeProject && (
          <div className="border-b border-slate-200 p-3">
            <div className="mb-1.5 text-xs font-semibold text-slate-600">
              页面 ({activeProject.page_count} 页)
            </div>
            <div className="flex flex-wrap gap-1.5">
              {activeProject.pages_meta.map((pm) => (
                <button
                  key={pm.page_index}
                  type="button"
                  onClick={() => setActivePageIndex(pm.page_index)}
                  className={`rounded border px-2.5 py-1 text-xs font-medium ${
                    activePageIndex === pm.page_index
                      ? "border-blue-600 bg-blue-600 text-white"
                      : "border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100"
                  }`}
                >
                  第 {pm.page_index + 1} 页
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Regions on current page */}
        <div className="flex-1 overflow-y-auto p-3">
          <div className="mb-1.5 text-xs font-semibold text-slate-600">
            本页填写区域 ({currentRegions.length})
          </div>
          <div className="space-y-1">
            {currentRegions.map((r) => (
              <div
                key={r.id}
                onClick={() => setSelectedRegionId(r.id)}
                className={`flex cursor-pointer items-center justify-between rounded px-2 py-1.5 text-xs ${
                  selectedRegionId === r.id
                    ? "bg-blue-50 font-semibold text-blue-700"
                    : "text-slate-700 hover:bg-slate-50"
                }`}
              >
                <span className="truncate">{r.name}</span>
                <button
                  type="button"
                  onClick={(ev) => {
                    ev.stopPropagation();
                    deleteRegion(r.id);
                  }}
                  className="rounded p-0.5 text-slate-400 hover:text-rose-600"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        </div>
      </aside>

      {/* Center Canvas Area */}
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between border-b border-slate-200 bg-white px-3 py-1.5">
          <div className="flex items-center gap-1">
            {(
              [
                ["select", "选择 / 拖动", MousePointer2],
                ["draw_multi_line", "框选多行横线", AlignLeft],
                ["draw_single_line", "框选单行填空", Type],
                ["draw_table", "框选表格区", Grid],
              ] as [ToolMode, string, React.ElementType][]
            ).map(([mode, label, Icon]) => (
              <button
                key={mode}
                type="button"
                onClick={() => setToolMode(mode)}
                className={`flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium ${
                  toolMode === mode
                    ? "bg-blue-600 text-white"
                    : "text-slate-700 hover:bg-slate-100"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-1.5 text-xs">
            <button
              type="button"
              onClick={() => setShowHelpers(!showHelpers)}
              className="flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-slate-700 hover:bg-slate-50"
            >
              {showHelpers ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
              {showHelpers ? "隐藏辅助框" : "显示辅助框"}
            </button>
            <button
              type="button"
              onClick={() => setZoom(Math.max(0.25, Number((zoom - 0.15).toFixed(2))))}
              className="rounded border border-slate-200 p-1 hover:bg-slate-50"
            >
              <ZoomOut className="h-3.5 w-3.5" />
            </button>
            <span className="w-11 text-center font-mono">{Math.round(zoom * 100)}%</span>
            <button
              type="button"
              onClick={() => setZoom(Math.min(3.5, Number((zoom + 0.15).toFixed(2))))}
              className="rounded border border-slate-200 p-1 hover:bg-slate-50"
            >
              <ZoomIn className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() => void refreshPreview()}
              className="flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-slate-700 hover:bg-slate-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${isRenderingPreview ? "animate-spin" : ""}`} />
              刷新预览
            </button>
          </div>
        </div>

        {activeProject ? (
          <TemplateCanvas zoom={zoom} setZoom={setZoom} />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 bg-slate-100 text-slate-500">
            <div className="text-base font-medium text-slate-700">
              先上传一份实验报告或课堂记录模板（PDF / 图片）
            </div>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
            >
              <FilePlus2 className="h-4 w-4" />
              上传模板文件
            </button>
          </div>
        )}
      </main>

      {/* Right Inspector */}
      <aside className="flex w-80 flex-col border-l border-slate-200 bg-white">
        <div className="grid grid-cols-2 border-b border-slate-200 text-xs font-semibold">
          <button
            type="button"
            onClick={() => setRightTab("region")}
            className={`py-2.5 ${
              rightTab === "region"
                ? "border-b-2 border-blue-600 text-blue-600"
                : "text-slate-500 hover:text-slate-800"
            }`}
          >
            区域与文本
          </button>
          <button
            type="button"
            onClick={() => setRightTab("style")}
            className={`py-2.5 ${
              rightTab === "style"
                ? "border-b-2 border-blue-600 text-blue-600"
                : "text-slate-500 hover:text-slate-800"
            }`}
          >
            拟真风格调节
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {rightTab === "region" ? <RegionInspector /> : <StylePanel />}
        </div>
      </aside>
    </div>
  );
};
