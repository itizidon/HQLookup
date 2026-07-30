# app/ingestion/chunk_builder.py

from typing import List, Dict, Any, Optional
from .models import TableRegion, RegionAnalysisResult, RAGChunk, ChunkStrategy


def _format_cell(val: Any) -> str:
    """Cleans cell values for text representation."""
    if val is None:
        return ""
    s = str(val).replace("\n", " ").strip()
    return "" if s.lower() in ("none", "null", "nan") else s


# -------------------------------------------------------------------
# 1. ENTITY Strategy (Groups multi-row records)
# -------------------------------------------------------------------
def _build_entity_chunks(region: TableRegion, analysis: RegionAnalysisResult) -> List[RAGChunk]:
    headers = analysis.flat_headers
    data_rows = region.grid_values[analysis.data_start_index:]
    group_col = analysis.group_by_column or (headers[0] if headers else "")

    group_col_idx = headers.index(group_col) if group_col in headers else 0

    grouped: Dict[str, List[List[Any]]] = {}
    for row in data_rows:
        key = _format_cell(row[group_col_idx]) if group_col_idx < len(row) else ""
        if key:
            grouped.setdefault(key, []).append(row)

    chunks = []
    for idx, (entity_id, rows) in enumerate(grouped.items()):
        lines = [f"Table: {analysis.table_name} | {analysis.entity_type}: {entity_id}"]
        for r_idx, r in enumerate(rows):
            pairs = [f"{h}: {_format_cell(r[i])}" for i, h in enumerate(headers) if i < len(r) and _format_cell(r[i])]
            if pairs:
                lines.append(f"- Record {r_idx + 1}: " + " | ".join(pairs))
        
        chunks.append(RAGChunk(
            chunk_id=f"{region.region_id}_entity_{idx}",
            content="\n".join(lines),
            metadata={"entity_id": entity_id, "table_name": analysis.table_name, "strategy": "entity"}
        ))
    return chunks


# -------------------------------------------------------------------
# 2. FORM Strategy (Key-Value Intake Layouts)
# -------------------------------------------------------------------
def _build_form_chunks(region: TableRegion, analysis: RegionAnalysisResult) -> List[RAGChunk]:
    """Parses non-tabular key-value layouts (e.g. B2: 'Patient Name', C2: 'John Doe')."""
    kv_pairs = []
    grid = region.grid_values

    for r in grid:
        for c in range(0, len(r) - 1, 2):
            label = _format_cell(r[c])
            val = _format_cell(r[c + 1]) if c + 1 < len(r) else ""
            if label and val and label.endswith(":"):
                kv_pairs.append(f"• {label} {val}")
            elif label and val:
                kv_pairs.append(f"• {label}: {val}")

    content = f"Form: {analysis.table_name} ({analysis.entity_type})\n" + "\n".join(kv_pairs)
    return [RAGChunk(
        chunk_id=f"{region.region_id}_form",
        content=content,
        metadata={"table_name": analysis.table_name, "strategy": "form"}
    )]


# -------------------------------------------------------------------
# 3. CALENDAR Strategy (Temporal / Schedule Grids)
# -------------------------------------------------------------------
def _build_calendar_chunks(region: TableRegion, analysis: RegionAnalysisResult) -> List[RAGChunk]:
    """Groups day/time headers with event cells."""
    headers = analysis.flat_headers
    data_rows = region.grid_values[analysis.data_start_index:]
    events = []

    for row in data_rows:
        time_or_row_label = _format_cell(row[0]) if row else ""
        for c_idx in range(1, len(headers)):
            val = _format_cell(row[c_idx]) if c_idx < len(row) else ""
            if val:
                day_header = headers[c_idx]
                events.append(f"• [{day_header} @ {time_or_row_label}]: {val}")

    content = f"Schedule / Calendar: {analysis.table_name}\n" + "\n".join(events)
    return [RAGChunk(
        chunk_id=f"{region.region_id}_calendar",
        content=content,
        metadata={"table_name": analysis.table_name, "strategy": "calendar"}
    )]


# -------------------------------------------------------------------
# 4. LEDGER Strategy (Transactions & Running Balances)
# -------------------------------------------------------------------
def _build_ledger_chunks(region: TableRegion, analysis: RegionAnalysisResult) -> List[RAGChunk]:
    """Preserves sequential order and transaction line items."""
    headers = analysis.flat_headers
    data_rows = region.grid_values[analysis.data_start_index:]
    entries = []

    for idx, row in enumerate(data_rows):
        pairs = [f"{h}: {_format_cell(row[i])}" for i, h in enumerate(headers) if i < len(row) and _format_cell(row[i])]
        if pairs:
            entries.append(f"Entry {idx + 1}: " + " | ".join(pairs))

    content = f"Financial Ledger: {analysis.table_name}\n" + "\n".join(entries)
    return [RAGChunk(
        chunk_id=f"{region.region_id}_ledger",
        content=content,
        metadata={"table_name": analysis.table_name, "strategy": "ledger"}
    )]


# -------------------------------------------------------------------
# 5. PIVOT Strategy (Subtotals & Multi-level Aggregations)
# -------------------------------------------------------------------
def _build_pivot_chunks(region: TableRegion, analysis: RegionAnalysisResult) -> List[RAGChunk]:
    """Preserves cross-tab totals and hierarchy."""
    headers = analysis.flat_headers
    data_rows = region.grid_values[analysis.data_start_index:]
    lines = [f"Pivot Summary: {analysis.table_name}", f"Dimensions: {', '.join(headers)}"]

    for row in data_rows:
        row_str = " | ".join([_format_cell(c) for c in row if _format_cell(c)])
        if row_str:
            lines.append(f"• {row_str}")

    return [RAGChunk(
        chunk_id=f"{region.region_id}_pivot",
        content="\n".join(lines),
        metadata={"table_name": analysis.table_name, "strategy": "pivot"}
    )]


# -------------------------------------------------------------------
# 6. SUMMARY / TABLE / MATRIX (Standard Builders)
# -------------------------------------------------------------------
def _build_whole_table_chunks(region: TableRegion, analysis: RegionAnalysisResult) -> List[RAGChunk]:
    headers = analysis.flat_headers
    data_rows = region.grid_values[analysis.data_start_index:]
    
    md = [
        f"### {analysis.table_name}",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |"
    ]
    for row in data_rows:
        vals = [_format_cell(row[i]) if i < len(row) else "" for i in range(len(headers))]
        md.append("| " + " | ".join(vals) + " |")

    return [RAGChunk(
        chunk_id=f"{region.region_id}_table",
        content="\n".join(md),
        metadata={"table_name": analysis.table_name, "strategy": analysis.chunk_strategy.value}
    )]


# -------------------------------------------------------------------
# Phase 6 Main Dispatcher
# -------------------------------------------------------------------
def build_chunks_for_region(region: TableRegion, analysis: RegionAnalysisResult) -> List[RAGChunk]:
    strategy = analysis.chunk_strategy

    if strategy == ChunkStrategy.ENTITY:
        return _build_entity_chunks(region, analysis)
    elif strategy in (ChunkStrategy.TABLE, ChunkStrategy.SUMMARY):
        return _build_whole_table_chunks(region, analysis)
    elif strategy == ChunkStrategy.FORM:
        return _build_form_chunks(region, analysis)
    elif strategy == ChunkStrategy.CALENDAR:
        return _build_calendar_chunks(region, analysis)
    elif strategy == ChunkStrategy.LEDGER:
        return _build_ledger_chunks(region, analysis)
    elif strategy == ChunkStrategy.PIVOT:
        return _build_pivot_chunks(region, analysis)
    else:
        # Default fallback
        return _build_whole_table_chunks(region, analysis)