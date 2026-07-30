# app/ingestion/metadata_enricher.py

from typing import Any, Dict, Optional, List
from .models import TableRegion, RegionAnalysisResult, RAGChunk, WorkbookGraph, EnhancedChunkMetadata


def _col_idx_to_letter(idx: int) -> str:
    """Converts 0-indexed column integer to Excel letter (0 -> A, 1 -> B, 25 -> Z, 26 -> AA)."""
    string = ""
    while idx >= 0:
        string = chr(idx % 26 + 65) + string
        idx = idx // 26 - 1
    return string


def _format_cell_range(bbox: Dict[str, int]) -> str:
    """Formats bounding box into standard Excel range string (e.g. B2:G25)."""
    start_col = _col_idx_to_letter(bbox.get("min_col", 0))
    start_row = bbox.get("min_row", 0) + 1  # 1-indexed for Excel
    end_col = _col_idx_to_letter(bbox.get("max_col", 0))
    end_row = bbox.get("max_row", 0) + 1
    return f"{start_col}{start_row}:{end_col}{end_row}"


def enrich_chunk_metadata(
    chunk: RAGChunk,
    region: TableRegion,
    analysis: RegionAnalysisResult,
    filename: str,
    graph: Optional[WorkbookGraph] = None
) -> RAGChunk:
    """Phase 8 Metadata Enrichment Engine: Builds comprehensive metadata dictionary for vector indexing."""
    
    # 1. Extract Bounding Box and Cell Range
    bbox = region.bounding_box
    cell_range = _format_cell_range(bbox)

    # 2. Extract Relationships from Phase 7 Graph
    rel_list = []
    if graph:
        for edge in graph.edges:
            if edge.source_region_id == region.region_id:
                rel_list.append({
                    "related_table": edge.target_table,
                    "join_key": edge.shared_key,
                    "cardinality": edge.cardinality
                })
            elif edge.target_region_id == region.region_id:
                rel_list.append({
                    "related_table": edge.source_table,
                    "join_key": edge.shared_key,
                    "cardinality": edge.cardinality
                })

    # 3. Construct Enhanced Metadata Pydantic Object
    enhanced_meta = EnhancedChunkMetadata(
        file_name=filename,
        sheet_name=region.sheet_name,
        bounding_box=bbox,
        cell_range=cell_range,
        table_name=analysis.table_name,
        entity_type=analysis.entity_type,
        chunk_strategy=analysis.chunk_strategy.value,
        entity_id=chunk.metadata.get("entity_id"),
        row_count=len(region.grid_values),
        column_count=len(region.grid_values[0]) if region.grid_values else 0,
        columns=analysis.flat_headers,
        confidence_score=analysis.confidence_score,
        business_context=analysis.summary,
        relationships=rel_list
    )

    # 4. Overwrite chunk metadata dict with flattened Pydantic payload
    chunk.metadata = enhanced_meta.model_dump()
    return chunk