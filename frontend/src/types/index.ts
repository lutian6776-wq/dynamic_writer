export interface Profile {
  id: string;
  name: string;
  created_at: string;
}

export interface PageMeta {
  page_index: number;
  width_pt: number;
  height_pt: number;
}

export type RegionType = "single_line" | "multi_line" | "table";
export type TextAlign = "left" | "center" | "right";

export interface RegionConfig {
  id: string;
  page_index: number;
  name: string;
  type: RegionType;
  x: number;
  y: number;
  width: number;
  height: number;
  font_size: number;
  line_spacing: number;
  baseline_offset: number;
  first_line_indent: number;
  align: TextAlign;
  next_region_id: string | null;
  table_rows: number[];
  table_cols: number[];
  text: string;
}

export type StylePreset = "neat" | "daily" | "rush" | "custom";
export type StrikethroughStyle = "double_line" | "scribble";

export interface HandwritingStyle {
  preset: StylePreset;
  ink_color: string;
  stroke_weight: number;
  elastic_intensity: number;
  rotation_sigma: number;
  scale_sigma: number;
  word_spacing_factor: number;
  baseline_drift: number;
  line_slant: number;
  ink_variation: number;
  strikethrough_prob: number;
  strikethrough_style: StrikethroughStyle;
  fatigue_intensity: number;
  seed: number;
}

export interface Project {
  id: string;
  name: string;
  profile_id: string;
  template_kind: string;
  page_count: number;
  pages_meta: PageMeta[];
  regions: RegionConfig[];
  style: HandwritingStyle;
  updated_at: string;
}

export interface MissingCharStat {
  char: string;
  count: number;
}

export interface PreviewStats {
  total_chars: number;
  missing_counts: MissingCharStat[];
  missing_unique: number;
  ai_generated_chars?: string[];
  warnings: string[];
}

export interface GlyphVariant {
  id: string;
  char: string;
  source: string;
  image_url: string;
  visual_width_ratio: number;
  visual_height_ratio: number;
  ink_center_y: number;
  sheet_id: number | null;
  created_at: string;
  import_date?: string;
}

export interface GlyphSummary {
  char: string;
  variant_count: number;
  tablet_count: number;
  ai_count: number;
  has_tablet: boolean;
  has_ai: boolean;
  latest_image_url: string;
  latest_created_at: string;
  latest_import_date: string;
  variants: GlyphVariant[];
}

export type GlyphSortBy = "variant_count" | "latest" | "char";

export interface GlyphImportDateStat {
  date: string;
  variant_count: number;
  char_count: number;
  tablet_count: number;
  ai_count: number;
}

export interface BatchDeleteGlyphsRequest {
  profile_id: string;
  glyph_ids?: string[];
  chars?: string[];
  source?: "all" | "tablet" | "ai_generated";
  date_from?: string;
  date_to?: string;
  tz_offset_min?: number;
}

export interface BatchDeleteGlyphsResponse {
  deleted: number;
  deleted_ids: string[];
}

export interface AiStatus {
  available: boolean;
  cuda_available: boolean;
  device: string;
  gpu_name: string | null;
  vram_total_mb: number;
  vram_allocated_mb: number;
  ckpt_ready: boolean;
  ckpt_dir: string;
  loaded: boolean;
  missing_files: string[];
  error: string | null;
}

export interface AiSynthesizeRequest {
  profile_id: string;
  chars: string;
  variants_per_char?: number;
  num_inference_steps?: number;
  guidance_scale?: number;
  style_glyph_ids?: string[] | null;
  seed?: number;
  replace_existing_ai?: boolean;
}

export interface AiJobStatus {
  job_id: string;
  status: "running" | "done" | "error";
  profile_id: string;
  total: number;
  completed: number;
  current_char: string;
  generated_glyphs: {
    id: string;
    char: string;
    variant: number;
    image_url: string;
  }[];
  replaced_count?: number;
  errors: string[];
  elapsed_sec: number;
}

export interface CharPreset {
  id: string;
  name: string;
  description: string;
  chars: string;
}

export interface CaptureSheetMeta {
  sheet_id: number;
  profile_id: string;
  title: string;
  page_count: number;
  status: string;
  created_at: string;
  total_slots?: number;
  unique_chars?: number;
}

export interface SheetExtractResult {
  sheet_ids: number[];
  pages_processed: number;
  extracted_count: number;
  skipped_blank_count: number;
  extracted_glyphs: {
    id: string;
    char: string;
    variant: number;
    image_url: string;
  }[];
  warnings: string[];
}

export interface LanQrInfo {
  url: string;
  ip: string;
  svg: string;
}

export interface ExportRequest {
  dpi: 300 | 600;
  mode: "composite" | "overlay_only";
  offset_x_mm: number;
  offset_y_mm: number;
  missing_char_mode: "blank" | "highlight";
}

export const STYLE_PRESETS: Record<"neat" | "daily" | "rush", Partial<HandwritingStyle>> = {
  neat: {
    preset: "neat",
    stroke_weight: 1.0,
    elastic_intensity: 0.1,
    rotation_sigma: 0.7,
    scale_sigma: 0.02,
    word_spacing_factor: 0.98,
    baseline_drift: 0.4,
    line_slant: 0.0,
    ink_variation: 0.04,
    strikethrough_prob: 0.0,
    fatigue_intensity: 0.05,
  },
  daily: {
    preset: "daily",
    stroke_weight: 1.0,
    elastic_intensity: 0.28,
    rotation_sigma: 1.8,
    scale_sigma: 0.045,
    word_spacing_factor: 1.02,
    baseline_drift: 1.2,
    line_slant: 0.0,
    ink_variation: 0.08,
    strikethrough_prob: 0.0,
    fatigue_intensity: 0.2,
  },
  rush: {
    preset: "rush",
    stroke_weight: 0.96,
    elastic_intensity: 0.52,
    rotation_sigma: 3.4,
    scale_sigma: 0.075,
    word_spacing_factor: 1.08,
    baseline_drift: 2.2,
    line_slant: -0.6,
    ink_variation: 0.14,
    strikethrough_prob: 0.008,
    fatigue_intensity: 0.55,
  },
};
