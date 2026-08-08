"""
LLM service (OpenAI only).
Builds grounded prompts from retrieved chunks and generates answers.
"""

import os
import json
import re
from typing import List
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

# Initialize client once
client = OpenAI(
    base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
    api_key=os.getenv("OPENAI_API_KEY", "ollama"),
)
LLM_MODEL = os.getenv("LLM_MODEL", "mistral:7b")

def clean_json_response(raw_text: str) -> str:
    """Strips markdown code fences (```json ... ```) if the model outputs them."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()

# ── Prompt builder ─────────────────────────────────────────────────────────────
def build_prompt(
    question: str,
    chunks: List[dict],
) -> str:

    context_blocks = []

    for i, chunk in enumerate(chunks, 1):

        context_blocks.append(
            f"""[{i}]
FILE: {chunk['filename']}
CHUNK ID: {chunk.get('id', i)}
CONTENT TYPE: {chunk.get('content_type', 'unknown')}
CHUNK TYPE: {chunk.get('chunk_type', 'unknown')}
SCORE: {chunk['score']}

{chunk['text']}
"""
        )

    context = "\n\n---\n\n".join(
        context_blocks
    )

    return f"""
You are a precise retrieval answer generator.

Answer the user's question using ONLY the provided context.

The context may contain spreadsheet rows, spreadsheet metadata,
or normal document text.

IMPORTANT RULES:

1. Return ONLY valid JSON.
2. Do not return markdown.
3. Do not hallucinate information.
4. Preserve dates, dollar amounts, IDs, names, and other values
   exactly as they appear.
5. Every answer must be supported by the context.
6. Ignore context blocks that do not contain information relevant
   to the question.
7. Confidence must be between 0.0 and 1.0.

SPREADSHEET RULES:

8. A tabular context block represents ONE spreadsheet record.
9. Do not combine values from different spreadsheet records.
10. Do not move a value from one row into another row.
11. Keep fields from the same row together.
12. If two rows have the same provider and date but different
    statement/order numbers, they are still separate records.
13. If two context blocks have the same unique identifier
    (for example Statement Number, Invoice Number, Order Number,
    Claim ID, or another explicit record identifier), treat them
    as the same record.
14. If duplicate context blocks describe the same record, return
    only one answer for that record.
15. If two records have different unique identifiers, return
    separate answers.
16. Never invent a unique identifier when one is missing.

FIELD ASSOCIATION:

When answering a spreadsheet question, use the values from the
SAME Row Data block.

For example, if a row contains:

Statement Number: 1236
Total Amount Billed: 200

the answer must associate 200 with statement number 1236.

Do not take the statement number from one context block and the
amount from another context block.

If the question asks for an amount, use the field that most
directly represents the requested amount.

For a question asking how much was charged, prefer:

Total Amount Billed

over:

Amount Paid
Amount Paid by Insurance
Out-of-Pocket
Amount Due

unless the question explicitly asks for one of those fields.

OUTPUT FORMAT:

{{
  "answers": [
    {{
      "answer": "Complete answer supported by one logical record.",
      "confidence": 0.98,
      "sources": [
        {{
          "chunk": 1,
          "filename": "example.xlsx"
        }}
      ]
    }}
  ]
}}

If no context answers the question:

{{
  "answers": []
}}

CONTEXT:

{context}

QUESTION:

{question}
""".strip()


# ── OpenAI call ───────────────────────────────────────────────────────────────
def call_openai(prompt: str) -> str:
    response = client.chat.completions.create(
        model=LLM_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are a precise retrieval assistant that outputs strictly valid JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
    )
    print(response)
    return response.choices[0].message.content


# ── Public interface ───────────────────────────────────────────────────────────
def generate_answer(question: str, chunks: List[dict]) -> dict:
    prompt = build_prompt(question, chunks)
    print("\n=== DEBUG: PROMPT SENT TO LLM ===")
    print(prompt)
    print("=================================\n")
    raw = call_openai(prompt)
    
    # Strip markdown backticks before parsing
    cleaned_raw = clean_json_response(raw)

    try:
        return json.loads(cleaned_raw)
    except json.JSONDecodeError:
        # Fallback safety if model fails JSON generation completely
        print(f"[LLM Warning] Failed to parse JSON. Raw output:\n{raw}")
        return {
            "answers": [
                {
                    "fact": cleaned_raw,
                    "sources": []
                }
            ]
        }