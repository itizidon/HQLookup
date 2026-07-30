# app/ingestion/validators.py

from typing import Dict, Any
from .models import TableRegion, RegionAnalysisResult, ChunkStrategy

CONFIDENCE_THRESHOLD = 0.70

# Map raw strategy strings to Enum
STRATEGY_MAP = {
    "entity": ChunkStrategy.ENTITY,
    "table": ChunkStrategy.TABLE,
    "matrix": ChunkStrategy.MATRIX,
    "pivot": ChunkStrategy.PIVOT,
    "summary": ChunkStrategy.SUMMARY,
    "form": ChunkStrategy.FORM,
    "calendar": ChunkStrategy.CALENDAR,
    "ledger": ChunkStrategy.LEDGER,
    "row": ChunkStrategy.TABLE,  # Map legacy 'row' to TABLE
}


def _run_heuristic_fallback(region: TableRegion) -> RegionAnalysisResult:
    """Fallback parser if LLM fails or returns low confidence."""
    grid = region.grid_values
    num_rows = len(grid)
    num_cols = len(grid[0]) if grid else 0

    if num_rows == 0 or num_cols == 0:
        return RegionAnalysisResult(
            table_name="Empty Region",
            entity_type="Unknown",
            header_row_index=0,
            data_start_index=0,
            chunk_strategy=ChunkStrategy.TABLE,
            confidence_score=0.0,
            summary="Empty table region."
        )

    # 1. Determine Header Row
    header_idx = 0
    for r_idx in range(min(3, num_rows)):
        if any(isinstance(cell, str) and cell.strip() for cell in grid[r_idx]):
            header_idx = r_idx
            break

    data_start_idx = min(header_idx + 1, num_rows)
    header_cells = [str(c).lower() for c in grid[header_idx] if c is not None]
    header_text = " ".join(header_cells)

    # 2. Geometry & Keyword Heuristics for Strategy Selection
    strategy = ChunkStrategy.TABLE

    # Check for CALENDAR (days/months in headers)
    time_keywords = {"monday", "tuesday", "wednesday", "thursday", "friday", "january", "february", "march", "q1", "q2"}
    if any(kw in header_text for kw in time_keywords):
        strategy = ChunkStrategy.CALENDAR

    # Check for LEDGER (balance, debit, credit, transaction)
    elif any(kw in header_text for kw in {"balance", "debit", "credit", "transaction", "amount"}):
        strategy = ChunkStrategy.LEDGER

    # Check for FORM (small key-value grid layout)
    elif num_cols <= 4 and num_rows <= 8 and any(":" in str(cell) for row in grid for cell in row if cell):
        strategy = ChunkStrategy.FORM

    # Check for SUMMARY (KPI cards or very small tables)
    elif num_rows <= 3:
        strategy = ChunkStrategy.SUMMARY

    # Check for ENTITY (duplicate values in column 0)
    elif num_rows > 4:
        col0_vals = [grid[r][0] for r in range(data_start_idx, num_rows) if grid[r] and grid[r][0] is not None]
        if len(col0_vals) >= 4 and len(set(col0_vals)) < len(col0_vals) * 0.6:
            strategy = ChunkStrategy.ENTITY

    return RegionAnalysisResult(
        table_name=f"Table ({region.sheet_name})",
        entity_type="Record",
        header_row_index=header_idx,
        data_start_index=data_start_idx,
        chunk_strategy=strategy,
        group_by_column=str(grid[header_idx][0]) if (strategy == ChunkStrategy.ENTITY and grid[header_idx]) else None,
        confidence_score=0.50,
        summary="Heuristically extracted table region."
    )


def validate_and_sanitize_analysis(
    raw_json: Dict[str, Any], 
    region: TableRegion
) -> RegionAnalysisResult:
    """Phase 5 Airlock: Validates strategy type and structure against actual grid dimensions."""
    grid = region.grid_values
    num_rows = len(grid)

    if num_rows == 0:
        return _run_heuristic_fallback(region)

    try:
        # CHECK 1: Confidence
        confidence = float(raw_json.get("confidence", raw_json.get("confidence_score", 0.0)))
        if confidence < CONFIDENCE_THRESHOLD:
            print(f"[Phase 5 Fallback] Confidence {confidence:.2f} below threshold {CONFIDENCE_THRESHOLD}.")
            return _run_heuristic_fallback(region)

        # CHECK 2: Bounds
        header_row = int(raw_json.get("header_row", raw_json.get("header_row_index", 0)))
        data_start = int(raw_json.get("data_start", raw_json.get("data_start_index", header_row + 1)))

        if not (0 <= header_row < num_rows) or data_start <= header_row or data_start > num_rows:
            print(f"[Phase 5 Fallback] Invalid indices (header: {header_row}, data_start: {data_start}).")
            return _run_heuristic_fallback(region)

        # CHECK 3: Strategy Parsing
        raw_strat = str(raw_json.get("chunk_strategy", "table")).lower().strip()
        strategy = STRATEGY_MAP.get(raw_strat, ChunkStrategy.TABLE)

        group_by = raw_json.get("entity_key", raw_json.get("group_by_column"))

        # Check entity column exists if ENTITY strategy was selected
        if strategy == ChunkStrategy.ENTITY and group_by:
            header_cells = [str(c).strip().lower() for c in grid[header_row] if c is not None]
            clean_group_by = str(group_by).strip().lower()
            
            match_found = any(clean_group_by in h or h in clean_group_by for h in header_cells)
            if not match_found:
                print(f"[Phase 5 Warning] Group key '{group_by}' missing in headers. Demoting ENTITY -> TABLE.")
                strategy = ChunkStrategy.TABLE
                group_by = None

        return RegionAnalysisResult(
            table_name=raw_json.get("title", raw_json.get("table_name", "Untitled Table")),
            entity_type=raw_json.get("entity", raw_json.get("entity_type", "Record")),
            header_row_index=header_row,
            data_start_index=data_start,
            chunk_strategy=strategy,
            group_by_column=group_by,
            relationships=raw_json.get("relationships", []),
            summary=raw_json.get("summary", ""),
            confidence_score=confidence
        )

    except Exception as e:
        print(f"[Phase 5 Exception] Validation failed: {e}. Running fallback.")
        return _run_heuristic_fallback(region)