import React from "react";
import { Shuffle } from "lucide-react";
import { useAppStore } from "../store/useAppStore";
import { STYLE_PRESETS, type StrikethroughStyle } from "../types";

const INK_SWATCHES = [
  { name: "0.5mm 碳素黑", color: "#1c1d24" },
  { name: "蓝黑中性笔", color: "#192742" },
  { name: "深蓝圆珠笔", color: "#1d3d78" },
  { name: "浅灰铅笔", color: "#3d424d" },
];

export const StylePanel: React.FC = () => {
  const { activeProject, updateStyle } = useAppStore();
  if (!activeProject) return null;
  const s = activeProject.style;

  const applyPreset = (key: "neat" | "daily" | "rush") => {
    updateStyle(STYLE_PRESETS[key]);
  };

  return (
    <div className="flex flex-col gap-3 p-3 text-xs">
      <div>
        <div className="mb-1.5 font-semibold text-slate-700">书写状态预设</div>
        <div className="grid grid-cols-3 gap-1.5">
          {(
            [
              ["neat", "工整"],
              ["daily", "日常"],
              ["rush", "赶报告"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => applyPreset(key)}
              className={`rounded-md border px-2 py-1.5 font-medium transition ${
                s.preset === key
                  ? "border-blue-600 bg-blue-50 text-blue-700"
                  : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Ink color & thickness for matching real pen when hand-filling formulas */}
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-2.5">
        <div className="mb-1.5 font-semibold text-slate-700">墨色与笔锋粗细（匹配手补真笔）</div>
        <div className="flex items-center gap-2">
          {INK_SWATCHES.map((sw) => (
            <button
              key={sw.color}
              type="button"
              title={sw.name}
              onClick={() => updateStyle({ ink_color: sw.color })}
              className={`h-6 w-6 rounded-full border-2 ${
                s.ink_color.toLowerCase() === sw.color ? "border-blue-500 scale-110" : "border-white"
              }`}
              style={{ backgroundColor: sw.color }}
            />
          ))}
          <input
            type="color"
            value={s.ink_color}
            onChange={(e) => updateStyle({ ink_color: e.target.value })}
            className="h-6 w-8 cursor-pointer rounded border border-slate-300 bg-white"
          />
          <span className="ml-auto font-mono text-[11px] text-slate-500">{s.ink_color}</span>
        </div>

        <div className="mt-2">
          <div className="flex justify-between text-slate-600">
            <span>笔划粗细</span>
            <span>{s.stroke_weight.toFixed(2)}×</span>
          </div>
          <input
            type="range"
            min={0.65}
            max={1.55}
            step={0.05}
            value={s.stroke_weight}
            onChange={(e) => updateStyle({ stroke_weight: Number(e.target.value), preset: "custom" })}
            className="w-full"
          />
        </div>
      </div>

      {/* Natural perturbation sliders */}
      <div className="space-y-2 rounded-lg border border-slate-200 p-2.5">
        <div className="font-semibold text-slate-700">同字异形与排版微扰</div>

        <SliderRow
          label="弹性微形变"
          value={s.elastic_intensity}
          min={0}
          max={0.9}
          step={0.02}
          format={(v) => v.toFixed(2)}
          onChange={(v) => updateStyle({ elastic_intensity: v, preset: "custom" })}
        />
        <SliderRow
          label="字角随机旋转"
          value={s.rotation_sigma}
          min={0}
          max={6}
          step={0.1}
          format={(v) => `${v.toFixed(1)}°`}
          onChange={(v) => updateStyle({ rotation_sigma: v, preset: "custom" })}
        />
        <SliderRow
          label="字号微波动"
          value={s.scale_sigma}
          min={0}
          max={0.14}
          step={0.005}
          format={(v) => `${(v * 100).toFixed(1)}%`}
          onChange={(v) => updateStyle({ scale_sigma: v, preset: "custom" })}
        />
        <SliderRow
          label="视觉字距系数"
          value={s.word_spacing_factor}
          min={0.75}
          max={1.55}
          step={0.02}
          format={(v) => `${v.toFixed(2)}×`}
          onChange={(v) => updateStyle({ word_spacing_factor: v, preset: "custom" })}
        />
        <SliderRow
          label="基线柔和漂移"
          value={s.baseline_drift}
          min={0}
          max={4.5}
          step={0.1}
          format={(v) => `${v.toFixed(1)} pt`}
          onChange={(v) => updateStyle({ baseline_drift: v, preset: "custom" })}
        />
        <SliderRow
          label="整行倾斜角度"
          value={s.line_slant}
          min={-2.5}
          max={2.5}
          step={0.1}
          format={(v) => `${v > 0 ? "+" : ""}${v.toFixed(1)}°`}
          onChange={(v) => updateStyle({ line_slant: v, preset: "custom" })}
        />
        <SliderRow
          label="墨量深浅波动"
          value={s.ink_variation}
          min={0}
          max={0.3}
          step={0.01}
          format={(v) => `${(v * 100).toFixed(0)}%`}
          onChange={(v) => updateStyle({ ink_variation: v, preset: "custom" })}
        />
      </div>

      {/* Human imperfections */}
      <div className="space-y-2 rounded-lg border border-slate-200 p-2.5">
        <div className="font-semibold text-slate-700">人为瑕疵模拟</div>
        <SliderRow
          label="书写疲劳渐变"
          value={s.fatigue_intensity}
          min={0}
          max={1}
          step={0.05}
          format={(v) => `${(v * 100).toFixed(0)}%`}
          onChange={(v) => updateStyle({ fatigue_intensity: v, preset: "custom" })}
        />
        <SliderRow
          label="随机错字划掉概率"
          value={s.strikethrough_prob}
          min={0}
          max={0.04}
          step={0.002}
          format={(v) => `${(v * 100).toFixed(1)}%`}
          onChange={(v) => updateStyle({ strikethrough_prob: v, preset: "custom" })}
        />
        <div className="flex items-center justify-between">
          <span className="text-slate-600">划掉样式</span>
          <select
            value={s.strikethrough_style}
            onChange={(e) =>
              updateStyle({ strikethrough_style: e.target.value as StrikethroughStyle })
            }
            className="rounded border border-slate-300 px-2 py-0.5 text-xs"
          >
            <option value="double_line">自然双横线</option>
            <option value="scribble">波浪涂抹</option>
          </select>
        </div>
      </div>

      <button
        type="button"
        onClick={() => updateStyle({ seed: Math.floor(Math.random() * 100000) })}
        className="flex items-center justify-center gap-1.5 rounded-lg border border-slate-300 bg-white py-2 font-medium text-slate-700 hover:bg-slate-50"
      >
        <Shuffle className="h-3.5 w-3.5" />
        换一批同字异形布局 (Seed #{s.seed})
      </button>
    </div>
  );
};

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  onChange: (v: number) => void;
}

const SliderRow: React.FC<SliderProps> = ({ label, value, min, max, step, format, onChange }) => (
  <div>
    <div className="flex justify-between text-slate-600">
      <span>{label}</span>
      <span className="font-mono text-[11px]">{format(value)}</span>
    </div>
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-full"
    />
  </div>
);
