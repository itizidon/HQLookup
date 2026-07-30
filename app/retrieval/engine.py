# app/retrieval/engine.py

import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class QueryIntent(BaseModel):
    search_query: str
    target_tables: List[str] = []
    entity_id: Optional[str] = None
    entity_type: Optional[str] = None
    expand_relationships: bool = True


# -------------------------------------------------------------------
# 1. Intent & Entity Parsing
# -------------------------------------------------------------------
def parse_query_intent(user_query: str, openai_client: Any) -> QueryIntent:
    """Extracts metadata filtering intent and target entities from user prompt."""
    prompt = f"""
    You are a RAG retrieval router for spreadsheet data.
    Analyze the user's query and extract metadata targets for filtering.

    User Query: "{user_query}"

    Return JSON matching this schema:
    {{
      "search_query": "<Cleaned semantic search string>",
      "target_tables": ["<List of relevant table/sheet names if mentioned>"],
      "entity_id": "<Specific ID, name, or key if mentioned, else null>",
      "entity_type": "<Entity type like Patient, Invoice, Order if mentioned, else null>",
      "expand_relationships": true
    }}
    """
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        data = json.loads(response.choices[0].message.content)
        return QueryIntent(**data)
    except Exception:
        # Fallback to direct semantic vector search
        return QueryIntent(search_query=user_query, expand_relationships=True)


# -------------------------------------------------------------------
# 2. Graph Relationship Expansion Engine
# -------------------------------------------------------------------
def expand_graph_neighbors(
    primary_chunks: List[Dict[str, Any]], 
    vector_store: Any,
    max_neighbors_per_chunk: int = 3
) -> List[Dict[str, Any]]:
    """Phase 10 Expansion: Scans primary search results for Phase 7 graph links

    and fetches linked records across sheets (e.g., Invoice -> Payment history).
    """
    expanded_chunks = list(primary_chunks)
    seen_chunk_ids = {c["chunk_id"] for c in primary_chunks}

    for chunk in primary_chunks:
        metadata = chunk.get("metadata", {})
        relationships = metadata.get("relationships", [])

        # Get entity ID to join across sheets
        entity_id = metadata.get("entity_id")
        
        for rel in relationships:
            related_table = rel.get("related_table")
            join_key = rel.get("join_key")

            if not related_table:
                continue

            # Query vector store for related table using exact metadata filter
            filter_kwargs = {"table_name": related_table}
            if entity_id:
                filter_kwargs["entity_id"] = entity_id

            # Retrieve neighboring records
            neighbor_results = vector_store.search_by_metadata(
                filter_dict=filter_kwargs,
                limit=max_neighbors_per_chunk
            )

            for neighbor in neighbor_results:
                if neighbor["chunk_id"] not in seen_chunk_ids:
                    seen_chunk_ids.add(neighbor["chunk_id"])
                    # Mark chunk as a graph expansion chunk for transparency
                    neighbor["metadata"]["is_graph_expansion"] = True
                    neighbor["metadata"]["expanded_from"] = metadata.get("table_name")
                    expanded_chunks.append(neighbor)

    return expanded_chunks


# -------------------------------------------------------------------
# 3. Complete Phase 10 Master Retrieval Pipeline
# -------------------------------------------------------------------
def retrieve_context_for_query(
    user_query: str,
    vector_store: Any,
    openai_client: Any,
    top_k: int = 5
) -> str:
    """Master Phase 10 Retrieval Function: Intent Parsing -> Filtered Vector Search -> Graph Expansion -> Context Formatting."""
    
    # Step 1: Parse Intent & Extract Filters
    intent = parse_query_intent(user_query, openai_client)

    # Step 2: Build Vector Search Filters
    search_filters = {}
    if intent.entity_id:
        search_filters["entity_id"] = intent.entity_id
    if intent.entity_type:
        search_filters["entity_type"] = intent.entity_type
    if intent.target_tables:
        search_filters["table_name"] = intent.target_tables[0]

    # Step 3: Run Metadata-Filtered Vector Search
    primary_results = vector_store.similarity_search(
        query=intent.search_query,
        filter_dict=search_filters,
        top_k=top_k
    )

    # Step 4: Expand Graph Relationships across Sheets (Phase 7 Links)
    if intent.expand_relationships:
        final_results = expand_graph_neighbors(primary_results, vector_store)
    else:
        final_results = primary_results

    # Step 5: Format Final Assembly for LLM
    context_blocks = []
    for idx, c in enumerate(final_results, 1):
        meta = c.get("metadata", {})
        source_label = f"[{meta.get('table_name', 'Table')} | Sheet: {meta.get('sheet_name', 'Unknown')}]"
        if meta.get("is_graph_expansion"):
            source_label += f" (Linked via {meta.get('expanded_from')})"

        block = f"--- Source {idx}: {source_label} ---\n{c['content']}"
        context_blocks.append(block)

    return "\n\n".join(context_blocks)