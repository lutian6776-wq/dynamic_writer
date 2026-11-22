import type {
  AiJobStatus,
  AiStatus,
  AiSynthesizeRequest,
  BatchDeleteGlyphsRequest,
  BatchDeleteGlyphsResponse,
  CaptureSheetMeta,
  CharPreset,
  ExportRequest,
  GlyphImportDateStat,
  GlyphSortBy,
  GlyphSummary,
  HandwritingStyle,
  LanQrInfo,
  PreviewStats,
  Profile,
  Project,
  RegionConfig,
  SheetExtractResult,
} from "../types";

const getLocalTzOffsetMin = () => -new Date().getTimezoneOffset();

async function reqJson<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) {
    let msg = `请求失败 (${resp.status})`;
    try {
      const err = await resp.json();
      if (err?.detail) msg = String(err.detail);
    } catch {
      // ignore json parse failure
    }
    throw new Error(msg);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  // Profiles
  listProfiles: () => reqJson<Profile[]>("/api/profiles"),
  createProfile: (name: string) =>
    reqJson<Profile>("/api/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),

  // Glyphs
  listPresets: () => reqJson<CharPreset[]>("/api/glyphs/presets"),
  listGlyphs: (
    profileId: string,
    search = "",
    source: "all" | "tablet" | "ai_generated" = "all",
    opts?: { dateFrom?: string; dateTo?: string; sort?: GlyphSortBy }
  ) => {
    const params = new URLSearchParams({
      profile_id: profileId,
      search,
      source,
      tz_offset_min: String(getLocalTzOffsetMin()),
      sort: opts?.sort ?? "variant_count",
    });
    if (opts?.dateFrom) params.set("date_from", opts.dateFrom);
    if (opts?.dateTo) params.set("date_to", opts.dateTo);
    return reqJson<GlyphSummary[]>(`/api/glyphs?${params.toString()}`);
  },
  listGlyphImportDates: (
    profileId: string,
    source: "all" | "tablet" | "ai_generated" = "all"
  ) => {
    const params = new URLSearchParams({
      profile_id: profileId,
      source,
      tz_offset_min: String(getLocalTzOffsetMin()),
    });
    return reqJson<GlyphImportDateStat[]>(`/api/glyphs/dates?${params.toString()}`);
  },
  deleteGlyph: (glyphId: string) =>
    reqJson<{ deleted: boolean }>(`/api/glyphs/${encodeURIComponent(glyphId)}`, { method: "DELETE" }),
  batchDeleteGlyphs: (payload: BatchDeleteGlyphsRequest) =>
    reqJson<BatchDeleteGlyphsResponse>("/api/glyphs/batch-delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tz_offset_min: getLocalTzOffsetMin(),
        ...payload,
      }),
    }),
  analyzeText: (profileId: string, text: string) =>
    reqJson<{
      total_chars: number;
      unique_chars: number;
      covered_unique: number;
      missing_unique: number;
      coverage_ratio: number;
      unique_coverage_ratio: number;
      missing: { char: string; count: number }[];
      missing_chars_str: string;
    }>("/api/glyphs/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_id: profileId, text }),
    }),

  // Sheets
  listSheets: (profileId?: string) =>
    reqJson<CaptureSheetMeta[]>(
      profileId ? `/api/sheets?profile_id=${encodeURIComponent(profileId)}` : "/api/sheets"
    ),
  getLanQr: () => reqJson<LanQrInfo>("/api/sheets/lan-qr"),
  generateSheet: (payload: {
    profile_id: string;
    title: string;
    chars: string;
    preset_id?: string;
    variants_per_char: number;
    high_freq_chars?: string;
    high_freq_variants?: number;
  }) =>
    reqJson<CaptureSheetMeta>("/api/sheets/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  uploadSheet: async (file: File, profileId: string, overrideSheetId?: number | null) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("profile_id", profileId);
    if (overrideSheetId != null && !Number.isNaN(overrideSheetId)) {
      fd.append("override_sheet_id", String(overrideSheetId));
    }
    return reqJson<SheetExtractResult>("/api/sheets/upload", {
      method: "POST",
      body: fd,
    });
  },

  // Projects
  listProjects: () => reqJson<Project[]>("/api/projects"),
  uploadProject: async (file: File, profileId: string, name?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("profile_id", profileId);
    if (name) fd.append("name", name);
    return reqJson<Project>("/api/projects/upload", {
      method: "POST",
      body: fd,
    });
  },
  getProject: (id: string) => reqJson<Project>(`/api/projects/${id}`),
  updateProject: (
    id: string,
    payload: { name?: string; profile_id?: string; regions?: RegionConfig[]; style?: HandwritingStyle }
  ) =>
    reqJson<Project>(`/api/projects/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteProject: (id: string) =>
    reqJson<{ deleted: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),

  detectLines: (projectId: string, pageIndex: number, rect: { x: number; y: number; width: number; height: number }) =>
    reqJson<{ line_ys: number[]; line_spacing: number; baseline_offset: number; method: string }>(
      `/api/projects/${projectId}/pages/${pageIndex}/detect-lines`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(rect),
      }
    ),
  detectTable: (projectId: string, pageIndex: number, rect: { x: number; y: number; width: number; height: number }) =>
    reqJson<{ rows: number[]; cols: number[]; method: string }>(
      `/api/projects/${projectId}/pages/${pageIndex}/detect-table`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(rect),
      }
    ),
  renderPreview: (
    projectId: string,
    pageIndex: number,
    regions: RegionConfig[],
    style: HandwritingStyle,
    dpi = 120
  ) =>
    reqJson<{ image_base64: string; stats: PreviewStats }>(
      `/api/projects/${projectId}/pages/${pageIndex}/preview`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dpi, missing_char_mode: "highlight", regions, style }),
      }
    ),
  exportPdf: async (projectId: string, req: ExportRequest): Promise<Blob> => {
    const resp = await fetch(`/api/projects/${projectId}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!resp.ok) {
      throw new Error(`导出 PDF 失败 (${resp.status})`);
    }
    return resp.blob();
  },

  // Phase 2 AI Few-Shot Synthesis
  getAiStatus: () => reqJson<AiStatus>("/api/ai/status"),
  startAiSynthesize: (payload: AiSynthesizeRequest) =>
    reqJson<AiJobStatus>("/api/ai/synthesize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  getAiJob: (jobId: string) => reqJson<AiJobStatus>(`/api/ai/jobs/${encodeURIComponent(jobId)}`),
  unloadAiModel: () => reqJson<AiStatus>("/api/ai/unload", { method: "POST" }),
  deleteAllAiGlyphs: (profileId: string) =>
    reqJson<{ deleted: number }>(`/api/ai/glyphs/${encodeURIComponent(profileId)}`, {
      method: "DELETE",
    }),
};
