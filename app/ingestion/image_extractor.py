# app/ingestion/image_extractor.py

import io
from PIL import Image
from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class ExtractedImage(BaseModel):
    image_id: str
    sheet_name: str
    cell_anchor: str  # e.g., "E10"
    image_bytes: bytes
    format: str


def extract_images_from_worksheet(ws: Any) -> List[ExtractedImage]:
    """Phase 12a: Extracts embedded images and their cell coordinates from openpyxl sheet."""
    images = []
    
    for idx, img in enumerate(getattr(ws, "_images", [])):
        # Extract anchor cell coordinate if available
        cell_anchor = "A1"
        if hasattr(img, "anchor") and hasattr(img.anchor, "_from"):
            col = img.anchor._from.col + 1
            row = img.anchor._from.row + 1
            cell_anchor = f"{col}{row}"

        # Extract raw byte payload
        img_bytes = img.ref.getvalue()
        pil_img = Image.open(io.BytesIO(img_bytes))

        images.append(ExtractedImage(
            image_id=f"{ws.title}_img_{idx}",
            sheet_name=ws.title,
            cell_anchor=cell_anchor,
            image_bytes=img_bytes,
            format=pil_img.format or "PNG"
        ))

    return images