# app/ingestion/pipeline.py

import io
import fitz
from typing import List, Tuple, Any
import os
from openai import OpenAI

from app.ingestion.models import RAGChunk, WorkbookGraph
from app.ingestion.workbook_parser import extract_workbook, extract_regions_from_sheet
from app.ingestion.validators import validate_and_sanitize_analysis
from app.ingestion.chunk_builder import build_chunks_for_region
from app.ingestion.relationship_detector import build_workbook_graph
from app.ingestion.metadata_enricher import enrich_chunk_metadata
from app.ingestion.embedder import generate_chunk_embeddings
from app.ingestion.hierarchical_chunker import process_document_hierarchically


client = OpenAI(
    base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
    api_key=os.getenv("OPENAI_API_KEY", "ollama"),
)

def extract_text_from_bytes(file_bytes: bytes, filename: str) -> str:
    """Extracts raw text from bytes based on file extension (PDF, docx, txt, md)."""
    ext = filename.lower().split(".")[-1]

    if ext == "pdf":
        text = ""
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            for b in page.get_text("blocks"):
                text += b[4] + " "
        doc.close()
        return text

    elif ext == "docx":
        import docx
        doc = docx.Document(io.BytesIO(file_bytes))
        return "\n".join([p.text for p in doc.paragraphs])

    elif ext in ["txt", "md"]:
        return file_bytes.decode("utf-8", errors="ignore")

    else:
        return file_bytes.decode("utf-8", errors="ignore")


# app/ingestion/pipeline.py

# app/ingestion/pipeline.py

def ingest_spreadsheet(
    file_bytes: bytes,
    filename: str,
    openai_client: Any,
    analyze_region_func: Any = None
) -> Tuple[List[RAGChunk], WorkbookGraph]:
    """Executes the complete multi-phase spreadsheet ingestion pipeline with robust fallback handling."""
    workbook_data = extract_workbook(file_bytes, filename=filename)
    
    if analyze_region_func is None:
        analyze_region_func = lambda region, filename, llm_client: {
            "title": f"Table from {filename} ({region.sheet_name})",
            "summary": "Extracted spreadsheet region values and formulas.",
            "chunk_strategy": "whole_table",
            "confidence": 1.0,
        }

    all_chunks = []
    analyzed_regions = []

    for sheet in workbook_data.sheets:
        regions = extract_regions_from_sheet(sheet)
        for region in regions:
            raw_analysis = analyze_region_func(region, filename=filename, llm_client=openai_client)
            
            # Safely validate analysis, falling back gracefully if Pydantic raises an Enum or validation error
            try:
                analysis = validate_and_sanitize_analysis(raw_analysis, region)
            except Exception as val_err:
                print(f"[Phase 5 Fallback Triggered]: {val_err}")
                
                class FallbackAnalysis:
                    def __init__(self):
                        self.title = f"Table from {filename} ({region.sheet_name})"
                        self.summary = "Extracted spreadsheet region values and formulas."
                        self.chunk_strategy = "whole_table"
                        self.confidence = 1.0
                        self.flat_headers = []
                        self.primary_key = None
                        self.columns = []
                        self.data_start_index = 0
                        self.header_row_index = 0

                analysis = FallbackAnalysis()

            analyzed_regions.append((region, analysis))
            
            region_chunks = build_chunks_for_region(region, analysis)
            all_chunks.extend(region_chunks)

    workbook_graph = build_workbook_graph(analyzed_regions)

    enriched_chunks = []
    region_map = {r.region_id: (r, a) for r, a in analyzed_regions}
    
    for chunk in all_chunks:
        region_id = chunk.metadata.get("region_id")
        if region_id and region_id in region_map:
            region, analysis = region_map[region_id]
            enriched = enrich_chunk_metadata(chunk, region, analysis, filename, workbook_graph)
            enriched_chunks.append(enriched)
        else:
            enriched_chunks.append(chunk)

    final_chunks = generate_chunk_embeddings(enriched_chunks, openai_client=openai_client)
    print(f"[Spreadsheet Ingestion Complete] '{filename}': {len(final_chunks)} chunks indexed.")
    return final_chunks, workbook_graph


def ingest_text_or_pdf(
    file_bytes: bytes,
    filename: str,
    openai_client: Any
) -> List[RAGChunk]:
    """Executes small-to-big hierarchical text ingestion for PDFs, Word docs, and text files."""
    raw_text = extract_text_from_bytes(file_bytes, filename)
    
    if not raw_text.strip():
        return []

    # Processes text through your LangChain RecursiveCharacterTextSplitter small-to-big logic
    chunks = process_document_hierarchically(filename, raw_text)
    
    # Generates embeddings for all child chunks
    final_chunks = generate_chunk_embeddings(chunks, openai_client=openai_client)

    print(f"[Document Ingestion Complete] '{filename}': {len(final_chunks)} hierarchical chunks indexed.")
    return final_chunks


def ingest_document(
    file_bytes: bytes,
    filename: str,
    analyze_region_func: Any = None
) -> Any:
    """Master Dispatcher Function."""
    ext = filename.lower().split(".")[-1]

    if ext in ["xlsx", "xls", "csv"]:
        return ingest_spreadsheet(file_bytes, filename, client, analyze_region_func)
    elif ext in ["pdf", "docx", "txt", "md"]:
        return ingest_text_or_pdf(file_bytes, filename, client)
    else:
        raise ValueError(f"Unsupported file extension: .{ext}")