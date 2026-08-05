"""
Core RAG service using pgvector.
Handles: document ingestion → chunking → embedding → PostgreSQL storage → retrieval
"""
import os
import re
import json
import redis
import pandas as pd
import openpyxl
from openpyxl.utils import range_boundaries
from datetime import datetime
from typing import List, Optional
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

# ── Client ─────────────────────────────────────────────────────────────────────
client = OpenAI(
    base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
    api_key=os.getenv("OPENAI_API_KEY", "ollama"),
)
LLM_MODEL = os.getenv("LLM_MODEL", "mistral:7b")

# ── Constants ──────────────────────────────────────────────────────────────────
CHUNK_SIZE         = 500
CHUNK_OVERLAP      = 100
TOP_K              = 5
EMBED_MODEL        = "all-MiniLM-L6-v2"
MIN_SCORE_STANDARD = 0.45
MIN_SCORE_TABULAR  = 0.25

# ── Plan config ────────────────────────────────────────────────────────────────
PLAN_CONFIG = {
    "free": {
        "monthly_searches":   50,
        "use_hyde":           True,
        "use_multiquery":     True,
        "rate_per_minute":    3,
        "rate_per_hour":      20,
        "price_monthly":      0,
        "price_yearly":       0,
        "display_name":       "Free",
        "max_businesses":     1,
        "max_users":          2,
        "max_organizations":  1,
        "max_rows":           500,
        "max_file_mb":        5,
    },
    "starter": {
        "monthly_searches":   2000,
        "use_hyde":           True,
        "use_multiquery":     True,
        "rate_per_minute":    10,
        "rate_per_hour":      100,
        "price_monthly":      49,
        "price_yearly":       470,
        "display_name":       "Starter",
        "max_businesses":     3,
        "max_users":          10,
        "max_organizations":  1,
        "max_rows":           1000,
        "max_file_mb":        10,
    },
}

# ── Redis ──────────────────────────────────────────────────────────────────────
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=0,
    decode_responses=True,
)

ACTIVE_QUERY_TTL_SECONDS = 60 * 60 * 6  # 6 hours

# ── Singleton embedder ─────────────────────────────────────────────────────────
_embedder = None

def extract_spreadsheet_to_text(file_path: str) -> str:
    sheet_texts = []
    
    try:
        wb = openpyxl.load_workbook(file_path, data_only=True)
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            if ws._charts:
                sheet_texts.append(f"=== SHEET: {sheet_name} (Charts) ===\n")
                for i, chart in enumerate(ws._charts, 1):
                    chart_type = type(chart).__name__
                    title = getattr(chart, 'title', None)
                    title_str = title.text if title and hasattr(title, 'text') else str(title or "Untitled")
                    sheet_texts.append(f"- Chart {i}: Type={chart_type}, Title='{title_str}'\n")
                sheet_texts.append("\n")
    except Exception as e:
        print(f"[Spreadsheet] Chart extraction warning: {e}")

    excel_data = pd.ExcelFile(file_path)
    for sheet_name in excel_data.sheet_names:
        df = pd.read_excel(excel_data, sheet_name=sheet_name, header=None)
        sheet_texts.append(f"--- Data Grid for {sheet_name} ---\n")
        sheet_texts.append(df.to_string(na_rep="", index=True, header=True))
        sheet_texts.append("\n\n")
        
    return "".join(sheet_texts)

def chunk_table_deterministically(file_path: str, table_meta: dict) -> list[str]:
    table_name  = table_meta.get("table_name", "Unknown Table")
    cell_range  = table_meta.get("cell_range", "")
    headers     = table_meta.get("column_headers", [])
    description = table_meta.get("description", "")
    
    try:
        excel_file = pd.ExcelFile(file_path)
        df_full = pd.read_excel(excel_file, sheet_name=excel_file.sheet_names[0], header=None)
    except Exception as e:
        print(f"[Chunker] Error reading excel file for chunking: {e}")
        return []
    
    df_slice = df_full
    if cell_range:
        try:
            min_col, min_row, max_col, max_row = range_boundaries(cell_range)
            df_slice = df_full.iloc[min_row-1:max_row, min_col-1:max_col]
        except Exception:
            pass
            
    context_prefix = f"[Table: {table_name}]\nDescription: {description}\nHeaders: {', '.join(headers)}\n---"
    
    row_chunks = []
    header_set = {str(h).strip().lower() for h in headers if pd.notna(h)}

    for _, row in df_slice.iterrows():
        # Check if this row is actually just repeating the column headers
        row_values = [str(val).strip().lower() for val in row.values if pd.notna(val)]
        if header_set and row_values:
            # If most values in this row match the header names, it's a header row — skip it!
            matches = sum(1 for v in row_values if v in header_set)
            if matches >= len(header_set) * 0.6:  # 60% match threshold
                continue

        row_str = " | ".join([
            f"{headers[i]}: {val}" if i < len(headers) and pd.notna(val) else str(val) 
            for i, val in enumerate(row.values) if pd.notna(val)
        ])
        
        if row_str.strip():
            chunk_text = f"{context_prefix}\nRow Data: {row_str}"
            row_chunks.append(chunk_text)
            
    print(f"[Chunker] Generated {len(row_chunks)} valid row chunks for table '{table_name}' (skipped headers)")
    return row_chunks

def analyze_spreadsheet_with_llm(file_path: str, client: OpenAI = None) -> dict:
    if client is None:
        client = OpenAI()

    spreadsheet_text = extract_spreadsheet_to_text(file_path)
    print(f"[Spreadsheet LLM] Extracted text length: {len(spreadsheet_text)} chars from {file_path}")

    prompt = f"""
You are an expert data extraction and spreadsheet analysis assistant. Your task is to analyze the provided spreadsheet data (sheet names, cell contents, or structural text dumps) and identify the logical structure of the workbook.

Your goal is to detect:
- All distinct tables (even if they are not formatted as Excel Tables).
- The cell range occupied by each table.
- The column headers for each table.
- Any charts or visualizations.
- Important summary metrics or findings.

Return your response as a single, valid JSON object and nothing else. Do not include markdown code blocks (such as json), explanations, or conversational text.

The JSON object must strictly conform to the following schema:
{{
  "spreadsheet_summary": "A brief overview of the workbook contents.",
  "tables": [
    {{
      "table_name": "Name or inferred title of the table",
      "cell_range": "e.g., A1:D15",
      "column_headers": ["Header1", "Header2"],
      "description": "Brief description of the table contents"
    }}
  ],
  "charts": [
    {{
      "chart_name": "Name or inferred title of the chart",
      "chart_type": "e.g., Bar, Line, Pie",
      "location_or_range": "Cell location if identifiable",
      "description": "Brief description of what the chart visualizes"
    }}
  ],
  "key_findings": [
    "Notable data insight or summary total"
  ]
}}

Analyze the following spreadsheet content:
{spreadsheet_text}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a precise data extraction assistant that outputs strictly valid JSON objects."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    )

    raw_content = response.choices[0].message.content
    print(f"[Spreadsheet LLM] Raw JSON response received (first 300 chars): {raw_content[:300]}...")

    try:
        parsed_data = json.loads(raw_content)
        print(f"[Spreadsheet LLM] Parsed successfully -> Tables found: {len(parsed_data.get('tables', []))}, Charts found: {len(parsed_data.get('charts', []))}")
        return parsed_data
    except Exception as e:
        print(f"[Spreadsheet LLM] JSON parse error: {e}. Raw content was: {raw_content}")
        return {"tables": [], "charts": [], "key_findings": [], "spreadsheet_summary": ""}
    
def analyze_sheet_structure(
    raw_rows: list,
    sheet_name: str,
    filename: str,
    user_context: Optional[str] = None,
) -> dict:
    """
    Sends raw rows (as CSV text) to the LLM and asks it to identify:
      - Where the real header row is
      - Whether there are multiple tables
      - What each table represents
      - Which columns are IDs vs dollar amounts vs dates
 
    Returns a dict the ingestion code uses to read the file correctly.
    """
    # Convert raw rows to readable CSV-ish text (max 30 rows to stay within tokens)
    row_lines = []
    for i, row in enumerate(raw_rows[:30]):
        vals = [str(v) if pd.notna(v) else "" for v in row]
        row_lines.append(f"Row {i}: {' | '.join(vals)}")
    raw_sample = "\n".join(row_lines)
 
    prompt = f"""You are analyzing a raw Excel sheet to prepare it for ingestion into a vector search database.
 
Filename: {filename}
Sheet: {sheet_name}
User context: {user_context or 'None provided'}
 
Raw sheet content (first 30 rows, zero-indexed):
{raw_sample}
 
Analyze this sheet and respond with ONLY valid JSON — no markdown, no explanation.
 
Return this exact structure:
{{
  "tables": [
    {{
      "sheet_name": "Name of the Excel tab/sheet",
      "table_name": "descriptive name for this table",
      "header_row": 0,
      "data_start_row": 1,
      "data_end_row": null,
      "description": "what each row represents in plain english",
      "column_notes": {{
        "ColumnName": "what this column contains — flag if it is an ID/reference not a dollar amount"
      }},
      "disambiguation": "any important notes to prevent the LLM from confusing columns e.g. Statement Number is a bill ID not a dollar amount"
    }}
  ],
  "skip_rows": [],
  "structural_notes": "any other important layout notes"
}}
 
Rules:
- header_row is the zero-based row index where the REAL column headers are
- data_start_row is the first row of actual data (usually header_row + 1)
- data_end_row is null if data goes to the end, otherwise the last data row index
- skip_rows lists row indices that are metadata/totals/blank — NOT real data
- If there are multiple separate tables on the same sheet, list each one
- If all columns are unnamed, set header_row to the row with the most descriptive text
- IMPORTANT: Identify columns that look like amounts/money vs ID numbers"""
 
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,  # low temp — we want structured reliable output
            max_tokens=800,
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        print(f"[LLM Structure] {sheet_name}: {len(result.get('tables', []))} table(s) detected")
        return result
    except Exception as e:
        print(f"[LLM Structure] Failed for {sheet_name}: {e} — using fallback detection")
        return None
 
 
def fallback_detect_header(df_raw: pd.DataFrame) -> int:
    """Score-based header detection when LLM fails."""
    best_score = 0
    best_row   = 0
    for i in range(min(20, len(df_raw))):
        row_vals = df_raw.iloc[i].tolist()
        score = sum(
            1 for v in row_vals
            if isinstance(v, str)
            and len(v.strip()) > 1
            and not v.strip().replace(".", "").replace(",", "").replace("-", "").isnumeric()
        )
        # Penalize if first cell looks like a date
        first = str(row_vals[0]) if row_vals else ""
        if any(yr in first for yr in ["2020", "2021", "2022", "2023", "2024", "2025", "2026"]):
            score -= 3
        if score > best_score:
            best_score = score
            best_row   = i
    return best_row
 
def chunk_text_small_to_big(text: str) -> List[dict]:
    """
    Returns list of {child, parent} dicts.
    Child = small sentence-level chunk for embedding.
    Parent = surrounding paragraph for LLM context.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    # Step 1: Split into large parent chunks (paragraphs)
    parent_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=0,        # no overlap at parent level
        separators=["\n\n\n", "\n\n", "\n"],
    )
    parents = parent_splitter.split_text(text)

    # Step 2: Split each parent into small child chunks
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=150,
        chunk_overlap=0,        # no overlap at child level either
        separators=[".\n", ". ", "! ", "? ", "\n", " "],
    )

    result = []
    for parent in parents:
        children = child_splitter.split_text(parent)
        for child in children:
            if child.strip():
                result.append({
                    "child":  child.strip(),
                    "parent": parent.strip(),
                })

    return result

def normalize_parent_key(text: str) -> str:
    """
    Normalizes text by removing section/appendix headers and taking a middle-sample 
    fingerprint so identical repeated blocks match without false positives.
    """
    # Remove dynamic headers
    cleaned = re.sub(r'Appendix\s+\d+', '', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'Section\s+\d+', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\W+', '', cleaned).lower()
    
    # Use a longer fingerprint (first 300 chars) to prevent false-positive collisions
    return cleaned[:300]

def extract_table_from_structure(
    df_raw: pd.DataFrame,
    table_spec: dict,
    sheet_name: str,
) -> tuple[str, pd.DataFrame, str, str]:
    """
    Uses the LLM-provided table spec to correctly slice and header the DataFrame.
    Returns (table_name, clean_df, description, disambiguation).
    """
    header_row     = table_spec.get("header_row", 0)
    data_start     = table_spec.get("data_start_row", header_row + 1)
    data_end       = table_spec.get("data_end_row", None)
    table_name     = table_spec.get("table_name", sheet_name)
    description    = table_spec.get("description", "")
    disambiguation = table_spec.get("disambiguation", "")
    skip_rows      = table_spec.get("skip_rows", [])
 
    # Extract header from the identified row
    headers = df_raw.iloc[header_row].tolist()
    headers = [
        str(h).replace("\n", " ").strip() if pd.notna(h) else f"Column_{i}"
        for i, h in enumerate(headers)
    ]
 
    # Slice data rows
    if data_end is not None:
        df_data = df_raw.iloc[data_start:data_end + 1].copy()
    else:
        df_data = df_raw.iloc[data_start:].copy()
 
    df_data.columns = headers
 
    # Drop skip rows (adjust index since we sliced)
    adjusted_skips = [r - data_start for r in skip_rows if data_start <= r < (data_end or len(df_raw))]
    if adjusted_skips:
        df_data = df_data.drop(index=adjusted_skips, errors="ignore")
 
    # Drop unnamed columns
    df_data = df_data[[c for c in df_data.columns if not str(c).startswith("Unnamed:") and str(c).strip() not in ("", "nan")]]
 
    # Drop fully empty rows
    df_data = df_data.dropna(how="all").reset_index(drop=True)
 
    return table_name, df_data, description, disambiguation
 
 
def build_schema_chunk(
    table_name: str,
    df: pd.DataFrame,
    filename: str,
    description: str,
    disambiguation: str,
    user_context: Optional[str],
    column_notes: dict,
) -> str:
    """Builds the schema header chunk (chunk_index=0 for this table)."""
    sample_lines = []
    for col in df.columns:
        samples = (
            df[col].dropna().astype(str).str.strip()
            .loc[lambda s: s != ""].unique()[:3].tolist()
        )
        note = column_notes.get(col, "")
        flag = f" [{note}]" if note else ""
        sample_lines.append(
            f"  - {col}{flag}: e.g. {', '.join(samples)}" if samples else f"  - {col}{flag}"
        )
 
    parts = [
        f"[Table: {table_name}]",
        f"Source file: {filename}",
    ]
    if description:
        parts.append(f"Description: {description}")
    if user_context:
        parts.append(f"User notes: {user_context}")
    parts.append(f"Rows: {len(df)} | Columns: {len(df.columns)}")
    parts.append("Columns and sample values:\n" + "\n".join(sample_lines))
    if disambiguation:
        parts.append(f"\nIMPORTANT — Column disambiguation:\n{disambiguation}")
 
    return "\n".join(parts)

def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        print("Loading embedding model... (first time only)")
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder


# ── Search quota ───────────────────────────────────────────────────────────────
def get_monthly_search_count(org_id: int) -> int:
    key = f"searches:org:{org_id}:{datetime.now().strftime('%Y-%m')}"
    try:
        val = redis_client.get(key)
        return int(val) if val else 0
    except Exception:
        return 0

def increment_search_count(org_id: int) -> int:
    key = f"searches:org:{org_id}:{datetime.now().strftime('%Y-%m')}"
    try:
        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60 * 60 * 24 * 35)  # 35 days
        count, _ = pipe.execute()
        return count
    except Exception:
        return 0

def check_search_limit(org_id: int, plan: str) -> tuple[bool, int, int]:
    """Returns (allowed, current_count, limit)"""
    config  = PLAN_CONFIG.get(plan, PLAN_CONFIG["free"])
    limit   = config["monthly_searches"]
    current = get_monthly_search_count(org_id)
    return current < limit, current, limit


# ── Rate limiting ──────────────────────────────────────────────────────────────
def check_rate_limit(user_id: int, plan: str) -> bool:
    """Returns True if allowed, False if rate limited."""
    config      = PLAN_CONFIG.get(plan, PLAN_CONFIG["free"])
    minute_key  = f"rate:{user_id}:minute"
    hour_key    = f"rate:{user_id}:hour"
    try:
        pipe = redis_client.pipeline()
        pipe.incr(minute_key)
        pipe.expire(minute_key, 60)
        pipe.incr(hour_key)
        pipe.expire(hour_key, 3600)
        minute_count, _, hour_count, _ = pipe.execute()
        if minute_count > config["rate_per_minute"]:
            return False
        if hour_count > config["rate_per_hour"]:
            return False
        return True
    except Exception:
        return True  # fail open if Redis is down


# ── Active query cache (per user) ──────────────────────────────────────────────
def normalize_query(query: str) -> str:
    return " ".join(query.lower().strip().split())

def get_active_query_key(user_id: int) -> str:
    return f"active_query:{user_id}"

def get_active_query(user_id: int) -> dict | None:
    try:
        data = redis_client.get(get_active_query_key(user_id))
        if not data:
            return None
        return json.loads(data)
    except Exception:
        return None

def set_active_query(
    user_id: int,
    question: str,
    business_id: int,
    doc_state: dict,
    answers: list,
    retrieval_results: list,
    next_chunk_offset: int | None,
) -> None:
    try:
        redis_client.setex(
            get_active_query_key(user_id),
            ACTIVE_QUERY_TTL_SECONDS,
            json.dumps({
                "question":          normalize_query(question),
                "business_id":       business_id,
                "doc_state":         doc_state,
                "answers":           answers,
                "retrieval_results": retrieval_results,
                "next_chunk_offset": next_chunk_offset,
            }),
        )
    except Exception as e:
        print(f"[Redis] Failed to cache active query: {e}")

def clear_active_query(user_id: int) -> None:
    try:
        redis_client.delete(get_active_query_key(user_id))
    except Exception:
        pass


# ── HyDE ──────────────────────────────────────────────────────────────────────
def generate_hypothetical_answer(query: str) -> str:
    hyde_prompt = f"""You are a search assistant. A user is searching a document database.
Write a SHORT hypothetical passage (2-4 sentences) that would be the ideal answer 
to the following question. Write it as if it were extracted from a real document or table.
Do NOT say "I don't know". Always write a plausible passage.
Do NOT include any explanation — output ONLY the passage itself.

Question: {query}
Passage:"""
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": hyde_prompt}],
            temperature=0.5,
            max_tokens=150,
        )
        hypothetical = response.choices[0].message.content.strip()
        print(f"\n[HyDE] Generated: {hypothetical}")
        return hypothetical
    except Exception as e:
        print(f"[HyDE] Failed, falling back to raw query: {e}")
        return query


def build_hyde_vector(query: str, embedder: SentenceTransformer) -> list:
    import numpy as np
    hypothetical = generate_hypothetical_answer(query)
    vecs         = embedder.encode([query, hypothetical], normalize_embeddings=True)
    avg          = (vecs[0] + vecs[1]) / 2.0
    norm         = np.linalg.norm(avg)
    if norm > 0:
        avg = avg / norm
    return avg.tolist()


# ── Multi-Query HyDE ───────────────────────────────────────────────────────────
def generate_query_variants(query: str) -> List[str]:
    prompt = f"""You are a search query expander for a document retrieval system.
Given a user question, generate 4 alternative search queries that mean the same thing
but use different vocabulary, levels of formality, and domain-specific terms.

Rules:
- Include at least one very specific/technical version
- Include at least one that uses common abbreviations (SOP, PPE, etc.)
- Include one that mimics how a document title or heading might be phrased
- Keep each query under 15 words
- Return ONLY a JSON array of strings, nothing else

User question: {query}
"""
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=200,
        )
        raw      = response.choices[0].message.content.strip()
        raw      = raw.replace("```json", "").replace("```", "").strip()
        variants = json.loads(raw)
        if isinstance(variants, list):
            print(f"\n[MultiQuery] Variants: {variants}")
            return [query] + variants
    except Exception as e:
        print(f"[MultiQuery] Failed, using original query only: {e}")
    return [query]


def build_multi_hyde_vectors(query: str, embedder: SentenceTransformer) -> List[list]:
    import numpy as np
    variants = generate_query_variants(query)
    vectors  = []
    for variant in variants:
        try:
            vectors.append(build_hyde_vector(variant, embedder))
        except Exception as e:
            print(f"[MultiQuery] Skipping variant '{variant}': {e}")
            vectors.append(embedder.encode([variant], normalize_embeddings=True).tolist()[0])
    return vectors


def retrieve_chunks_multi(
    db: Session,
    business_id: int,
    query: str,
    get_k: int,
    offset: int = 0,
    document_ids: List[int] | None = None,
    vectors: list | None = None,
) -> dict:
    embedder = get_embedder()
 
    if vectors is None:
        vectors = build_multi_hyde_vectors(query, embedder)
 
    doc_filter_sql = ""
    base_params    = {
        "business_id":  business_id,
        "min_standard": MIN_SCORE_STANDARD,
        "min_tabular":  MIN_SCORE_TABULAR,
    }
    if document_ids:
        doc_filter_sql         = "AND c.document_id = ANY(:doc_ids)"
        base_params["doc_ids"] = document_ids
 
    rrf_scores: dict = {}
    RRF_K            = 60
 
    for query_vector in vectors:
        params = {
            **base_params,
            "query_vec":      query_vector,
            "limit_plus_one": get_k * 3 + 1,
            "offset":         0,
        }
 
        sql = f"""
WITH scored AS (
    SELECT
        c.id,
        c.text,
        c.parent_text,
        c.chunk_index,
        c.chunk_type,
        c.document_id,
        d.filename,
        1 - (c.embedding <=> CAST(:query_vec AS vector)) AS score
    FROM chunks c
    JOIN documents d
      ON d.id = c.document_id
    WHERE c.business_id = :business_id
    {doc_filter_sql}
),

tabular_headers AS (
    SELECT DISTINCT ON (c.document_id)
        c.id,
        c.text,
        c.parent_text,
        c.chunk_index,
        c.chunk_type,
        c.document_id,
        d.filename,
        1.0 AS score
    FROM chunks c
    JOIN documents d
      ON d.id = c.document_id
    WHERE c.business_id = :business_id
      AND c.chunk_type = 'tabular'
      AND c.chunk_index = 0
      {doc_filter_sql}
      AND c.document_id IN (
            SELECT document_id
            FROM scored
            WHERE chunk_type = 'tabular'
              AND score >= :min_tabular
      )
)

SELECT
    id,
    text,
    parent_text,
    chunk_index,
    chunk_type,
    document_id,
    filename,
    score
FROM (

    SELECT
        id,
        text,
        parent_text,
        chunk_index,
        chunk_type,
        document_id,
        filename,
        score
    FROM scored
    WHERE
        (
            chunk_type = 'tabular'
            AND score >= :min_tabular
        )
        OR
        (
            chunk_type <> 'tabular'
            AND score >= :min_standard
        )

    UNION

    SELECT
        id,
        text,
        parent_text,
        chunk_index,
        chunk_type,
        document_id,
        filename,
        score
    FROM tabular_headers

) combined

ORDER BY score DESC
LIMIT :limit_plus_one
OFFSET :offset
"""
 
        rows = db.execute(text(sql), params).fetchall()
        for rank, row in enumerate(rows):
            chunk_id         = row.id
            rrf_contribution = 1.0 / (rank + 1 + RRF_K)
            if chunk_id not in rrf_scores:
                rrf_scores[chunk_id] = {
                    "text": row.text,
                    "parent_text": row.parent_text,
                    "chunk_type": row.chunk_type,
                    "filename": row.filename,
                    "document_id": row.document_id,
                    "score": row.score,
                    "rrf_score": 0.0,
                }
            rrf_scores[chunk_id]["rrf_score"] += rrf_contribution
 
    # ── Sort by RRF score ──────────────────────────────────────────────────────
    merged = sorted(rrf_scores.values(), key=lambda x: x["rrf_score"], reverse=True)
 
    # ── Deduplicate by parent_text ─────────────────────────────────────────────
    # Multiple child chunks may share the same parent paragraph.
    # Only keep the highest-ranked child per unique parent so the LLM
    # never sees the same paragraph twice — this is what eliminates duplicates.
    seen_parents = set()
    deduped = []

    for r in merged:

    #
    # Spreadsheet pipeline
    #
        STRUCTURED_TYPES = {
            "tabular",
            "table_metadata",
            "workbook_metadata",
            "chart_metadata",
        }

        if r["chunk_type"] in STRUCTURED_TYPES:
            deduped.append({
                "text": r["text"],
                "child_text": r["text"],
                "filename": r["filename"],
                "document_id": r["document_id"],
                "score": float(round(r["score"], 4)),
                "chunk_type": r["chunk_type"],
            })
            continue

    #
    # Text / PDF pipeline
    #
        parent = r.get("parent_text") or r["text"]
        parent_key = parent.strip()[:200]

        if parent_key in seen_parents:
            continue

        seen_parents.add(parent_key)

        deduped.append({
            "text": parent,
            "child_text": r["text"],
            "filename": r["filename"],
            "document_id": r["document_id"],
            "score": float(round(r["score"], 4)),
            "chunk_type": r["chunk_type"],
        })
 
    print(f"\n[MultiQuery] {len(vectors)} variants → {len(merged)} chunks → {len(deduped)} after parent dedup")
    for r in deduped[:8]:
        print(f"  score={r['score']:.4f} | {r['filename']} | {r['text'][:80]}")
 
    has_more = len(deduped) > (offset + get_k)
    page     = deduped[offset: offset + get_k]
 
    return {
        "results":    page,
        "allResults": deduped,   # full deduped list for cache
        "hasMore":    has_more,
        "nextOffset": offset + get_k if has_more else None,
    }



# ── Text extraction ────────────────────────────────────────────────────────────
def extract_text(file_path: str, mime_type: str) -> str:
    path = Path(file_path)
    ext  = path.suffix.lower()

    if ext == ".pdf":
        import fitz
        text = ""
        doc  = fitz.open(path)
        for page in doc:
            for b in page.get_text("blocks"):
                text += b[4] + " "
        doc.close()
        return text

    if ext in [".xlsx", ".xls"]:
        import pandas as pd
        dict_df     = pd.read_excel(path, sheet_name=None)
        text_output = []
        for sheet_name, df in dict_df.items():
            text_output.append(f"Sheet: {sheet_name}\n{df.to_csv(index=False)}")
        return "\n\n".join(text_output)

    if ext == ".csv":
        import pandas as pd
        return pd.read_csv(path).to_csv(index=False)

    if ext == ".docx":
        import docx
        doc = docx.Document(path)
        return "\n".join([p.text for p in doc.paragraphs])

    if ext in [".txt", ".md"]:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    print(f"Unsupported file extension: {ext}")
    return ""


# ── Chunking ───────────────────────────────────────────────────────────────────
def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", " ", ""]
    )
    return splitter.split_text(text)

def clean_text(text: str) -> str:
    return text.replace("\x00", "")


# ── Ingest ─────────────────────────────────────────────────────────────────────
def ingest_document(
    db: Session,
    business_id: int,
    document_id: int,
    file_path: str,
    mime_type: str,
    filename: str,
    file_context: Optional[str] = None,
) -> int:
    from app.models import Chunk
 
    ext      = Path(file_path).suffix.lower()
    embedder = get_embedder()
    chunks_to_add = []
 
    # ── 1. Excel Spreadsheets (.xlsx, .xls) ──────────────────────────────────
    if ext in [".xlsx", ".xls"]:
        try:
            spreadsheet_meta = analyze_spreadsheet_with_llm(file_path)
        except Exception as e:
            print(f"[Ingest] LLM spreadsheet analysis failed for {filename}: {e}")
            spreadsheet_meta = {"tables": [], "charts": [], "key_findings": [], "spreadsheet_summary": ""}

        tables = spreadsheet_meta.get("tables", [])

        # Loop through each detected table and run deterministic row-level chunking
        for table in tables:
            table_chunks = chunk_table_deterministically(file_path, table)
            for chunk_text in table_chunks:
                chunks_to_add.append({
                    "text": chunk_text,
                    "parent": chunk_text
                })

        # FALLBACK: If the LLM returned 0 tables, don't drop the data! Chunk the whole sheet raw.
        if not tables:
            print(f"[Ingest] Warning: LLM detected 0 tables for {filename}. Falling back to full sheet raw ingestion.")
            try:
                df_full = pd.read_excel(file_path, header=None)
                for _, row in df_full.iterrows():
                    row_str = " | ".join([str(val) for val in row.values if pd.notna(val)])
                    if row_str.strip():
                        chunks_to_add.append({"text": row_str, "parent": row_str})
            except Exception as e:
                print(f"[Ingest] Fallback raw ingestion failed: {e}")

        # Package summary, charts, and key findings into a metadata chunk
        summary  = spreadsheet_meta.get("spreadsheet_summary", "")
        charts   = spreadsheet_meta.get("charts", [])
        findings = spreadsheet_meta.get("key_findings", [])
        
        meta_lines = []
        if summary:
            meta_lines.append(f"Workbook Summary: {summary}")
        if charts:
            meta_lines.append("Detected Charts & Visualizations:")
            for c in charts:
                meta_lines.append(f"- {c.get('chart_name')} ({c.get('chart_type')} at {c.get('location_or_range')}): {c.get('description')}")
        if findings:
            meta_lines.append("Key Findings & Insights:")
            for f in findings:
                meta_lines.append(f"- {f}")
                
        if meta_lines:
            meta_text = "\n".join(meta_lines)
            chunks_to_add.append({
                "text": meta_text,
                "parent": meta_text
            })

    # ── 2. CSV Files (.csv) ──────────────────────────────────────────────────
    elif ext == ".csv":
        df = pd.read_csv(file_path)
        csv_text = df.to_string(index=False)
        chunks_to_add.append({
            "text": csv_text,
            "parent": csv_text
        })

    # ── 3. Handle Embedding & Saving for Spreadsheets / CSVs ─────────────────
    if ext in [".csv", ".xlsx", ".xls"]:
        print(f"[Ingest] Total spreadsheet/CSV chunks ready to embed and save: {len(chunks_to_add)}")
        if not chunks_to_add:
            print(f"[Ingest] Error: 0 chunks generated for {filename}")
            return 0
        
        child_texts = [c["text"] for c in chunks_to_add]
        embeddings = embedder.encode(
            child_texts, show_progress_bar=False, normalize_embeddings=True
        ).tolist()

        db.add_all([
            Chunk(
                business_id=business_id,
                document_id=document_id,
                chunk_index=i,
                text=c["text"],
                parent_text=c["parent"],
                chunk_type="child",
                embedding=embedding,
            )
            for i, (c, embedding) in enumerate(zip(chunks_to_add, embeddings))
        ])
        db.commit()
        print(f"[Ingest] Successfully committed {len(chunks_to_add)} chunks for {filename}")
        return len(chunks_to_add)

    # ── 4. Fallback for Standard Text / PDFs ─────────────────────────────────
    else:
        raw_text = extract_text(file_path, mime_type)
        raw_text = clean_text(raw_text)
        if not raw_text:
            return 0

        pairs = chunk_text_small_to_big(raw_text)
        if not pairs:
            return 0

        child_texts = [p["child"] for p in pairs]
        embeddings  = embedder.encode(
            child_texts, show_progress_bar=False, normalize_embeddings=True
        ).tolist()

        db.add_all([
            Chunk(
                business_id=business_id,
                document_id=document_id,
                chunk_index=i,
                text=p["child"],          
                parent_text=p["parent"],  
                chunk_type="child",
                embedding=embedding,
            )
            for i, (p, embedding) in enumerate(zip(pairs, embeddings))
        ])
        db.commit()
        return len(pairs)



# ── Retrieval (single HyDE) ────────────────────────────────────────────────────
def retrieve_chunks(
    db: Session,
    business_id: int,
    query: str,
    get_k: int = TOP_K,
    offset: int = 0,
    document_ids: List[int] | None = None,
    use_hyde: bool = True,
) -> dict:
    embedder = get_embedder()

    if use_hyde:
        query_vector = build_hyde_vector(query, embedder)
    else:
        query_vector = embedder.encode([query], normalize_embeddings=True).tolist()[0]

    params = {
        "query_vec":      query_vector,
        "business_id":    business_id,
        "min_standard":   MIN_SCORE_STANDARD,
        "min_tabular":    MIN_SCORE_TABULAR,
        "limit_plus_one": get_k + 1,
        "offset":         offset,
    }

    doc_filter_sql = ""
    if document_ids:
        doc_filter_sql = "AND c.document_id = ANY(:doc_ids)"
        params["doc_ids"] = document_ids

    sql = f"""
            WITH scored AS (
                SELECT
                    c.id, c.text, c.parent_text, c.chunk_index, c.document_id, d.filename,
                    1 - (c.embedding <=> CAST(:query_vec AS vector)) AS score,
                    (c.text LIKE '[Table:%%')
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.business_id = :business_id
                {doc_filter_sql}
            ),
            tabular_headers AS (
                SELECT DISTINCT ON (c.document_id)
                    c.id, c.text, c.parent_text, c.chunk_index, c.document_id, d.filename,
                    1.0 AS score, TRUE
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.business_id = :business_id
                  AND c.chunk_index = 0
                  AND c.chunk_type = 'tabular'
                  {doc_filter_sql}
                  AND c.document_id IN (
                      SELECT document_id FROM scored
                      WHERE chunk_type = 'tabular' AND score >= :min_tabular
                  )
            )
            SELECT id, text, parent_text, chunk_index, document_id, filename, score
            FROM (
                SELECT id, text, parent_text, chunk_index, document_id, filename, score
                FROM scored
                WHERE
                    (
                        chunk_type = 'tabular'
                        AND score >= :min_tabular
                    )
                    OR
                    (
                        chunk_type <> 'tabular'
                        AND score >= :min_standard
                    )
                UNION
                SELECT id, text, parent_text, chunk_index, document_id, filename, score
                FROM tabular_headers
            ) combined
            ORDER BY score DESC
            LIMIT :limit_plus_one
            OFFSET :offset
        """

    results  = db.execute(text(sql), params).fetchall()
    has_more = len(results) > get_k
    results  = results[:get_k]

    return {
        "results": [
            {
                "text":        row.text,
                "filename":    row.filename,
                "document_id": row.document_id,
                "score":       float(round(row.score, 4)),
            }
            for row in results
        ],
        "hasMore":    has_more,
        "nextOffset": offset + get_k if has_more else None,
    }


# ── Delete ─────────────────────────────────────────────────────────────────────
def delete_document_chunks(db: Session, document_id: int) -> None:
    from app.models import Chunk
    db.query(Chunk).filter(Chunk.document_id == document_id).delete()
    db.commit()