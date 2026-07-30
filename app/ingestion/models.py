from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
from enum import Enum

@dataclass
class SheetData:
    name: str
    is_hidden: bool
    merged_ranges: List[str]  # e.g., ["A1:C1", "E5:E12"]
    hidden_rows: List[int]
    hidden_cols: List[str]
    has_charts: bool
    comments: Dict[str, str]  # Cell coordinate -> comment text (e.g., {"B2": "Pending audit"})
    grid_values: List[List[Any]]  # Evaluated cell values
    grid_formulas: List[List[Optional[str]]]  # Formula strings if present


@dataclass
class WorkbookData:
    filename: str
    sheets: List[SheetData]

class TableRelationship(BaseModel):
    source_region_id: str
    target_region_id: str
    source_table: str
    target_table: str
    shared_key: str
    cardinality: str  # "ONE_TO_MANY", "ONE_TO_ONE", or "MANY_TO_MANY"

class WorkbookGraph(BaseModel):
    nodes: Dict[str, str]  # region_id -> table_name
    edges: List[TableRelationship]

@dataclass
class TableRegion:
    sheet_name: str
    region_id: str                          # e.g. "Sheet1_Region_0"
    bounding_box: Tuple[int, int, int, int] # (min_row, min_col, max_row, max_col) 0-indexed
    grid_values: List[List[Any]]            # Normalized 2D array of just this region
    formulas: List[List[Optional[str]]]     # Formulas in this region
    comments: Dict[str, str]                # Cell comments mapped to region coordinates

class ChunkStrategy(str, Enum):
    ROW_BASED = "row_based"          # Standalone independent records (1 chunk per row)
    ENTITY_BASED = "entity_based"    # Multi-line items grouped by entity ID/name column
    MATRIX = "matrix"                # Financial grids/P&L statements with 2D intersecting headers
    WHOLE_TABLE = "whole_table"      # Small KPI summary tables or metadata blocks (1 chunk for entire table)


class RegionAnalysisResult(BaseModel):
    table_name: str = Field(description="Short descriptive name or title for this table region")
    entity_type: str = Field(description="Primary business entity, e.g., 'Patient', 'Insurance Claim', 'Refund'")
    header_row_index: int = Field(default=0, description="0-based row index *within this region grid* where column headers live")
    data_start_index: int = Field(default=1, description="0-based row index *within this region grid* where actual data rows start")
    chunk_strategy: ChunkStrategy = Field(default=ChunkStrategy.ROW_BASED, description="Best chunking approach")
    group_by_column: Optional[str] = Field(default=None, description="Exact string name of column to group by if chunk_strategy is entity_based")
    relationships: List[str] = Field(default_factory=list, description="Foreign keys or links to other tables (e.g. ['Patient ID', 'Invoice #'])")
    summary: str = Field(default="", description="1-2 sentence business description of what data this table contains")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Model confidence score between 0.0 and 1.0")
    flat_headers: List[str] = Field(default_factory=list, description="Reconstructed flat headers")

class RAGChunk(BaseModel):
    chunk_id: str
    content: str                  # Text to be embedded & searched
    metadata: Dict[str, Any]      # Source provenance for retrieval/filtering


class ChunkStrategy(str, Enum):
    ENTITY = "entity"
    TABLE = "table"
    MATRIX = "matrix"
    PIVOT = "pivot"
    SUMMARY = "summary"
    FORM = "form"
    CALENDAR = "calendar"
    LEDGER = "ledger"
    ROW = "row"  # General fallback

class EnhancedChunkMetadata(BaseModel):
    # Location & Provenance
    file_name: str
    sheet_name: str
    bounding_box: Dict[str, int]  # {"min_row": 2, "max_row": 30, "min_col": 1, "max_col": 6}
    cell_range: str               # "B3:G31"

    # Structure & Domain
    table_name: str
    entity_type: str
    chunk_strategy: str
    entity_id: Optional[str] = None

    # Grid Dimensions
    row_count: int
    column_count: int
    columns: List[str]

    # Quality & Context
    confidence_score: float
    business_context: str

    # Graph Relationships (Phase 7)
    relationships: List[Dict[str, str]] = []

class ChartSeries(BaseModel):
    title: str
    categories: List[Any]  # X-axis values / labels
    values: List[Any]      # Y-axis numerical values

class ExtractedChart(BaseModel):
    chart_id: str
    sheet_name: str
    title: str
    chart_type: str        # e.g., "line", "bar", "pie", "scatter"
    x_axis_title: Optional[str] = None
    y_axis_title: Optional[str] = None
    series: List[ChartSeries]
    bounding_box: Optional[Dict[str, int]] = None