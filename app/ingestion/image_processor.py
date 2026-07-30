# app/ingestion/image_processor.py

import base64
import json
from typing import Optional, Dict, Any
from .models import RAGChunk, ExtractedImage


VISION_SYSTEM_PROMPT = """You are an image analysis engine for spreadsheet RAG pipelines.
Analyze the provided image embedded in a spreadsheet and classify it into ONE category:
1. "DECORATIVE": Logos, icons, decorative stamps, empty shapes.
2. "CHART": Graphs, bar charts, trend visualizations, dashboards.
3. "DOCUMENT_OR_TABLE": Receipts, invoice scans, text tables, forms.

If DECORATIVE, set "skip": true.

For CHART or DOCUMENT_OR_TABLE, generate a high-precision markdown representation:
- Title / Summary
- Extracted Data / Key-Value Pairs / Series Table
- Key Business Context / Takeaways

Return JSON with this schema:
{
  "category": "<DECORATIVE | CHART | DOCUMENT_OR_TABLE>",
  "skip": <true | false>,
  "title": "<Short description of image contents>",
  "markdown_content": "<Structured markdown for vector embedding>",
  "summary": "<1-2 sentence high-level business summary>"
}
"""


def process_image_to_chunk(
    extracted_img: ExtractedImage,
    filename: str,
    openai_client: Any
) -> Optional[RAGChunk]:
    """Phase 12b: Uses Vision LLM to classify and extract structured text from workbook images."""
    
    # Encode image bytes to base64
    b64_image = base64.b64encode(extracted_img.image_bytes).decode("utf-8")

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": VISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Sheet: {extracted_img.sheet_name}, Anchor: {extracted_img.cell_anchor}"},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/{extracted_img.format.lower()};base64,{b64_image}"}
                        }
                    ]
                }
            ],
            temperature=0.0
        )
        
        result = json.loads(response.choices[0].message.content)

        # Skip decorative images (logos, dividers) to avoid index noise
        if result.get("skip") or result.get("category") == "DECORATIVE":
            return None

        # Build standard RAGChunk compliant with Phase 8 metadata
        content = f"## Image Context: {result.get('title')}\n"
        content += f"**Sheet:** {extracted_img.sheet_name} | **Anchor Cell:** {extracted_img.cell_anchor}\n\n"
        content += result.get("markdown_content", "")

        metadata = {
            "file_name": filename,
            "sheet_name": extracted_img.sheet_name,
            "table_name": result.get("title", "Embedded Image"),
            "entity_type": result.get("category"),
            "chunk_strategy": "SUMMARY",
            "confidence_score": 0.95,
            "business_context": result.get("summary", ""),
            "is_image": True,
            "cell_anchor": extracted_img.cell_anchor
        }

        return RAGChunk(
            chunk_id=f"chunk_{extracted_img.image_id}",
            content=content,
            metadata=metadata
        )

    except Exception as e:
        print(f"[Phase 12 Exception] Vision processing failed for {extracted_img.image_id}: {e}")
        return None