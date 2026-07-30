import json
import os
from openai import OpenAI
from .models import RegionAnalysisResult, TableRegion
from .validators import validate_and_sanitize_analysis

LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
client = OpenAI()

def _align_group_by_column(group_by: Optional[str], flat_headers: List[str]) -> Optional[str]:
    """Ensures group_by_column matches an exact normalized header string."""
    if not group_by or not flat_headers:
        return None
    
    # 1. Exact Match
    if group_by in flat_headers:
        return group_by
        
    # 2. Case-insensitive / Partial Match
    group_by_clean = group_by.lower().strip()
    for h in flat_headers:
        if group_by_clean in h.lower():
            return h
            
    return flat_headers[0] if flat_headers else None

def _build_preview_text(region: TableRegion, max_preview_rows: int = 7) -> str:
    """Formats top N rows of a region into a line-numbered string preview."""
    preview_lines = []

    for r_idx, row in enumerate(region.grid_values[:max_preview_rows]):
        cells = [
            f"Col {c_idx}: {str(val).replace('\n', ' ')}" 
            for c_idx, val in enumerate(row) 
            if val is not None and str(val).strip() != ""
        ]
        if cells:
            preview_lines.append(f"Row {r_idx}: " + " | ".join(cells))

    if region.comments:
        comment_strs = [f"{coord}: {txt}" for coord, txt in region.comments.items()]
        preview_lines.append("\nCell Comments:\n" + "\n".join(comment_strs))

    return "\n".join(preview_lines)


SYSTEM_PROMPT = """You are an expert spreadsheet analysis assistant.
Your task is to analyze a isolated grid snippet from an Excel workbook and classify its structure for vector indexing.

Analyze the grid sample and classify it into EXACTLY ONE of these 8 strategies:

1. ENTITY: Multi-row records grouped under a shared primary identifier (e.g., Invoice # with line items, Patient ID with medical visits).
2. TABLE: Standard relational row-and-column table where each row is an independent entry.
3. MATRIX: 2D cross-tab grid where row labels intersect with column headers (e.g., financial models, rate grids, P&L statements).
4. PIVOT: Aggregated table containing multi-level headers, grouped dimensions, sub-totals, or grand totals.
5. SUMMARY: Executive dashboard cards, KPI callout blocks, or high-level metric summaries.
6. FORM: Key-value pair intake layouts, forms, or vertical attribute lists (e.g., Patient Name: John, DOB: 01/01/1990).
7. CALENDAR: Temporal/schedule grids with days or time slots along axes and events/shifts in cells.
8. LEDGER: Sequential financial transaction logs featuring running balances, debits, credits, or dates.

Return ONLY valid JSON with this exact schema:
{
  "title": "<Short descriptive name for the table>",
  "entity": "<Primary entity type, e.g., Patient, Invoice, Metric>",
  "header_row": <0-indexed row number containing headers>,
  "data_start": <0-indexed row number where data starts>,
  "chunk_strategy": "<ENTITY | TABLE | MATRIX | PIVOT | SUMMARY | FORM | CALENDAR | LEDGER>",
  "entity_key": "<Header name used for grouping, required ONLY if strategy is ENTITY>",
  "relationships": ["<Associated entity or table names>"],
  "summary": "<1-2 sentence description of table contents>",
  "confidence": <Float between 0.0 and 1.0>
}
"""


def analyze_region(
    region: TableRegion,
    filename: str = "",
    file_context: str = "",
    llm_client: Any = None  # Your OpenAI/Anthropic client instance
) -> RegionAnalysisResult:
    """Phase 3: Prompts LLM to analyze region structure and passes output to Phase 5 validation."""
    
    # Send up to the first 10 rows as a lightweight representation
    grid_sample = region.grid_values[:10]
    
    user_prompt = f"""
    Context:
    - File: {filename}
    - Sheet: {region.sheet_name}
    - Bounding Box: {region.bounding_box}
    - Document Context: {file_context}

    Grid Sample:
    {json.dumps(grid_sample, indent=2)}
    """

    try:
        # Replace this block with your actual LLM API call (OpenAI, Anthropic, etc.)
        response = llm_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0
        )
        raw_json = json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"[Phase 3 Exception] LLM call failed for {region.region_id}: {e}")
        raw_json = {"confidence": 0.0}

    # Phase 5 Validation Airlock
    return validate_and_sanitize_analysis(raw_json, region)
    
import re
from typing import Any, List


def flatten_and_normalize_headers(
    grid_values: List[List[Any]], 
    header_start_idx: int, 
    data_start_idx: int
) -> List[str]:
    """Reconstructs single-tier or multi-tier headers into clean composite header strings.
    
    Example input:
        Row 1: ['Patient Info', 'Patient Info', 'January', 'January']
        Row 2: ['ID',           'Name',         'Charge',  'Payment']
        
    Output:
        ['Patient Info ID', 'Patient Info Name', 'January Charge', 'January Payment']
    """
    if not grid_values or header_start_idx >= len(grid_values):
        return []

    num_cols = len(grid_values[0])
    
    # If header and data start at the same row (no explicit headers found), generate defaults
    if header_start_idx >= data_start_idx:
        return [f"Column_{c_idx + 1}" for c_idx in range(num_cols)]

    header_rows = grid_values[header_start_idx:data_start_idx]
    final_headers: List[str] = []

    for c_idx in range(num_cols):
        cell_parts: List[str] = []
        
        for r in header_rows:
            val = r[c_idx]
            if val is not None:
                cleaned_str = str(val).strip()
                # Ignore placeholders like 'Unnamed: 0' or empty strings
                if cleaned_str and not re.match(r"^unnamed:?\s*\d*$", cleaned_str, re.IGNORECASE):
                    # Avoid repeating identical words stacked on top of each other
                    if not cell_parts or cell_parts[-1].lower() != cleaned_str.lower():
                        cell_parts.append(cleaned_str)

        # Build composite string or assign fallback if completely empty
        if cell_parts:
            combined_header = " ".join(cell_parts)
            # Sanitize whitespace (e.g. multiple spaces, tabs, newlines)
            combined_header = re.sub(r"\s+", " ", combined_header)
            final_headers.append(combined_header)
        else:
            final_headers.append(f"Column_{c_idx + 1}")

    # Handle duplicate header names by appending _1, _2 suffix
    seen_names = {}
    deduped_headers = []
    for h in final_headers:
        if h in seen_names:
            seen_names[h] += 1
            deduped_headers.append(f"{h}_{seen_names[h]}")
        else:
            seen_names[h] = 0
            deduped_headers.append(h)

    return deduped_headers

