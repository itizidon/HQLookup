# app/ingestion/embedder.py

from typing import List, Any, Optional
from sentence_transformers import SentenceTransformer
from .models import RAGChunk

EMBED_MODEL = "all-MiniLM-L6-v2"
_embedder = None


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        print("Loading embedding model... (first time only)")
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder


def generate_chunk_embeddings(
    chunks: List[RAGChunk],
    openai_client: Optional[Any] = None
) -> List[RAGChunk]:
    """Phase 9: Generates vector embeddings for a list of RAGChunks and assigns them."""
    if not chunks:
        return []

    embedder = get_embedder()
    contents = [chunk.content for chunk in chunks]

    # Generate normalized embeddings using sentence-transformers
    embeddings = embedder.encode(
        contents,
        show_progress_bar=False,
        normalize_embeddings=True,
    ).tolist()

    # Assign embeddings back to the respective RAGChunks
    for chunk, embedding in zip(chunks, embeddings):
        chunk.embedding = embedding

    return chunks