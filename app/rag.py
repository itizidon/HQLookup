"""
Core RAG service using pgvector.
Handles: document ingestion → chunking → embedding → PostgreSQL storage → retrieval
"""
import json
import logging
import redis
import pandas as pd
from datetime import datetime, timezone
from typing import Callable, List
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
from app.settings import settings
from app.services.spreadsheet_ingestion import (
    analyze_spreadsheet_with_llm,
    build_spreadsheet_chunk_specs,
    chunk_table_deterministically,
    scan_workbook,
)
logger = logging.getLogger(__name__)

# ── Client ─────────────────────────────────────────────────────────────────────
client = OpenAI(
    base_url=settings.llm_base_url,
    api_key=settings.openai_api_key,
    timeout=settings.llm_timeout_seconds,
    max_retries=0,
)
LLM_MODEL = settings.llm_model
MAX_QUERY_VARIANTS = 4
MAX_QUERY_VARIANT_CHARS = 300

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
redis_client = redis.Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)

ACTIVE_QUERY_TTL_SECONDS = 60 * 60 * 6  # 6 hours
ACTIVE_QUERY_CACHE_VERSION = 2

# ── Singleton embedder ─────────────────────────────────────────────────────────
_embedder = None

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
        model_path = settings.embedding_model_path
        if settings.is_production:
            path = Path(model_path)
            if not path.is_absolute() or not path.is_dir():
                raise RuntimeError(
                    "Production embedding model path is missing or not absolute"
                )
            if not list(path.rglob("*.safetensors")):
                raise RuntimeError("Production embedding model must use safetensors")
            unsafe_artifacts = tuple(
                suffix
                for suffix in ("*.bin", "*.pt", "*.pth", "*.pkl", "*.pickle")
                if list(path.rglob(suffix))
            )
            if unsafe_artifacts:
                raise RuntimeError("Unsafe embedding model artifact detected")
        _embedder = SentenceTransformer(
            model_path,
            trust_remote_code=False,
            local_files_only=settings.is_production,
        )
        if _embedder.get_sentence_embedding_dimension() != 384:
            raise RuntimeError("Embedding model must produce 384-dimensional vectors")
    return _embedder


# ── Search quota ───────────────────────────────────────────────────────────────
class QuotaBackendUnavailable(RuntimeError):
    """Raised when a cost-bearing request cannot reserve quota safely."""


def _monthly_search_key(org_id: int) -> str:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return f"searches:org:{org_id}:{month}"


def get_monthly_search_count(org_id: int) -> int:
    key = _monthly_search_key(org_id)
    try:
        val = redis_client.get(key)
        return int(val) if val else 0
    except redis.RedisError as exc:
        raise QuotaBackendUnavailable("Search quota service is unavailable") from exc

def increment_search_count(org_id: int) -> int:
    key = _monthly_search_key(org_id)
    try:
        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60 * 60 * 24 * 35)  # 35 days
        count, _ = pipe.execute()
        return int(count)
    except redis.RedisError as exc:
        raise QuotaBackendUnavailable("Search quota service is unavailable") from exc

def check_search_limit(org_id: int, plan: str) -> tuple[bool, int, int]:
    """Returns (allowed, current_count, limit)"""
    config  = PLAN_CONFIG.get(plan, PLAN_CONFIG["free"])
    limit   = config["monthly_searches"]
    current = get_monthly_search_count(org_id)
    return current < limit, current, limit


_RESERVE_SEARCH_SCRIPT = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local limit = tonumber(ARGV[1])
if current >= limit then
    return {0, current}
end
current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
end
return {1, current}
"""

_RESERVE_SEARCH_WITH_BUSINESS_SCRIPT = """
local org_current = tonumber(redis.call('GET', KEYS[1]) or '0')
local business_current = tonumber(redis.call('GET', KEYS[2]) or '0')
local org_limit = tonumber(ARGV[1])
local business_limit = tonumber(ARGV[2])
if org_current >= org_limit then
    return {0, org_current, business_current, 1}
end
if business_current >= business_limit then
    return {0, org_current, business_current, 2}
end
org_current = redis.call('INCR', KEYS[1])
business_current = redis.call('INCR', KEYS[2])
if org_current == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
end
if business_current == 1 then
    redis.call('EXPIRE', KEYS[2], tonumber(ARGV[3]))
end
return {1, org_current, business_current, 0}
"""


def reserve_search(
    org_id: int,
    plan: str,
    business_id: int | None = None,
    business_limit: int | None = None,
) -> tuple:
    """Atomically reserve one monthly search, failing closed on Redis errors."""

    limit = PLAN_CONFIG.get(plan, PLAN_CONFIG["free"])["monthly_searches"]
    try:
        if business_id is None or business_limit is None:
            allowed, current = redis_client.eval(
                _RESERVE_SEARCH_SCRIPT,
                1,
                _monthly_search_key(org_id),
                limit,
                60 * 60 * 24 * 35,
            )
            return bool(int(allowed)), int(current), limit

        allowed, org_current, business_current, reason = redis_client.eval(
            _RESERVE_SEARCH_WITH_BUSINESS_SCRIPT,
            2,
            _monthly_search_key(org_id),
            f"searches:business:{business_id}:{datetime.now(timezone.utc):%Y-%m}",
            limit,
            max(0, business_limit),
            60 * 60 * 24 * 35,
        )
        return (
            bool(int(allowed)),
            int(org_current),
            limit,
            int(business_current),
            max(0, business_limit),
            int(reason),
        )
    except redis.RedisError as exc:
        raise QuotaBackendUnavailable("Search quota service is unavailable") from exc


# ── Active query cache (per user) ──────────────────────────────────────────────
def normalize_query(query: str) -> str:
    return " ".join(query.lower().strip().split())

def get_active_query_key(user_id: int) -> str:
    return f"active_query:v{ACTIVE_QUERY_CACHE_VERSION}:{user_id}"

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

    except redis.RedisError:
        logger.warning("Failed to cache active query for user_id=%s", user_id)

def clear_active_query(user_id: int) -> None:
    try:
        redis_client.delete(get_active_query_key(user_id))
    except Exception:
        pass


# ── HyDE ──────────────────────────────────────────────────────────────────────
def generate_hypothetical_answer(
    query: str,
    reserve_llm_call: Callable[[], bool] | None = None,
) -> str:
    hyde_prompt = f"""You are a search assistant. A user is searching a document database.
Write a SHORT hypothetical passage (2-4 sentences) that would be the ideal answer 
to the following question. Write it as if it were extracted from a real document or table.
Do NOT say "I don't know". Always write a plausible passage.
Do NOT include any explanation — output ONLY the passage itself.

Question: {query}
Passage:"""
    if reserve_llm_call is not None and not reserve_llm_call():
        return query
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": hyde_prompt}],
            temperature=0.5,
            max_tokens=150,
        )
        hypothetical = response.choices[0].message.content.strip()
        return hypothetical
    except Exception:
        logger.warning("HyDE generation failed; using the original query")
        return query


def build_hyde_vector(
    query: str,
    embedder: SentenceTransformer,
    reserve_llm_call: Callable[[], bool] | None = None,
) -> list:
    import numpy as np
    hypothetical = generate_hypothetical_answer(query, reserve_llm_call)
    vecs         = embedder.encode([query, hypothetical], normalize_embeddings=True)
    avg          = (vecs[0] + vecs[1]) / 2.0
    norm         = np.linalg.norm(avg)
    if norm > 0:
        avg = avg / norm
    return avg.tolist()


# ── Multi-Query HyDE ───────────────────────────────────────────────────────────
def generate_query_variants(
    query: str,
    reserve_llm_call: Callable[[], bool] | None = None,
) -> List[str]:
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
    if reserve_llm_call is not None and not reserve_llm_call():
        return [query]
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
            clean_variants: list[str] = []
            seen = {query.strip().casefold()}
            for variant in variants:
                if not isinstance(variant, str):
                    continue
                normalized = " ".join(variant.split())
                identity = normalized.casefold()
                if not normalized or len(normalized) > MAX_QUERY_VARIANT_CHARS:
                    continue
                if identity in seen:
                    continue
                clean_variants.append(normalized)
                seen.add(identity)
                if len(clean_variants) >= MAX_QUERY_VARIANTS:
                    break
            return [query] + clean_variants
    except Exception:
        logger.warning("Multi-query generation failed; using the original query")
    return [query]


def build_multi_hyde_vectors(
    query: str,
    embedder: SentenceTransformer,
    reserve_llm_call: Callable[[], bool] | None = None,
) -> List[list]:
    import numpy as np
    variants = generate_query_variants(query, reserve_llm_call)
    vectors  = []
    for variant in variants:
        try:
            vectors.append(build_hyde_vector(variant, embedder, reserve_llm_call))
        except Exception:
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
    reserve_llm_call: Callable[[], bool] | None = None,
) -> dict:

    embedder = get_embedder()

    if vectors is None:
        logger.debug("Generating retrieval vectors")
        vectors = build_multi_hyde_vectors(
            query,
            embedder,
            reserve_llm_call,
        )
    else:
        logger.debug("Reusing %s cached retrieval vectors", len(vectors))

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

        logger.debug("Retrieval vector returned %s candidates", len(rows))

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

            else:
                # Expose the strongest cosine similarity observed across
                # the query variants, not whichever vector found it first.
                rrf_scores[chunk_id]["score"] = max(
                    rrf_scores[chunk_id]["score"],
                    float(row.score),
                )

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

    logger.debug(
        "Retrieval merged candidates structured=%s total=%s",
        len(structured),
        len(merged),
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

    logger.debug(
        "Multi-query retrieval variants=%s merged=%s deduplicated=%s",
        len(vectors),
        len(merged),
        len(deduped),
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
    max_extracted_chars = settings.max_ingested_chunk_chars * 200
    path = Path(file_path)
    ext  = path.suffix.lower()

    if ext == ".pdf":
        import fitz
        text = ""
        doc  = fitz.open(path)
        for page in doc:
            for b in page.get_text("blocks"):
                text += b[4] + " "
                if len(text) >= max_extracted_chars:
                    break
            if len(text) >= max_extracted_chars:
                break
        doc.close()
        return text

    if ext in [".xlsx", ".xlsm", ".xls"]:
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
        return "\n".join([p.text for p in doc.paragraphs])[:max_extracted_chars]

    if ext in [".txt", ".md"]:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(max_extracted_chars)

    logger.warning("Rejected unsupported file extension")
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
    *,
    ingestion_notes: str | None = None,
) -> int:

    from app.models import Chunk

    ext = Path(file_path).suffix.lower()
    embedder = get_embedder()

    chunks_to_add = []

    # ==================================================================
    # 1. EXCEL SPREADSHEETS
    # ==================================================================

    if ext in {".xlsx", ".xlsm", ".xls"}:
        chunks_to_add = build_spreadsheet_chunk_specs(
            file_path,
            filename,
            client=client,
            ingestion_notes=ingestion_notes,
        )

    # ==================================================================
    # 2. CSV
    # ==================================================================

    elif ext == ".csv":

        try:

            df = pd.read_csv(
                file_path,
            )

            for row_index, row in df.iterrows():
                values = [
                    f"{column}: {value}"
                    for column, value in row.items()
                    if pd.notna(value)
                ]
                row_text = (
                    f"Row: {row_index + 1}\n" + " | ".join(values)
                )[: settings.max_ingested_chunk_chars]
                if row_text.strip():
                    chunks_to_add.append({
                        "text": row_text,
                        "parent": row_text,
                        "chunk_type": "tabular_record",
                        "content_type": "tabular",
                    })

        except Exception:
            logger.warning("CSV ingestion failed")

            return 0

    # ==================================================================
    # 3. SPREADSHEET / CSV EMBEDDING
    # ==================================================================

    if ext in {".csv", ".xlsx", ".xlsm", ".xls"}:

        logger.debug("Spreadsheet chunks ready=%s", len(chunks_to_add))

        if not chunks_to_add:

            logger.warning("Spreadsheet ingestion generated no chunks")

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

        logger.info("Spreadsheet ingestion committed chunks=%s", len(db_chunks))

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

    logger.info("Text ingestion committed chunks=%s", len(db_chunks))

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
    reserve_llm_call: Callable[[], bool] | None = None,
) -> dict:
    embedder = get_embedder()

    if use_hyde:
        query_vector = build_hyde_vector(query, embedder, reserve_llm_call)
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
