# app/ingestion/relationship_detector.py

import re
from typing import List, Dict, Tuple, Set, Any
from .models import TableRegion, RegionAnalysisResult, TableRelationship, WorkbookGraph, RAGChunk


def _normalize_key(key_name: str) -> str:
    """Normalizes header names for matching (e.g., 'Patient_ID', 'patient id', 'PatientID' -> 'patient_id')."""
    s = re.sub(r'[\s_\-]+', '_', key_name.strip().lower())
    s = re.sub(r'([a-z])([A-Z])', r'\1_\2', s).lower()
    return s


def _is_id_candidate(normalized_key: str) -> bool:
    """Filters headers to focus on key identifiers (e.g., ID, Code, Number, Key, Ref)."""
    patterns = [r'.*id$', r'.*key$', r'.*num$', r'.*number$', r'.*code$', r'.*ref$']
    return any(re.match(p, normalized_key) for p in patterns)


def build_workbook_graph(
    analyzed_regions: List[Tuple[TableRegion, RegionAnalysisResult]]
) -> WorkbookGraph:
    """Phase 7 Entrypoint: Scans headers across all tables to build cross-sheet relationships."""
    
    nodes: Dict[str, str] = {}
    key_to_regions: Dict[str, List[Tuple[str, str, List[Any]]]] = {}

    # 1. Index all columns and candidate keys across all regions
    for region, analysis in analyzed_regions:
        nodes[region.region_id] = analysis.table_name
        headers = analysis.flat_headers
        data_rows = region.grid_values[analysis.data_start_index:]

        for c_idx, raw_header in enumerate(headers):
            if not raw_header:
                continue
            
            norm_key = _normalize_key(raw_header)
            
            # Extract sample values in this column to assess cardinality
            col_vals = [
                str(row[c_idx]).strip() 
                for row in data_rows 
                if c_idx < len(row) and row[c_idx] is not None and str(row[c_idx]).strip()
            ]

            if _is_id_candidate(norm_key) or norm_key == _normalize_key(analysis.group_by_column or ""):
                key_to_regions.setdefault(norm_key, []).append((region.region_id, analysis.table_name, col_vals))

    edges: List[TableRelationship] = []
    seen_edges: Set[Tuple[str, str, str]] = set()

    # 2. Match identical key columns across distinct tables
    for norm_key, occurrences in key_to_regions.items():
        if len(occurrences) < 2:
            continue  # Key only exists in 1 table

        for i in range(len(occurrences)):
            for j in range(i + 1, len(occurrences)):
                r1_id, t1_name, vals1 = occurrences[i]
                r2_id, t2_name, vals2 = occurrences[j]

                edge_pair_key = tuple(sorted([r1_id, r2_id])) + (norm_key,)
                if edge_pair_key in seen_edges:
                    continue
                seen_edges.add(edge_pair_key)

                # Determine Cardinality based on uniqueness of values
                unique_v1 = len(set(vals1)) == len(vals1) if vals1 else False
                unique_v2 = len(set(vals2)) == len(vals2) if vals2 else False

                if unique_v1 and not unique_v2:
                    source_id, source_table = r1_id, t1_name
                    target_id, target_table = r2_id, t2_name
                    cardinality = "ONE_TO_MANY"
                elif not unique_v1 and unique_v2:
                    source_id, source_table = r2_id, t2_name
                    target_id, target_table = r1_id, t1_name
                    cardinality = "ONE_TO_MANY"
                elif unique_v1 and unique_v2:
                    source_id, source_table = r1_id, t1_name
                    target_id, target_table = r2_id, t2_name
                    cardinality = "ONE_TO_ONE"
                else:
                    source_id, source_table = r1_id, t1_name
                    target_id, target_table = r2_id, t2_name
                    cardinality = "MANY_TO_MANY"

                edges.append(TableRelationship(
                    source_region_id=source_id,
                    target_region_id=target_id,
                    source_table=source_table,
                    target_table=target_table,
                    shared_key=norm_key,
                    cardinality=cardinality
                ))

    return WorkbookGraph(nodes=nodes, edges=edges)


def enrich_chunks_with_graph(
    chunks: List[RAGChunk], 
    graph: WorkbookGraph
) -> List[RAGChunk]:
    """Injects cross-table graph edges into chunk metadata for downstream vector/graph query expansion."""
    
    # Map region_id -> list of related table links
    region_links: Dict[str, List[Dict[str, str]]] = {}
    for edge in graph.edges:
        link_for_src = {
            "related_table": edge.target_table,
            "join_key": edge.shared_key,
            "cardinality": edge.cardinality
        }
        link_for_tgt = {
            "related_table": edge.source_table,
            "join_key": edge.shared_key,
            "cardinality": edge.cardinality
        }
        region_links.setdefault(edge.source_region_id, []).append(link_for_src)
        region_links.setdefault(edge.target_region_id, []).append(link_for_tgt)

    # Attach to chunk metadata
    for chunk in chunks:
        region_id = chunk.metadata.get("region_id")
        if region_id and region_id in region_links:
            chunk.metadata["graph_relationships"] = region_links[region_id]

    return chunks