import React, { useEffect } from "react";
import { BookOpen, FileText, PenTool, Plus, Printer, QrCode, X } from "lucide-react";
import { useAppStore } from "./store/useAppStore";
import { WorkspaceEditor } from "./components/WorkspaceEditor";
import { GlyphLibraryView } from "./components/GlyphLibraryView";
import { SheetCaptureModal } from "./components/SheetCaptureModal";
import { AiSynthesizeModal } from "./components/AiSynthesizeModal";
import { ExportDialog } from "./components/ExportDialog";

export function App() {
  const {
    initLoad,
    profiles,
    activeProfileId,
    setActiveProfileId,
    createProfile,
    activeTab,
    setActiveTab,
    activeProject,
    openCaptureModal,
    setExportModalOpen,
    errorMessage,
    clearError,
  } = useAppStore();

  useEffect(() => {
    void initLoad();
  }, [initLoad]);

  const handleNewProfile = async () => {
    const name = window.prompt("请输入新的笔迹档案名称（例如：蓝黑钢笔、赶工速写）");
    if (name && name.trim()) {
      await createProfile(name.trim());
    }
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-100">
      {/* Top Navbar */}
      <header className="flex h-13 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4 py-2 shadow-sm">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 text-white">
              <PenTool className="h-4 w-4" />
            </div>
            <div>
              <div className="text-sm font-bold leading-tight text-slate-900">墨迹 · 个人手写模板引擎</div>
              <div className="text-[11px] text-slate-500">EMR 平板真迹采集 · 同字异形 · 套打校准</div>
            </div>
          </div>

          <div className="ml-2 flex rounded-lg bg-slate-100 p-0.5 text-xs font-semibold">
            <button
              type="button"
              onClick={() => setActiveTab("workspace")}
              className={`flex items-center gap-1 rounded-md px-3 py-1.5 ${
                activeTab === "workspace" ? "bg-white text-blue-600 shadow-sm" : "text-slate-600"
              }`}
            >
              <FileText className="h-3.5 w-3.5" />
              模板填框工作台
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("library")}
              className={`flex items-center gap-1 rounded-md px-3 py-1.5 ${
                activeTab === "library" ? "bg-white text-blue-600 shadow-sm" : "text-slate-600"
              }`}
            >
              <BookOpen className="h-3.5 w-3.5" />
              个人字库管理
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-xs">
            <span className="text-slate-500">笔迹档案:</span>
            <select
              value={activeProfileId}
              onChange={(e) => void setActiveProfileId(e.target.value)}
              className="bg-transparent font-semibold text-slate-800 focus:outline-none"
            >
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => void handleNewProfile()}
              title="新建笔迹档案"
              className="rounded p-0.5 text-slate-500 hover:bg-slate-200"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>

          <button
            type="button"
            onClick={() => openCaptureModal("", "高频字采集表")}
            className="flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-100"
          >
            <QrCode className="h-3.5 w-3.5" />
            平板扫码采集
          </button>

          <button
            type="button"
            disabled={!activeProject}
            onClick={() => setExportModalOpen(true)}
            className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-40"
          >
            <Printer className="h-3.5 w-3.5" />
            导出打印 PDF
          </button>
        </div>
      </header>

      {errorMessage && (
        <div className="flex items-center justify-between bg-rose-600 px-4 py-1.5 text-xs text-white">
          <span>错误：{errorMessage}</span>
          <button type="button" onClick={clearError}>
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {activeTab === "workspace" ? <WorkspaceEditor /> : <GlyphLibraryView />}

      <SheetCaptureModal />
      <AiSynthesizeModal />
      <ExportDialog />
    </div>
  );
}

export default App;
