"""
Core RAG service using pgvector.
Handles: document ingestion → chunking → embedding → PostgreSQL storage → retrieval
"""
import io
import os
import re
import json
import redis
import pandas as pd
from app.models import Chunk
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
        "monthly_searches": 50,
        "use_hyde":         True,
        "use_multiquery":   True,
        "rate_per_minute":  3,
        "rate_per_hour":    20,
        "price_monthly":    0,
        "price_yearly":     0,
        "display_name":     "Free",
        "max_businesses":   1,
        "max_users":        2,
        "max_organizations": 1,
    },
    "starter": {
        "monthly_searches": 2000,
        "use_hyde":         True,
        "use_multiquery":   True,
        "rate_per_minute":  10,
        "rate_per_hour":    100,
        "price_monthly":    49,
        "price_yearly":     470,
        "display_name":     "Starter",
        "max_businesses":   3,
        "max_users":        10,
        "max_organizations": 1,
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

def _analyze_sheet_layout(
    raw_sample_text: str,
    filename: str,
    sheet_name: str,
    file_context: str
) -> dict:
    prompt = f"""
You are an expert data engineer analyzing a raw spreadsheet for a RAG ingestion pipeline.
Filename: {filename}
Sheet Name: {sheet_name}
Business Context: {file_context if file_context.strip() else 'None provided'}

RAW SHEET PREVIEW (Zero-based row indices shown at start of each line):
{raw_sample_text}

Task:
Analyze the row layout and return a JSON object describing ALL tables or chart/summary blocks found on this sheet.

Return ONLY a valid JSON object matching this schema:
{{
  "blocks": [
    {{
      "name": "Short descriptive name for this block",
      "block_type": "table" | "chart_summary",
      "header_row_index": 40,      // Zero-based row index where column headers live (null if chart_summary)
      "data_start_index": 41,     // Zero-based row index where data rows start
      "data_end_index": null,     // Zero-based index where data ends (null if extends to sheet end)
      "strategy": "row_by_row" | "grouped_by_column",
      "group_by_column": "Invoice Number" // Column name that groups related rows (null if row_by_row)
    }}
  ]
}}

Rules for "strategy" & "group_by_column":
1. Use "grouped_by_column" if multi-line items share an ID/entity column (e.g. 'Invoice #', 'Patient Name', 'Order ID', 'Date'). Set "group_by_column" to the EXACT string header of that column.
2. Use "row_by_row" if each line is an independent standalone record (e.g., employee directory, product list). Set "group_by_column": null.
3. Use "chart_summary" for KPI blocks, unstructured summary text, or embedded chart matrices.
"""
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content or "{}")
    except Exception as e:
        print(f"[LLM Layout Error] {sheet_name}: {e}")
        return {
            "blocks": [
                {
                    "name": sheet_name,
                    "block_type": "table",
                    "header_row_index": 0,
                    "data_start_index": 1,
                    "data_end_index": None,
                    "strategy": "row_by_row",
                    "group_by_column": None
                }
            ]
        }
 
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


def extract_tabular_frames(file_bytes: bytes, filename: str):
    """
    Returns every worksheet as a DataFrame.

    Output:
    [
        {
            "sheet_name": "Billing",
            "dataframe": df
        },
        {
            "sheet_name": "Doctors",
            "dataframe": df
        }
    ]
    """

    workbook = pd.ExcelFile(io.BytesIO(file_bytes))

    sheets = []

    for sheet in workbook.sheet_names:
        df = workbook.parse(sheet, header=None)

        sheets.append({
            "sheet_name": sheet,
            "dataframe": df
        })

    return sheets
 
def build_schema_chunk(
    table_name: str,
    df: pd.DataFrame,
    filename: str,
    description: str = "",
    disambiguation: str = "",
    file_context: str = "",
    col_notes: str = "",
) -> str:
    """
    Creates a schema/metadata header string for a tabular dataframe.
    """
    cols = ", ".join([str(c) for c in df.columns])
    dtypes = ", ".join([f"{col} ({dtype})" for col, dtype in zip(df.columns, df.dtypes)])

    lines = [
        f"[Schema Header: Table '{table_name}' | Source: {filename}]",
        f"Total Columns ({len(df.columns)}): {cols}",
        f"Column Types: {dtypes}",
        f"Total Rows: {len(df)}"
    ]

    if description:
        lines.append(f"Description: {description}")
    if file_context:
        lines.append(f"Context Note: {file_context}")
    if disambiguation:
        lines.append(f"Disambiguation: {disambiguation}")
    if col_notes:
        lines.append(f"Column Notes: {col_notes}")

    return "\n".join(lines)

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
) -> dict:
    embedder = get_embedder()
    vectors  = build_multi_hyde_vectors(query, embedder)

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
                    c.id, c.text, c.parent_text, c.chunk_index, c.document_id, d.filename,
                    1 - (c.embedding <=> CAST(:query_vec AS vector)) AS score,
                    (c.chunk_type = 'tabular' OR c.text LIKE '[Table:%%' OR c.text LIKE '[Schema Header:%%') AS is_tabular
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.business_id = :business_id
                {doc_filter_sql}
            ),
            tabular_headers AS (
                SELECT DISTINCT ON (c.document_id)
                    c.id, c.text, c.parent_text, c.chunk_index, c.document_id, d.filename,
                    1.0 AS score, TRUE AS is_tabular
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.business_id = :business_id
                  AND c.chunk_index = 0
                  AND (c.chunk_type = 'tabular' OR c.text LIKE '[Table:%%' OR c.text LIKE '[Schema Header:%%')
                  {doc_filter_sql}
                  AND c.document_id IN (
                      SELECT document_id FROM scored
                      WHERE is_tabular AND score >= :min_tabular
                  )
            )
            SELECT id, text, parent_text, chunk_index, document_id, filename, score
            FROM (
                SELECT id, text, parent_text, chunk_index, document_id, filename, score
                FROM scored
                WHERE (is_tabular     AND score >= :min_tabular)
                   OR (NOT is_tabular AND score >= :min_standard)
                UNION
                SELECT id, text, parent_text, chunk_index, document_id, filename, score
                FROM tabular_headers
            ) combined
            ORDER BY score DESC
            LIMIT :limit_plus_one
            OFFSET :offset
        """

        rows = db.execute(text(sql), params).fetchall()
        for rank, row in enumerate(rows):
            chunk_id = row.id
            rrf_contribution = 1.0 / (rank + 1 + RRF_K)
            if chunk_id not in rrf_scores:
                rrf_scores[chunk_id] = {
                    "text":        row.parent_text or row.text,
                    "child_text":  row.text,
                    "filename":    row.filename,
                    "document_id": row.document_id,
                    "score":       row.score,
                    "rrf_score":   0.0,
                }
            rrf_scores[chunk_id]["rrf_score"] += rrf_contribution

    # Sort all results by RRF score
    merged = sorted(rrf_scores.values(), key=lambda x: x["rrf_score"], reverse=True)

    # Deduplicate by normalized parent fingerprint
    seen_parents = set()
    deduped = []
    for r in merged:
        parent_text = r.get("text", "")
        key = normalize_parent_key(parent_text)
        
        if key not in seen_parents:
            seen_parents.add(key)
            deduped.append(r)

    merged = deduped

    # Slice page and set has_more AFTER deduplication
    has_more = len(merged) > (offset + get_k)
    page     = merged[offset: offset + get_k]

    return {
        "results": [
            {
                "text":        r["text"],
                "filename":    r["filename"],
                "document_id": r["document_id"],
                "score":       float(round(r["score"], 4)),
            }
            for r in page
        ],
        "allResults": [
            {
                "text":        r["text"],
                "filename":    r["filename"],
                "document_id": r["document_id"],
                "score":       float(round(r["score"], 4)),
            }
            for r in merged
        ],
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
    filename: str,
    file_bytes: bytes,
    file_path: str = None,
    mime_type: str = None,
    file_context: str = "",
) -> int:
    ext = os.path.splitext(filename)[1].lower()
    embedder = get_embedder()

    # ==========================================================
    # Spreadsheet ingestion
    # ==========================================================
    if ext in [".csv", ".xlsx", ".xls"]:
        try:
            # 1. Read Raw Data without headers
            sheets_raw: dict[str, pd.DataFrame] = {}

            if ext == ".csv":
                df = pd.read_csv(io.BytesIO(file_bytes), header=None).fillna("")
                sheets_raw["Sheet1"] = df
            else:
                engine = "openpyxl" if ext in [".xlsx", ".xlsm"] else "xlrd"
                excel_file = pd.ExcelFile(
                    io.BytesIO(file_bytes), engine=engine
                )
                for sheet_name in excel_file.sheet_names:
                    sheets_raw[sheet_name] = excel_file.parse(
                        sheet_name, header=None
                    ).fillna("")

            pairs = []  # Will store {"child": text, "parent": text}

            # 2. Loop through each sheet
            for sheet_name, df_raw in sheets_raw.items():
                if df_raw.empty:
                    continue

                # Build row-indexed preview (first 120 non-empty rows)
                preview_lines = []
                for idx, row in df_raw.head(120).iterrows():
                    row_vals = [
                        f"Col {col_i}: {val}"
                        for col_i, val in enumerate(row)
                        if str(val).strip() != ""
                    ]
                    if row_vals:
                        preview_lines.append(
                            f"Row {idx}: " + " | ".join(row_vals)
                        )

                sample_text = "\n".join(preview_lines)

                # Ask LLM for layout breakdown
                layout = _analyze_sheet_layout(
                    sample_text, filename, sheet_name, file_context
                )
                blocks = layout.get("blocks", [])

                # ------------------------------------------------------
                # 📍 HERE IS WHERE THE BLOCKS LOGIC GOES 📍
                # ------------------------------------------------------
                for block in blocks:
                    block_name = block.get("name", sheet_name)
                    block_type = block.get("block_type", "table")
                    strategy = block.get("strategy", "row_by_row")
                    group_col = block.get("group_by_column")

                    header_idx = block.get("header_row_index")
                    data_start = block.get("data_start_index", 0)
                    data_end = block.get("data_end_index")

                    # Slice DataFrame to block bounds
                    if data_end is not None and isinstance(data_end, int):
                        sub_df = df_raw.iloc[data_start : data_end + 1].copy()
                    else:
                        sub_df = df_raw.iloc[data_start:].copy()

                    if sub_df.empty:
                        continue

                    # ==============================================================
                    # 1. Chart / KPI / Unstructured Summary Regions (Uses block_type)
                    # ==============================================================
                    if block_type == "chart_summary":
                        md_table = sub_df.to_markdown(index=False)
                        block_text = f"[Chart/Summary Block: {block_name} | Sheet: {sheet_name} | Source: {filename}]\n{md_table}"
                        pairs.append({"child": block_text, "parent": block_text})
                        continue

                    # ==============================================================
                    # 2. Standard Tabular Grids
                    # ==============================================================
                    # Extract column headers dynamically
                    if header_idx is not None and 0 <= header_idx < len(df_raw):
                        headers = [
                            str(val).strip() or f"Col_{i}"
                            for i, val in enumerate(df_raw.iloc[header_idx])
                        ]
                    else:
                        headers = [f"Col_{i}" for i in range(sub_df.shape[1])]

                    sub_df.columns = headers
                    sub_df = sub_df.loc[:, ~sub_df.columns.str.contains(r"^Col_\d+$|^\s*$")]

                    # Add Schema Header Chunk (index 0)
                    col_names = [str(c) for c in sub_df.columns]
                    schema_text = (
                        f"[Schema Header: Table '{block_name}' | Sheet: '{sheet_name}' | Source: {filename}]\n"
                        f"Columns ({len(col_names)}): {', '.join(col_names)}"
                    )
                    pairs.append({"child": schema_text, "parent": schema_text})

                    # Dynamic Column Grouping
                    if strategy == "grouped_by_column" and group_col and group_col in sub_df.columns:
                        sub_df[group_col] = (
                            sub_df[group_col]
                            .astype(str)
                            .replace(["", "nan", "None"], None)
                            .ffill()
                        )

                        for group_val, group_df in sub_df.groupby(group_col, sort=False):
                            if not group_val or str(group_val).strip() == "":
                                continue

                            records = group_df.to_dict(orient="records")
                            formatted_rows = [
                                " | ".join(
                                    f"{k}: {v}" for k, v in r.items() if str(v).strip() != ""
                                )
                                for r in records
                            ]

                            if not formatted_rows:
                                continue

                            child_text = (
                                f"[Table: {block_name} | {group_col}: {group_val}]\n"
                                + "\n".join(formatted_rows)
                            )
                            pairs.append({"child": child_text, "parent": child_text})

                    # Fallback Standard Row-by-Row
                    else:
                        records = sub_df.to_dict(orient="records")
                        for i, row in enumerate(records):
                            row_str = " | ".join(
                                f"{k}: {v}" for k, v in row.items() if str(v).strip() != ""
                            )
                            if not row_str:
                                continue

                            child_text = f"[Table: {block_name} | Row {i+1}]\n{row_str}"
                            pairs.append({"child": child_text, "parent": child_text})

            if not pairs:
                return 0

            # 3. Embed all chunks generated across sheets & blocks
            child_texts = [p["child"] for p in pairs]
            embeddings = embedder.encode(
                child_texts,
                show_progress_bar=False,
                normalize_embeddings=True,
            ).tolist()

            # 4. Save to DB
            db.add_all(
                [
                    Chunk(
                        business_id=business_id,
                        document_id=document_id,
                        chunk_index=idx,
                        text=p["child"],
                        parent_text=p["parent"],
                        chunk_type="tabular",
                        embedding=embedding,
                    )
                    for idx, (p, embedding) in enumerate(
                        zip(pairs, embeddings)
                    )
                ]
            )

            db.commit()
            return len(pairs)

        except Exception as e:
            db.rollback()
            print(f"[Ingest] Spreadsheet processing failed: {e}")
            raise e
    # ==========================================================
    # Text/PDF ingestion (UNCHANGED)
    # ==========================================================
    else:
        raw_text = extract_text(file_path, mime_type)
        raw_text = clean_text(raw_text)

        if not raw_text:
            return 0

        pairs = chunk_text_small_to_big(raw_text)

        if not pairs:
            return 0

        child_texts = [p["child"] for p in pairs]

        embeddings = embedder.encode(
            child_texts,
            show_progress_bar=False,
            normalize_embeddings=True,
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
                    (c.text LIKE '[Table:%%') AS is_tabular
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.business_id = :business_id
                {doc_filter_sql}
            ),
            tabular_headers AS (
                SELECT DISTINCT ON (c.document_id)
                    c.id, c.text, c.parent_text, c.chunk_index, c.document_id, d.filename,
                    1.0 AS score, TRUE AS is_tabular
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.business_id = :business_id
                  AND c.chunk_index = 0
                  AND c.text LIKE '[Table:%%'
                  {doc_filter_sql}
                  AND c.document_id IN (
                      SELECT document_id FROM scored
                      WHERE is_tabular AND score >= :min_tabular
                  )
            )
            SELECT id, text, parent_text, chunk_index, document_id, filename, score
            FROM (
                SELECT id, text, parent_text, chunk_index, document_id, filename, score
                FROM scored
                WHERE (is_tabular     AND score >= :min_tabular)
                   OR (NOT is_tabular AND score >= :min_standard)
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