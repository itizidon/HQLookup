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
def build_prompt(question: str, chunks: List[dict], task_type: str = "general") -> str:
    context_blocks = []

    for i, chunk in enumerate(chunks, 1):
        context_blocks.append(
            f"""
CHUNK {i}
FILE: {chunk["filename"]}
Score: {chunk["score"]}

{chunk["parent_text"] or chunk["text"]}
""".strip()
        )

    context = "\n\n=============================\n\n".join(context_blocks)

    return f"""
You are a document retrieval assistant.

Your job is to answer the user's question ONLY using the provided context.

----------------------------
PRIMARY OBJECTIVE
----------------------------

First determine what information the user is actually asking for.

Then locate ONLY the data that answers that question.

Do NOT extract unrelated information.

----------------------------
VERY IMPORTANT
----------------------------

Many documents contain repeated information.

Many retrieved chunks overlap.

If multiple chunks describe the same thing:

• Return ONE answer
• Merge the sources
• Never repeat the same fact twice

----------------------------
SPREADSHEETS
----------------------------

If the context comes from a spreadsheet:

1. Determine which column answers the question.

Example:

Question:
How much did Dr. Sue charge?

Correct column:
Price

Incorrect columns:
Invoice Number
Procedure ID
Patient Number
Row Number

Never return values from the wrong column.

----------------------------
TABLES
----------------------------

Treat every row as one logical record.

Do NOT split one row into multiple answers.

Do NOT combine different rows together.

----------------------------
TEXT DOCUMENTS
----------------------------

If multiple paragraphs describe the same protocol,
procedure,
policy,
or instruction,

return ONE combined answer.

----------------------------
OUTPUT RULES
----------------------------

Return ONLY valid JSON.

No markdown.

No explanations.

Return this format:

{{
    "answers": [
        {{
            "fact": "...",
            "sources": [
                {{
                    "chunk": 1,
                    "filename": "example.pdf"
                }}
            ]
        }}
    ]
}}

Requirements:

• Every answer must be unique.
• Never repeat the same fact.
• Merge duplicate information.
• Merge overlapping information.
• Prefer the most complete version.
• If the answer cannot be found return

{{"answers":[]}}

----------------------------
CONTEXT
----------------------------

{context}

----------------------------
QUESTION
----------------------------

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