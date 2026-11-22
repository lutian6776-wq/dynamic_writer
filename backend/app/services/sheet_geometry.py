"""Single source of truth for A4 capture sheet coordinates, markers, and barcode."""

from __future__ import annotations

A4_W_MM = 210.0
A4_H_MM = 297.0
MM_TO_PT = 72.0 / 25.4
EXTRACTION_DPI = 300
MM_TO_PX = EXTRACTION_DPI / 25.4

A4_W_PT = A4_W_MM * MM_TO_PT
A4_H_PT = A4_H_MM * MM_TO_PT

# Exact width/height at 300 DPI
A4_W_PX = int(round(A4_W_MM * MM_TO_PX))  # 2480
A4_H_PX = int(round(A4_H_MM * MM_TO_PX))  # 3508

# Concentric square fiducial markers at 4 corners (TL, TR, BR, BL)
MARKER_CENTERS_MM: list[tuple[float, float]] = [
    (12.0, 12.0),
    (198.0, 12.0),
    (198.0, 285.0),
    (12.0, 285.0),
]
MARKER_OUTER_MM = 10.0
MARKER_MID_MM = 6.2
MARKER_INNER_MM = 3.0

# 18-cell header barcode: [0]=black cal, [1..16]=16-bit code MSB first, [17]=black cal
BARCODE_CELL_COUNT = 18
BARCODE_X_START_MM = 24.0
BARCODE_Y_TOP_MM = 8.5
BARCODE_CELL_W_MM = 4.6
BARCODE_CELL_H_MM = 5.8
BARCODE_CELL_GAP_MM = 1.0

# Character cell grid: 8 cols x 9 rows = 72 cells per page
GRID_COLS = 8
GRID_ROWS = 9
CELLS_PER_PAGE = GRID_COLS * GRID_ROWS

GRID_LEFT_MM = 14.0
GRID_TOP_MM = 26.0
PITCH_X_MM = 23.0
PITCH_Y_MM = 27.6
LABEL_H_MM = 5.6
BOX_SIZE_MM = 19.8


def pack_sheet_code(sheet_id: int, page_index: int) -> int:
    """Pack sheet_id (0..1023) and page_index (0..63) into 16 bits."""
    return ((int(sheet_id) & 0x3FF) << 6) | (int(page_index) & 0x3F)


def unpack_sheet_code(code: int) -> tuple[int, int]:
    """Unpack 16-bit integer back into (sheet_id, page_index)."""
    sheet_id = (int(code) >> 6) & 0x3FF
    page_index = int(code) & 0x3F
    return sheet_id, page_index


def get_cell_rects_mm(row: int, col: int) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    """Return (label_rect_mm, box_rect_mm) as (x0, y0, x1, y1) for cell (row, col)."""
    x0 = GRID_LEFT_MM + col * PITCH_X_MM
    label_y0 = GRID_TOP_MM + row * PITCH_Y_MM
    label_y1 = label_y0 + LABEL_H_MM
    box_y0 = label_y1
    box_y1 = box_y0 + BOX_SIZE_MM
    return (x0, label_y0, x0 + BOX_SIZE_MM, label_y1), (x0, box_y0, x0 + BOX_SIZE_MM, box_y1)
