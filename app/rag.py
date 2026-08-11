"""
Core RAG service using pgvector.
Handles: document ingestion → chunking → embedding → PostgreSQL storage → retrieval
"""
import os
import json
import redis
import pandas as pd
import openpyxl
from openpyxl.utils import range_boundaries
from datetime import datetime
from typing import List
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
TOP_K              = 5
EMBED_MODEL        = "all-MiniLM-L6-v2"
MIN_SCORE_STANDARD = 0.45
MIN_SCORE_TABULAR  = 0.0

# ── Plan config ────────────────────────────────────────────────────────────────
PLAN_CONFIG = {
    "free": {
        "monthly_searches":   50,
        "use_hyde":           True,
        "use_multiquery":     True,
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
            
    return row_chunks

def analyze_spreadsheet_with_llm(file_path: str, client: OpenAI = None) -> dict:
    if client is None:
        client = OpenAI()

    spreadsheet_text = extract_spreadsheet_to_text(file_path)

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

    try:
        parsed_data = json.loads(raw_content)
        return parsed_data
    except Exception as e:
        print(f"[Spreadsheet LLM] JSON parse error: {e}. Raw content was: {raw_content}")
        return {"tables": [], "charts": [], "key_findings": [], "spreadsheet_summary": ""}

def chunk_text_small_to_big(text: str) -> List[dict]:
    """
    Returns list of {child, parent} dicts.
    Child = small sentence-level chunk for embedding.
    Parent = surrounding paragraph for LLM context.
    """
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

def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
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
    retrieval_cursor: int,
    retrieval_limit: int,
    retrieval_vectors: list | None,
    retrieval_fully_exhausted: bool,
) -> None:
    try:
        redis_client.setex(
            get_active_query_key(user_id),
            ACTIVE_QUERY_TTL_SECONDS,
            json.dumps({
                "question": normalize_query(question),
                "business_id": business_id,
                "doc_state": doc_state,
                "answers": answers,
                "retrieval_results": retrieval_results,
                "retrieval_cursor": retrieval_cursor,
                "retrieval_limit": retrieval_limit,
                "retrieval_vectors": retrieval_vectors,
                "retrieval_fully_exhausted": retrieval_fully_exhausted,
            }),
        )

    except Exception as e:
        print(
            f"[Redis] Failed to cache active query: {e}"
        )

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
        print(
            "[Retrieval] No cached vectors; "
            "generating Multi-Query/HyDE vectors"
        )
        vectors = build_multi_hyde_vectors(
            query,
            embedder,
        )
    else:
        print(
            f"[Retrieval] Reusing {len(vectors)} "
            "cached Multi-Query/HyDE vectors"
        )

    doc_filter_sql = ""

    base_params = {
        "business_id": business_id,
        "min_standard": MIN_SCORE_STANDARD,
        "min_tabular": MIN_SCORE_TABULAR,
    }

    if document_ids:

        doc_filter_sql = (
            "AND c.document_id = ANY(:doc_ids)"
        )

        base_params["doc_ids"] = document_ids

    rrf_scores = {}

    RRF_K = 60

    # Retrieve enough candidates before deduplication.
    candidate_limit = max(
        (offset + get_k) * 5,
        get_k * 5,
        20,
    )

    for query_vector in vectors:

        params = {
            **base_params,
            "query_vec": query_vector,
            "limit": candidate_limit,
        }

        sql = f"""
            WITH scored AS (

                SELECT
                    c.id,
                    c.text,
                    c.parent_text,
                    c.chunk_index,
                    c.chunk_type,
                    c.content_type,
                    c.document_id,
                    d.filename,

                    1 - (
                        c.embedding
                        <=> CAST(:query_vec AS vector)
                    ) AS score

                FROM chunks c

                JOIN documents d
                    ON d.id = c.document_id

                WHERE
                    c.business_id = :business_id

                    {doc_filter_sql}
            )

            SELECT
                id,
                text,
                parent_text,
                chunk_index,
                chunk_type,
                content_type,
                document_id,
                filename,
                score

            FROM scored

            WHERE

                (
                    content_type = 'tabular'
                    AND score >= :min_tabular
                )

                OR

                (
                    content_type = 'metadata'
                    AND score >= :min_tabular
                )

                OR

                (
                    content_type = 'text'
                    AND score >= :min_standard
                )

            ORDER BY score DESC

            LIMIT :limit
        """

        rows = db.execute(
            text(sql),
            params,
        ).fetchall()

        print(
            f"[Retrieval] vector returned "
            f"{len(rows)} candidate chunks"
        )

        for rank, row in enumerate(rows):

            chunk_id = row.id

            contribution = (
                1.0 /
                (rank + 1 + RRF_K)
            )

            if chunk_id not in rrf_scores:

                rrf_scores[chunk_id] = {
                    "id": row.id,
                    "text": row.text,
                    "parent_text": row.parent_text,
                    "chunk_index": row.chunk_index,
                    "chunk_type": row.chunk_type,
                    "content_type": row.content_type,
                    "filename": row.filename,
                    "document_id": row.document_id,
                    "score": float(row.score),
                    "rrf_score": 0.0,
                }

            rrf_scores[
                chunk_id
            ]["rrf_score"] += contribution

    # ================================================================
    # RRF SORT
    # ================================================================

    merged = sorted(
    rrf_scores.values(),
    key=lambda x: x["rrf_score"],
    reverse=True,
)

# ------------------------------------------------------------------
# DEBUG: How many spreadsheet rows survived retrieval?
# ------------------------------------------------------------------

    structured = [
        r for r in merged
        if r.get("content_type") == "tabular"
    ]

    print(
        f"[Retrieval] "
        f"structured candidates={len(structured)} "
        f"total merged={len(merged)}"
    )

    for r in structured:
        print(
            f"  statement/chunk={r['chunk_index']} "
            f"score={r['score']:.4f} "
            f"{r['text'][:150]}"
        )

    # ------------------------------------------------------------------
    # 3. Deduplicate
    # ------------------------------------------------------------------

    # ================================================================
    # DEDUPLICATION
    # ================================================================

    deduped = []

    seen_text_parents = set()

    for result in merged:

        content_type = result[
            "content_type"
        ]

        # ------------------------------------------------------------
        # Spreadsheet rows
        # ------------------------------------------------------------

        if content_type == "tabular":

            # A database chunk is already one logical spreadsheet
            # record. If multiple HyDE searches find it, RRF has
            # already merged them by chunk ID.
            #
            # Therefore DO NOT deduplicate spreadsheet records
            # based on their text.
            deduped.append({
                "id": result["id"],
                "text": result["text"],
                "child_text": result["text"],
                "filename": result["filename"],
                "document_id": result["document_id"],
                "chunk_index": result["chunk_index"],
                "chunk_type": result["chunk_type"],
                "content_type": content_type,
                "score": round(
                    result["score"],
                    4,
                ),
                "rrf_score": result["rrf_score"],
            })

            continue

        # ------------------------------------------------------------
        # Metadata
        # ------------------------------------------------------------

        if content_type == "metadata":

            deduped.append({
                "id": result["id"],
                "text": result["text"],
                "child_text": result["text"],
                "filename": result["filename"],
                "document_id": result["document_id"],
                "chunk_index": result["chunk_index"],
                "chunk_type": result["chunk_type"],
                "content_type": content_type,
                "score": round(
                    result["score"],
                    4,
                ),
                "rrf_score": result["rrf_score"],
            })

            continue

        # ------------------------------------------------------------
        # PDF / text
        # ------------------------------------------------------------

        parent = (
            result["parent_text"]
            or result["text"]
        )

        parent_key = (
            result["document_id"],
            parent.strip(),
        )

        if parent_key in seen_text_parents:
            continue

        seen_text_parents.add(
            parent_key,
        )

        deduped.append({
            "id": result["id"],
            "text": parent,
            "child_text": result["text"],
            "filename": result["filename"],
            "document_id": result["document_id"],
            "chunk_index": result["chunk_index"],
            "chunk_type": result["chunk_type"],
            "content_type": content_type,
            "score": round(
                result["score"],
                4,
            ),
            "rrf_score": result["rrf_score"],
        })

    # ================================================================
    # DEBUG
    # ================================================================

    print(
        f"\n[MultiQuery] "
        f"{len(vectors)} variants "
        f"→ {len(merged)} candidates "
        f"→ {len(deduped)} after dedup"
    )

    for result in deduped[:20]:

        print(
            f"  score={result['score']:.4f}"
            f" | rrf={result['rrf_score']:.4f}"
            f" | content={result['content_type']}"
            f" | type={result['chunk_type']}"
            f" | index={result['chunk_index']}"
            f" | {result['filename']}"
            f" | {result['text'][:100]}"
        )

    # ================================================================
    # PAGINATION
    # ================================================================

    total_results = len(deduped)

    page_end = offset + get_k

    page = deduped[
        offset:page_end
    ]

    has_more = page_end < total_results

    next_offset = (
        page_end
        if has_more
        else None
    )

    return {
        "results": page,
        "allResults": deduped,
        "hasMore": has_more,
        "nextOffset": next_offset,
        "totalResults": total_results,
        "vectors": vectors,
    }

# ── Text extraction ────────────────────────────────────────────────────────────
def extract_text(file_path: str) -> str:
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


def clean_text(text: str) -> str:
    return text.replace("\x00", "")


# ── Ingest ─────────────────────────────────────────────────────────────────────
def ingest_document(
    db: Session,
    business_id: int,
    document_id: int,
    file_path: str,
    filename: str,
) -> int:

    from app.models import Chunk

    ext = Path(file_path).suffix.lower()
    embedder = get_embedder()

    chunks_to_add = []

    # ==================================================================
    # 1. EXCEL SPREADSHEETS
    # ==================================================================

    if ext in {".xlsx", ".xls"}:

        try:
            spreadsheet_meta = analyze_spreadsheet_with_llm(
                file_path
            )

        except Exception as e:
            print(
                f"[Ingest] Spreadsheet analysis failed "
                f"for {filename}: {e}"
            )

            spreadsheet_meta = {
                "tables": [],
                "charts": [],
                "key_findings": [],
                "spreadsheet_summary": "",
            }

        tables = spreadsheet_meta.get(
            "tables",
            [],
        )

        # --------------------------------------------------------------
        # Table records
        # --------------------------------------------------------------

        for table in tables:

            table_chunks = chunk_table_deterministically(
                file_path,
                table,
            )

            for chunk_text in table_chunks:

                if not chunk_text.strip():
                    continue

                chunks_to_add.append({
                    "text": chunk_text,
                    "parent": chunk_text,

                    # Specific chunk role
                    "chunk_type": "tabular_record",

                    # Broad pipeline type
                    "content_type": "tabular",
                })

        # --------------------------------------------------------------
        # Fallback if LLM detected no tables
        # --------------------------------------------------------------

        if not tables:

            print(
                f"[Ingest] Warning: no tables detected for "
                f"{filename}; using raw spreadsheet fallback."
            )

            try:

                excel_file = pd.ExcelFile(
                    file_path
                )

                for sheet_name in excel_file.sheet_names:

                    df = pd.read_excel(
                        excel_file,
                        sheet_name=sheet_name,
                        header=None,
                    )

                    for row_index, row in df.iterrows():

                        values = [
                            str(value)
                            for value in row.values
                            if pd.notna(value)
                        ]

                        if not values:
                            continue

                        row_text = (
                            f"Sheet: {sheet_name}\n"
                            f"Row: {row_index + 1}\n"
                            + " | ".join(values)
                        )

                        chunks_to_add.append({
                            "text": row_text,
                            "parent": row_text,
                            "chunk_type": "tabular_record",
                            "content_type": "tabular",
                        })

            except Exception as e:

                print(
                    f"[Ingest] Spreadsheet fallback failed "
                    f"for {filename}: {e}"
                )

        # --------------------------------------------------------------
        # Workbook summary
        # --------------------------------------------------------------

        summary = spreadsheet_meta.get(
            "spreadsheet_summary",
            "",
        )

        if summary:

            summary_text = (
                f"Workbook Summary:\n"
                f"{summary}"
            )

            chunks_to_add.append({
                "text": summary_text,
                "parent": summary_text,
                "chunk_type": "workbook_metadata",
                "content_type": "metadata",
            })

        # --------------------------------------------------------------
        # Charts
        # --------------------------------------------------------------

        charts = spreadsheet_meta.get(
            "charts",
            [],
        )

        for chart in charts:

            chart_text = (
                f"[Chart]\n"
                f"Name: {chart.get('chart_name', 'Untitled')}\n"
                f"Type: {chart.get('chart_type', 'Unknown')}\n"
                f"Location: {chart.get('location_or_range', 'Unknown')}\n"
                f"Description: {chart.get('description', '')}"
            )

            chunks_to_add.append({
                "text": chart_text,
                "parent": chart_text,
                "chunk_type": "chart_metadata",
                "content_type": "metadata",
            })

        # --------------------------------------------------------------
        # Key findings
        # --------------------------------------------------------------

        findings = spreadsheet_meta.get(
            "key_findings",
            [],
        )

        for finding in findings:

            if not finding:
                continue

            finding_text = (
                f"Workbook Finding:\n"
                f"{finding}"
            )

            chunks_to_add.append({
                "text": finding_text,
                "parent": finding_text,
                "chunk_type": "workbook_metadata",
                "content_type": "metadata",
            })

    # ==================================================================
    # 2. CSV
    # ==================================================================

    elif ext == ".csv":

        try:

            df = pd.read_csv(
                file_path,
            )

            # For now, keep the existing CSV behavior.
            csv_text = df.to_string(
                index=False,
            )

            if csv_text.strip():

                chunks_to_add.append({
                    "text": csv_text,
                    "parent": csv_text,
                    "chunk_type": "tabular_record",
                    "content_type": "tabular",
                })

        except Exception as e:

            print(
                f"[Ingest] CSV processing failed "
                f"for {filename}: {e}"
            )

            return 0

    # ==================================================================
    # 3. SPREADSHEET / CSV EMBEDDING
    # ==================================================================

    if ext in {".csv", ".xlsx", ".xls"}:

        print(
            f"[Ingest] Total spreadsheet/CSV chunks ready "
            f"to embed and save: {len(chunks_to_add)}"
        )

        if not chunks_to_add:

            print(
                f"[Ingest] Error: no chunks generated "
                f"for {filename}"
            )

            return 0

        texts = [
            chunk["text"]
            for chunk in chunks_to_add
        ]

        embeddings = embedder.encode(
            texts,
            show_progress_bar=False,
            normalize_embeddings=True,
        ).tolist()

        db_chunks = []

        for index, (
            chunk,
            embedding,
        ) in enumerate(
            zip(
                chunks_to_add,
                embeddings,
            )
        ):

            db_chunks.append(
                Chunk(
                    business_id=business_id,
                    document_id=document_id,
                    chunk_index=index,

                    text=chunk["text"],
                    parent_text=chunk["parent"],

                    chunk_type=chunk["chunk_type"],
                    content_type=chunk["content_type"],

                    embedding=embedding,
                )
            )

        db.add_all(db_chunks)
        db.commit()

        print(
            f"[Ingest] Successfully committed "
            f"{len(db_chunks)} chunks for {filename}"
        )

        return len(db_chunks)

    # ==================================================================
    # 4. PDF / NORMAL TEXT
    # ==================================================================

    raw_text = extract_text(file_path)

    raw_text = clean_text(
        raw_text,
    )

    if not raw_text:
        return 0

    pairs = chunk_text_small_to_big(
        raw_text,
    )

    if not pairs:
        return 0

    child_texts = [
        pair["child"]
        for pair in pairs
    ]

    embeddings = embedder.encode(
        child_texts,
        show_progress_bar=False,
        normalize_embeddings=True,
    ).tolist()

    db_chunks = []

    for index, (
        pair,
        embedding,
    ) in enumerate(
        zip(
            pairs,
            embeddings,
        )
    ):

        db_chunks.append(
            Chunk(
                business_id=business_id,
                document_id=document_id,
                chunk_index=index,

                text=pair["child"],
                parent_text=pair["parent"],

                chunk_type="child",
                content_type="text",

                embedding=embedding,
            )
        )

    db.add_all(db_chunks)
    db.commit()

    print(
        f"[Ingest] Successfully committed "
        f"{len(db_chunks)} text chunks for {filename}"
    )

    return len(db_chunks)


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
