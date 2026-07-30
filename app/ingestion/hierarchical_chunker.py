# app/ingestion/hierarchical_chunker.py

from typing import List, Dict
from langchain_text_splitters import RecursiveCharacterTextSplitter
from .models import RAGChunk


def clean_text(text: str) -> str:
    """Cleans extracted raw text by stripping lines."""
    if not text:
        return ""
    return "\n".join([line.strip() for line in text.splitlines() if line.strip()])


def chunk_text_small_to_big(text: str) -> List[Dict[str, str]]:
    """Returns list of {child, parent} dicts using LangChain RecursiveCharacterTextSplitter.
    Child = small sentence-level chunk for embedding.
    Parent = surrounding paragraph for LLM context.
    """
    # Step 1: Split into large parent chunks (paragraphs)
    parent_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=0,
        separators=["\n\n\n", "\n\n", "\n"],
    )
    parents = parent_splitter.split_text(text)

    # Step 2: Split each parent into small child chunks
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=150,
        chunk_overlap=0,
        separators=[".\n", ". ", "! ", "? ", "\n", " "],
    )

    result = []
    for parent in parents:
        children = child_splitter.split_text(parent)
        for child in children:
            if child.strip():
                result.append({
                    "child": child.strip(),
                    "parent": parent.strip(),
                })

    return result


def process_document_hierarchically(filename: str, full_text: str) -> List[RAGChunk]:
    """Hierarchical chunker bridging your small-to-big pairs into pipeline RAGChunks."""
    cleaned = clean_text(full_text)
    pairs = chunk_text_small_to_big(cleaned)
    
    chunks = []
    for i, p in enumerate(pairs):
        chunk_id = f"{filename}_chunk_{i}"
        metadata = {
            "file_name": filename,
            "chunk_strategy": "HIERARCHICAL_SMALL_TO_BIG",
            "parent_text": p["parent"],
            "entity_type": "DocumentSection",
            "chunk_type": "child",
            "chunk_index": i
        }
        chunks.append(
            RAGChunk(
                chunk_id=chunk_id,
                content=p["child"],
                metadata=metadata
            )
        )
        
    return chunks