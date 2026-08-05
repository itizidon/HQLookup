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
def build_prompt(question: str, chunks: List[dict]) -> str:
    context_blocks = []

    for i, chunk in enumerate(chunks, 1):
        context_blocks.append(
            f"""[{i}]
          FILE: {chunk['filename']}
          SCORE: {chunk['score']}
          {chunk['text']}
          """
        )

    context = "\n\n---\n\n".join(context_blocks)

    return f"""
You are a retrieval assistant.

Your task is to evaluate each retrieved context block independently.

Each context block is an independent candidate answer. Multiple context blocks may answer the user's question.

Use ONLY the provided context.

IMPORTANT RULES:

* Return ONLY valid JSON.
* Do NOT include markdown.
* Do NOT include explanations outside the JSON.
* Evaluate every context block independently.
* If a context block answers the user's question, return one answer object for that context block.
* NEVER merge multiple context blocks into one answer.
* NEVER summarize multiple spreadsheet rows into one answer.
* NEVER combine multiple matching records into one answer.
* If three different rows answer the question, return three separate answer objects.
* Preserve all values exactly as they appear in the context.
* Ignore context blocks that do not answer the user's question.
* Do not hallucinate.
* If no context answers the question, return:
  {{
  "answers": []
  }}

Return JSON in exactly this format:

{{
"answers": [
{{
"answer": "Complete answer taken from this context block.",
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

Guidelines:

* Each answer object should correspond to exactly ONE retrieved context block.
* Do not combine answers from different chunks.
* Multiple chunks may produce multiple answers.
* It is acceptable for different answers to contain similar information if they originate from different rows or records.
* Preserve dates, dollar amounts, IDs, names, and other values exactly as written.
* Confidence should be between 0.0 and 1.0.

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