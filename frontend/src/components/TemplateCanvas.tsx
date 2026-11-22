import React, { useEffect, useRef, useState } from "react";
import { Group, Image as KonvaImage, Layer, Line, Rect, Stage, Text, Transformer } from "react-konva";
import type Konva from "konva";
import type { RegionConfig } from "../types";
import { useAppStore } from "../store/useAppStore";

function useHtmlImage(url: string | null): HTMLImageElement | null {
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  useEffect(() => {
    if (!url) {
      setImg(null);
      return;
    }
    let alive = true;
    const image = new window.Image();
    image.crossOrigin = "anonymous";
    image.onload = () => {
      if (alive) setImg(image);
    };
    image.src = url;
    return () => {
      alive = false;
    };
  }, [url]);
  return img;
}

interface Props {
  zoom: number;
  setZoom: (z: number) => void;
}

export const TemplateCanvas: React.FC<Props> = ({ zoom, setZoom }) => {
  const {
    activeProject,
    activePageIndex,
    selectedRegionId,
    setSelectedRegionId,
    toolMode,
    showHelpers,
    previewImageUrl,
    addRegion,
    updateRegion,
  } = useAppStore();

  const containerRef = useRef<HTMLDivElement>(null);
  const trRef = useRef<Konva.Transformer>(null);
  const shapeRefs = useRef<Record<string, Konva.Rect>>({});

  const [size, setSize] = useState({ width: 800, height: 640 });
  const [pan, setPan] = useState({ x: 40, y: 24 });
  const [draftBox, setDraftBox] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const drawStartRef = useRef<{ x: number; y: number } | null>(null);
  const isPanningRef = useRef(false);
  const panOriginRef = useRef<{ x: number; y: number; px: number; py: number }>({ x: 0, y: 0, px: 0, py: 0 });

  const pageMeta = activeProject?.pages_meta[activePageIndex];
  const pageWidthPt = pageMeta?.width_pt ?? 595.28;
  const pageHeightPt = pageMeta?.height_pt ?? 841.89;

  const bgUrl = activeProject
    ? `/api/projects/${activeProject.id}/pages/${activePageIndex}/background?dpi=150`
    : null;
  const bgImage = useHtmlImage(bgUrl);
  const overlayImage = useHtmlImage(previewImageUrl);

  // Resize observer for responsive Stage
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setSize({
          width: Math.max(300, entry.contentRect.width),
          height: Math.max(300, entry.contentRect.height),
        });
      }
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // Auto fit page when switching project or page
  useEffect(() => {
    if (!activeProject || !pageMeta) return;
    const fitZoom = Math.min(
      (size.width - 64) / pageMeta.width_pt,
      (size.height - 48) / pageMeta.height_pt,
      1.35
    );
    const z = Math.max(0.35, Number(fitZoom.toFixed(2)));
    setZoom(z);
    setPan({
      x: Math.max(16, (size.width - pageMeta.width_pt * z) * 0.5),
      y: 20,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProject?.id, activePageIndex]);

  const pageRegions = activeProject
    ? activeProject.regions.filter((r) => r.page_index === activePageIndex)
    : [];

  // Sync Konva Transformer with selected region
  useEffect(() => {
    const tr = trRef.current;
    if (!tr) return;
    if (selectedRegionId && showHelpers && shapeRefs.current[selectedRegionId]) {
      tr.nodes([shapeRefs.current[selectedRegionId]]);
      tr.getLayer()?.batchDraw();
    } else {
      tr.nodes([]);
      tr.getLayer()?.batchDraw();
    }
  }, [selectedRegionId, pageRegions.length, showHelpers]);

  const getStagePagePoint = (stage: Konva.Stage) => {
    const pointer = stage.getPointerPosition();
    if (!pointer) return { x: 0, y: 0 };
    return {
      x: (pointer.x - pan.x) / zoom,
      y: (pointer.y - pan.y) / zoom,
    };
  };

  const handleWheel = (e: Konva.KonvaEventObject<WheelEvent>) => {
    e.evt.preventDefault();
    const stage = e.target.getStage();
    if (!stage) return;
    const pointer = stage.getPointerPosition();
    if (!pointer) return;

    const scaleBy = 1.1;
    const oldZoom = zoom;
    const newZoom = e.evt.deltaY < 0 ? Math.min(3.5, oldZoom * scaleBy) : Math.max(0.25, oldZoom / scaleBy);
    const mousePointTo = {
      x: (pointer.x - pan.x) / oldZoom,
      y: (pointer.y - pan.y) / oldZoom,
    };
    setZoom(newZoom);
    setPan({
      x: pointer.x - mousePointTo.x * newZoom,
      y: pointer.y - mousePointTo.y * newZoom,
    });
  };

  const handleMouseDown = (e: Konva.KonvaEventObject<MouseEvent>) => {
    const stage = e.target.getStage();
    if (!stage) return;

    // Middle mouse button or Shift+click pans canvas
    if (e.evt.button === 1 || (toolMode === "select" && e.evt.shiftKey)) {
      isPanningRef.current = true;
      panOriginRef.current = { x: e.evt.clientX, y: e.evt.clientY, px: pan.x, py: pan.y };
      return;
    }

    if (toolMode !== "select") {
      const pt = getStagePagePoint(stage);
      drawStartRef.current = pt;
      setDraftBox({ x: pt.x, y: pt.y, w: 0, h: 0 });
      return;
    }

    // Clicking empty background deselects or allows dragging background to pan
    const clickedOnEmpty = e.target === stage || e.target.name() === "page-bg" || e.target.name() === "page-paper";
    if (clickedOnEmpty) {
      setSelectedRegionId(null);
      isPanningRef.current = true;
      panOriginRef.current = { x: e.evt.clientX, y: e.evt.clientY, px: pan.x, py: pan.y };
    }
  };

  const handleMouseMove = (e: Konva.KonvaEventObject<MouseEvent>) => {
    if (isPanningRef.current) {
      const dx = e.evt.clientX - panOriginRef.current.x;
      const dy = e.evt.clientY - panOriginRef.current.y;
      setPan({ x: panOriginRef.current.px + dx, y: panOriginRef.current.py + dy });
      return;
    }
    if (drawStartRef.current) {
      const stage = e.target.getStage();
      if (!stage) return;
      const pt = getStagePagePoint(stage);
      const sx = drawStartRef.current.x;
      const sy = drawStartRef.current.y;
      setDraftBox({
        x: Math.min(sx, pt.x),
        y: Math.min(sy, pt.y),
        w: Math.abs(pt.x - sx),
        h: Math.abs(pt.y - sy),
      });
    }
  };

  const handleMouseUp = () => {
    if (isPanningRef.current) {
      isPanningRef.current = false;
    }
    if (drawStartRef.current && draftBox) {
      if (draftBox.w >= 18 && draftBox.h >= 12) {
        const type =
          toolMode === "draw_single_line"
            ? "single_line"
            : toolMode === "draw_table"
            ? "table"
            : "multi_line";
        const label =
          type === "single_line" ? "单行填空" : type === "table" ? "数据表格" : "正文区域";
        const newReg: RegionConfig = {
          id: `reg_${Math.random().toString(36).slice(2, 8)}`,
          page_index: activePageIndex,
          name: `${label} ${pageRegions.length + 1}`,
          type,
          x: Math.round(draftBox.x * 10) / 10,
          y: Math.round(draftBox.y * 10) / 10,
          width: Math.round(draftBox.w * 10) / 10,
          height: Math.round(draftBox.h * 10) / 10,
          font_size: type === "table" ? 13 : 16,
          line_spacing: 24,
          baseline_offset: 20,
          first_line_indent: 0,
          align: type === "table" ? "center" : "left",
          next_region_id: null,
          table_rows: [0.0, 0.33, 0.66, 1.0],
          table_cols: [0.0, 0.33, 0.66, 1.0],
          text: type === "table" ? "项目\t数值\t单位\n1\t1.02\tV\n2\t2.05\tV" : "",
        };
        addRegion(newReg);
      }
      drawStartRef.current = null;
      setDraftBox(null);
    }
  };

  const renderRegionHelpers = (reg: RegionConfig) => {
    const isSel = reg.id === selectedRegionId;
    const strokeColor =
      reg.type === "table" ? "#9333ea" : reg.type === "single_line" ? "#059669" : "#2563eb";

    const lines: React.ReactNode[] = [];
    if (isSel && reg.type === "multi_line") {
      const spacing = Math.max(8, reg.line_spacing);
      let curY = reg.y + reg.baseline_offset;
      let idx = 0;
      while (curY <= reg.y + reg.height + 2 && idx < 60) {
        const startX = idx === 0 ? reg.x + reg.first_line_indent : reg.x;
        lines.push(
          <Line
            key={`bl-${idx}`}
            points={[startX, curY, reg.x + reg.width, curY]}
            stroke="#38bdf8"
            strokeWidth={1 / zoom}
            dash={[4 / zoom, 3 / zoom]}
            listening={false}
          />
        );
        curY += spacing;
        idx++;
      }
    }

    const tableSplitters: React.ReactNode[] = [];
    if (isSel && reg.type === "table") {
      reg.table_rows.slice(1, -1).forEach((ratio, idx) => {
        const ry = reg.y + ratio * reg.height;
        tableSplitters.push(
          <Line
            key={`tr-${idx}`}
            points={[reg.x, ry, reg.x + reg.width, ry]}
            stroke="#a855f7"
            strokeWidth={2 / zoom}
            hitStrokeWidth={10 / zoom}
            draggable
            dragBoundFunc={(pos) => {
              const pageY = (pos.y - pan.y) / zoom;
              const clampedY = Math.max(reg.y + 6, Math.min(reg.y + reg.height - 6, pageY));
              return { x: pan.x, y: clampedY * zoom + pan.y };
            }}
            onDragEnd={(e) => {
              const absY = e.target.y();
              const newRatio = Math.max(0.05, Math.min(0.95, ratio + absY / reg.height));
              e.target.y(0);
              const nextRows = [...reg.table_rows];
              nextRows[idx + 1] = Number(newRatio.toFixed(4));
              nextRows.sort((a, b) => a - b);
              updateRegion(reg.id, { table_rows: nextRows });
            }}
          />
        );
      });
      reg.table_cols.slice(1, -1).forEach((ratio, idx) => {
        const cx = reg.x + ratio * reg.width;
        tableSplitters.push(
          <Line
            key={`tc-${idx}`}
            points={[cx, reg.y, cx, reg.y + reg.height]}
            stroke="#a855f7"
            strokeWidth={2 / zoom}
            hitStrokeWidth={10 / zoom}
            draggable
            dragBoundFunc={(pos) => {
              const pageX = (pos.x - pan.x) / zoom;
              const clampedX = Math.max(reg.x + 6, Math.min(reg.x + reg.width - 6, pageX));
              return { x: clampedX * zoom + pan.x, y: pan.y };
            }}
            onDragEnd={(e) => {
              const absX = e.target.x();
              const newRatio = Math.max(0.05, Math.min(0.95, ratio + absX / reg.width));
              e.target.x(0);
              const nextCols = [...reg.table_cols];
              nextCols[idx + 1] = Number(newRatio.toFixed(4));
              nextCols.sort((a, b) => a - b);
              updateRegion(reg.id, { table_cols: nextCols });
            }}
          />
        );
      });
    }

    return (
      <Group key={reg.id}>
        <Rect
          ref={(node) => {
            if (node) shapeRefs.current[reg.id] = node;
          }}
          x={reg.x}
          y={reg.y}
          width={reg.width}
          height={reg.height}
          stroke={strokeColor}
          strokeWidth={(isSel ? 1.8 : 1.1) / zoom}
          fill={isSel ? "rgba(37, 99, 235, 0.04)" : "rgba(37, 99, 235, 0.015)"}
          dash={isSel ? undefined : [5 / zoom, 3 / zoom]}
          draggable={toolMode === "select"}
          onClick={() => setSelectedRegionId(reg.id)}
          onTap={() => setSelectedRegionId(reg.id)}
          onDragEnd={(e) => {
            updateRegion(reg.id, {
              x: Math.round(e.target.x() * 10) / 10,
              y: Math.round(e.target.y() * 10) / 10,
            });
          }}
          onTransformEnd={(e) => {
            const node = e.target;
            const scaleX = node.scaleX();
            const scaleY = node.scaleY();
            node.scaleX(1);
            node.scaleY(1);
            updateRegion(reg.id, {
              x: Math.round(node.x() * 10) / 10,
              y: Math.round(node.y() * 10) / 10,
              width: Math.max(18, Math.round(node.width() * scaleX * 10) / 10),
              height: Math.max(12, Math.round(node.height() * scaleY * 10) / 10),
            });
          }}
        />
        <Text
          x={reg.x + 2}
          y={Math.max(2, reg.y - 13 / zoom)}
          text={reg.next_region_id ? `${reg.name} ➔` : reg.name}
          fontSize={11 / zoom}
          fill={strokeColor}
          listening={false}
        />
        {lines}
        {tableSplitters}
      </Group>
    );
  };

  return (
    <div
      ref={containerRef}
      className={`relative flex-1 overflow-hidden bg-slate-200/80 ${
        toolMode === "select" ? "cursor-default" : "cursor-crosshair"
      }`}
    >
      <Stage
        width={size.width}
        height={size.height}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
      >
        <Layer x={pan.x} y={pan.y} scaleX={zoom} scaleY={zoom}>
          {/* White paper shadow backdrop */}
          <Rect
            name="page-paper"
            x={0}
            y={0}
            width={pageWidthPt}
            height={pageHeightPt}
            fill="#ffffff"
            shadowColor="rgba(15, 23, 42, 0.22)"
            shadowBlur={18}
            shadowOffset={{ x: 0, y: 4 }}
          />
          {bgImage && (
            <KonvaImage
              name="page-bg"
              image={bgImage}
              x={0}
              y={0}
              width={pageWidthPt}
              height={pageHeightPt}
            />
          )}
          {overlayImage && (
            <KonvaImage
              image={overlayImage}
              x={0}
              y={0}
              width={pageWidthPt}
              height={pageHeightPt}
              listening={false}
            />
          )}

          {showHelpers && pageRegions.map(renderRegionHelpers)}

          {showHelpers && draftBox && (
            <Rect
              x={draftBox.x}
              y={draftBox.y}
              width={draftBox.w}
              height={draftBox.h}
              stroke="#2563eb"
              strokeWidth={1.5 / zoom}
              dash={[4 / zoom, 3 / zoom]}
              fill="rgba(37, 99, 235, 0.08)"
              listening={false}
            />
          )}

          {showHelpers && (
            <Transformer
              ref={trRef}
              rotateEnabled={false}
              keepRatio={false}
              anchorSize={7}
              borderStroke="#2563eb"
              anchorStroke="#2563eb"
              anchorFill="#ffffff"
            />
          )}
        </Layer>
      </Stage>

      <div className="pointer-events-none absolute bottom-3 left-3 rounded-md bg-slate-900/70 px-2.5 py-1 text-xs text-white backdrop-blur">
        滚轮缩放 · 拖动空白处平移 · 选中框后可拖拽四边调大小
      </div>
    </div>
  );
};
