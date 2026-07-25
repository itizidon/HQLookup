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
            f"[{i}] FILE: {chunk['filename']} (Score: {chunk['score']})\n{chunk['text'].strip()}"
        )

    context = "\n\n---\n\n".join(context_blocks)

    # Optional rule injection for strict financial parsing
    extra_requirements = ""
    if task_type == "transactions":
        extra_requirements = """
- Extract each matching financial transaction as an individual array object.
- Keep charges and dollar values separated per item.
"""

    return f"""
You are a retrieval assistant. Answer the user's question using ONLY the provided context.

IMPORTANT RULES:
- Return ONLY valid JSON.
- Do NOT include markdown code fences (no ```json).
- Do NOT include explanations outside the JSON.
- If the answer is not found in the context, return: {{"answers": []}}

Return format:
{{
  "answers": [
    {{
      "fact": "short factual statement",
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
- Extract ONLY facts that directly answer the user's prompt. Filter out irrelevant data.
- Each distinct answer item should be its own array object.
- Combine duplicate facts across multiple chunks into a single item.
- Do not hallucinate or invent details not in the context.
{extra_requirements}
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