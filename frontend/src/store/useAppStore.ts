import { create } from "zustand";
import { api } from "../api/client";
import type {
  AiStatus,
  CharPreset,
  GlyphImportDateStat,
  GlyphSortBy,
  GlyphSummary,
  HandwritingStyle,
  PreviewStats,
  Profile,
  Project,
  RegionConfig,
} from "../types";

export type ToolMode = "select" | "draw_multi_line" | "draw_single_line" | "draw_table";
export type ActiveTab = "workspace" | "library";

interface AppState {
  profiles: Profile[];
  activeProfileId: string;
  projects: Project[];
  activeProject: Project | null;
  activePageIndex: number;
  selectedRegionId: string | null;
  toolMode: ToolMode;
  activeTab: ActiveTab;
  showHelpers: boolean;

  glyphs: GlyphSummary[];
  glyphSearch: string;
  glyphSourceFilter: "all" | "tablet" | "ai_generated";
  glyphDateFrom: string;
  glyphDateTo: string;
  glyphSort: GlyphSortBy;
  glyphImportDates: GlyphImportDateStat[];
  presets: CharPreset[];
  aiStatus: AiStatus | null;

  previewImageUrl: string | null;
  previewStats: PreviewStats | null;
  isRenderingPreview: boolean;
  errorMessage: string | null;

  captureModalOpen: boolean;
  captureInitialChars: string;
  captureInitialTitle: string;
  aiModalOpen: boolean;
  aiInitialChars: string;
  aiReplaceExisting: boolean;
  exportModalOpen: boolean;

  initLoad: () => Promise<void>;
  setActiveTab: (tab: ActiveTab) => void;
  setToolMode: (mode: ToolMode) => void;
  setShowHelpers: (v: boolean) => void;
  setActiveProfileId: (id: string) => Promise<void>;
  createProfile: (name: string) => Promise<void>;
  setGlyphSearch: (search: string) => Promise<void>;
  setGlyphSourceFilter: (source: "all" | "tablet" | "ai_generated") => Promise<void>;
  setGlyphDateRange: (dateFrom: string, dateTo: string) => Promise<void>;
  setGlyphSort: (sort: GlyphSortBy) => Promise<void>;
  resetGlyphFilters: () => Promise<void>;
  refreshGlyphs: (search?: string) => Promise<void>;
  deleteGlyphVariant: (glyphId: string) => Promise<void>;
  batchDeleteGlyphs: (glyphIds: string[]) => Promise<number>;
  refreshAiStatus: () => Promise<void>;

  uploadProject: (file: File) => Promise<void>;
  selectProject: (id: string) => Promise<void>;
  deleteProject: (id: string) => Promise<void>;
  setActivePageIndex: (idx: number) => void;
  setSelectedRegionId: (id: string | null) => void;

  addRegion: (region: RegionConfig) => void;
  updateRegion: (id: string, patch: Partial<RegionConfig>) => void;
  deleteRegion: (id: string) => void;
  updateStyle: (patch: Partial<HandwritingStyle>) => void;

  refreshPreview: () => Promise<void>;
  openCaptureModal: (chars?: string, title?: string) => void;
  closeCaptureModal: () => void;
  openAiModal: (chars?: string, opts?: { replaceExistingAi?: boolean }) => void;
  closeAiModal: () => void;
  setExportModalOpen: (open: boolean) => void;
  clearError: () => void;
}

let saveTimer: number | undefined;
let previewTimer: number | undefined;
let previewSeq = 0;

export const useAppStore = create<AppState>((set, get) => {
  const schedulePersistAndPreview = () => {
    const proj = get().activeProject;
    if (!proj) return;

    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(async () => {
      const latest = get().activeProject;
      if (!latest || latest.id !== proj.id) return;
      try {
        await api.updateProject(latest.id, {
          name: latest.name,
          profile_id: latest.profile_id,
          regions: latest.regions,
          style: latest.style,
        });
      } catch (e) {
        set({ errorMessage: (e as Error).message });
      }
    }, 350);

    window.clearTimeout(previewTimer);
    previewTimer = window.setTimeout(() => {
      void get().refreshPreview();
    }, 220);
  };

  return {
    profiles: [],
    activeProfileId: "default",
    projects: [],
    activeProject: null,
    activePageIndex: 0,
    selectedRegionId: null,
    toolMode: "select",
    activeTab: "workspace",
    showHelpers: true,

    glyphs: [],
    glyphSearch: "",
    glyphSourceFilter: "all",
    glyphDateFrom: "",
    glyphDateTo: "",
    glyphSort: "variant_count",
    glyphImportDates: [],
    presets: [],
    aiStatus: null,

    previewImageUrl: null,
    previewStats: null,
    isRenderingPreview: false,
    errorMessage: null,

    captureModalOpen: false,
    captureInitialChars: "",
    captureInitialTitle: "",
    aiModalOpen: false,
    aiInitialChars: "",
    aiReplaceExisting: false,
    exportModalOpen: false,

    initLoad: async () => {
      try {
        const [profiles, presets, projects] = await Promise.all([
          api.listProfiles(),
          api.listPresets(),
          api.listProjects(),
        ]);
        const activeProfileId = profiles[0]?.id ?? "default";
        const [glyphs, glyphImportDates] = await Promise.all([
          api.listGlyphs(activeProfileId, "", "all", { sort: "variant_count" }),
          api.listGlyphImportDates(activeProfileId, "all"),
        ]);
        const activeProject = projects[0] ?? null;
        set({
          profiles,
          activeProfileId,
          presets,
          projects,
          activeProject,
          activePageIndex: 0,
          selectedRegionId: activeProject?.regions[0]?.id ?? null,
          glyphs,
          glyphImportDates,
        });
        void get().refreshAiStatus();
        if (activeProject) {
          void get().refreshPreview();
        }
      } catch (e) {
        set({ errorMessage: (e as Error).message });
      }
    },

    setActiveTab: (tab) => set({ activeTab: tab }),
    setToolMode: (mode) => set({ toolMode: mode }),
    setShowHelpers: (v) => set({ showHelpers: v }),

    setActiveProfileId: async (id) => {
      set({ activeProfileId: id, glyphDateFrom: "", glyphDateTo: "" });
      const proj = get().activeProject;
      if (proj && proj.profile_id !== id) {
        const updated = { ...proj, profile_id: id };
        set({ activeProject: updated });
        await api.updateProject(proj.id, { profile_id: id });
      }
      await get().refreshGlyphs();
      void get().refreshPreview();
    },

    createProfile: async (name) => {
      const p = await api.createProfile(name);
      set((s) => ({ profiles: [...s.profiles, p] }));
      await get().setActiveProfileId(p.id);
    },

    setGlyphSearch: async (search) => {
      set({ glyphSearch: search });
      await get().refreshGlyphs(search);
    },

    setGlyphSourceFilter: async (source) => {
      set({ glyphSourceFilter: source });
      await get().refreshGlyphs();
    },

    setGlyphDateRange: async (dateFrom, dateTo) => {
      set({ glyphDateFrom: dateFrom, glyphDateTo: dateTo });
      await get().refreshGlyphs();
    },

    setGlyphSort: async (sort) => {
      set({ glyphSort: sort });
      await get().refreshGlyphs();
    },

    resetGlyphFilters: async () => {
      set({
        glyphSearch: "",
        glyphSourceFilter: "all",
        glyphDateFrom: "",
        glyphDateTo: "",
      });
      await get().refreshGlyphs("");
    },

    refreshGlyphs: async (searchOverride) => {
      const search = searchOverride !== undefined ? searchOverride : get().glyphSearch;
      if (searchOverride !== undefined && searchOverride !== get().glyphSearch) {
        set({ glyphSearch: searchOverride });
      }
      const { activeProfileId, glyphSourceFilter, glyphDateFrom, glyphDateTo, glyphSort } = get();
      const [glyphs, glyphImportDates] = await Promise.all([
        api.listGlyphs(activeProfileId, search, glyphSourceFilter, {
          dateFrom: glyphDateFrom,
          dateTo: glyphDateTo,
          sort: glyphSort,
        }),
        api.listGlyphImportDates(activeProfileId, glyphSourceFilter),
      ]);
      set({ glyphs, glyphImportDates });
    },

    deleteGlyphVariant: async (glyphId) => {
      await api.deleteGlyph(glyphId);
      await get().refreshGlyphs();
      void get().refreshPreview();
    },

    batchDeleteGlyphs: async (glyphIds) => {
      const res = await api.batchDeleteGlyphs({
        profile_id: get().activeProfileId,
        glyph_ids: glyphIds,
      });
      await get().refreshGlyphs();
      void get().refreshPreview();
      return res.deleted;
    },

    refreshAiStatus: async () => {
      try {
        const aiStatus = await api.getAiStatus();
        set({ aiStatus });
      } catch {
        // Ignore if AI endpoint unavailable
      }
    },

    uploadProject: async (file) => {
      const proj = await api.uploadProject(file, get().activeProfileId);
      const projects = await api.listProjects();
      set({
        projects,
        activeProject: proj,
        activePageIndex: 0,
        selectedRegionId: null,
        previewImageUrl: null,
        previewStats: null,
      });
      void get().refreshPreview();
    },

    selectProject: async (id) => {
      const proj = await api.getProject(id);
      set({
        activeProject: proj,
        activeProfileId: proj.profile_id,
        glyphDateFrom: "",
        glyphDateTo: "",
        activePageIndex: 0,
        selectedRegionId: proj.regions[0]?.id ?? null,
      });
      await get().refreshGlyphs();
      void get().refreshPreview();
    },

    deleteProject: async (id) => {
      await api.deleteProject(id);
      const projects = await api.listProjects();
      const next = projects[0] ?? null;
      set({
        projects,
        activeProject: next,
        activePageIndex: 0,
        selectedRegionId: next?.regions[0]?.id ?? null,
        previewImageUrl: null,
      });
      if (next) void get().refreshPreview();
    },

    setActivePageIndex: (idx) => {
      set({ activePageIndex: idx, selectedRegionId: null });
      void get().refreshPreview();
    },

    setSelectedRegionId: (id) => set({ selectedRegionId: id }),

    addRegion: (region) => {
      const proj = get().activeProject;
      if (!proj) return;
      set({
        activeProject: { ...proj, regions: [...proj.regions, region] },
        selectedRegionId: region.id,
        toolMode: "select",
      });
      schedulePersistAndPreview();
    },

    updateRegion: (id, patch) => {
      const proj = get().activeProject;
      if (!proj) return;
      const regions = proj.regions.map((r) => (r.id === id ? { ...r, ...patch } : r));
      set({ activeProject: { ...proj, regions } });
      schedulePersistAndPreview();
    },

    deleteRegion: (id) => {
      const proj = get().activeProject;
      if (!proj) return;
      const regions = proj.regions
        .filter((r) => r.id !== id)
        .map((r) => (r.next_region_id === id ? { ...r, next_region_id: null } : r));
      set({
        activeProject: { ...proj, regions },
        selectedRegionId: get().selectedRegionId === id ? null : get().selectedRegionId,
      });
      schedulePersistAndPreview();
    },

    updateStyle: (patch) => {
      const proj = get().activeProject;
      if (!proj) return;
      const nextStyle: HandwritingStyle = { ...proj.style, ...patch };
      set({ activeProject: { ...proj, style: nextStyle } });
      schedulePersistAndPreview();
    },

    refreshPreview: async () => {
      const proj = get().activeProject;
      if (!proj) return;
      const pageIdx = get().activePageIndex;
      const seq = ++previewSeq;
      set({ isRenderingPreview: true });
      try {
        const res = await api.renderPreview(proj.id, pageIdx, proj.regions, proj.style, 120);
        if (seq !== previewSeq) return;
        set({
          previewImageUrl: `data:image/png;base64,${res.image_base64}`,
          previewStats: res.stats,
          isRenderingPreview: false,
        });
      } catch (e) {
        if (seq !== previewSeq) return;
        set({ isRenderingPreview: false, errorMessage: (e as Error).message });
      }
    },

    openCaptureModal: (chars = "", title = "") =>
      set({
        captureModalOpen: true,
        captureInitialChars: chars,
        captureInitialTitle: title,
      }),
    closeCaptureModal: () => set({ captureModalOpen: false }),
    openAiModal: (chars = "", opts) =>
      set({
        aiModalOpen: true,
        aiInitialChars: chars,
        aiReplaceExisting: Boolean(opts?.replaceExistingAi),
      }),
    closeAiModal: () => set({ aiModalOpen: false }),
    setExportModalOpen: (open) => set({ exportModalOpen: open }),
    clearError: () => set({ errorMessage: null }),
  };
});
