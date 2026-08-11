"""
LLM service.

Supports:

1. Spreadsheet/tabular chunks
   - one explicit decision per row/chunk
   - MATCH / NO MATCH
   - natural-language string answers

2. Normal text documents
   - PDF
   - TXT
   - DOCX
   - Markdown
   - metadata / other text
   - normal multi-chunk RAG synthesis

All user-facing answers are returned as strings.
"""

import json
import logging
import re
from typing import List

from openai import OpenAI
from app.settings import settings

logger = logging.getLogger(__name__)


# ── Client configuration ──────────────────────────────────────────────────────

client = OpenAI(
    base_url=settings.llm_base_url,
    api_key=settings.openai_api_key.get_secret_value(),
    timeout=settings.llm_timeout_seconds,
    max_retries=2,
)

LLM_MODEL = settings.llm_model


# ── JSON cleanup ──────────────────────────────────────────────────────────────

def clean_json_response(raw_text: str) -> str:
    """
    Removes markdown code fences if the model outputs them.
    """

    if not raw_text:
        return ""

    cleaned = raw_text.strip()

    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\s*```$",
        "",
        cleaned,
    )

    return cleaned.strip()


# ── Shared context builder ────────────────────────────────────────────────────

def build_context(
    chunks: List[dict],
) -> str:

    context_blocks = []

    for i, chunk in enumerate(chunks, 1):

        context_blocks.append(
            f"""[{i}]
FILE: {chunk.get("filename", "unknown")}
CHUNK ID: {chunk.get("id", i)}
CONTENT TYPE: {chunk.get("content_type", "unknown")}
CHUNK TYPE: {chunk.get("chunk_type", "unknown")}
SCORE: {chunk.get("score", "unknown")}

{chunk.get("text", "")}
"""
        )

    return "\n\n---\n\n".join(
        context_blocks
    )


# ── Spreadsheet prompt ────────────────────────────────────────────────────────

def build_tabular_prompt(
    question: str,
    chunks: List[dict],
) -> str:

    context = build_context(
        chunks
    )

    # Build JSON examples with Python so literal braces do not
    # interfere with f-string formatting.

    output_example = {
        "records": [
            {
                "chunk_id": 17,
                "matches": True,
                "answer": (
                    "This record answers the user's question. "
                    "Include the relevant values from this row "
                    "in a clear, readable response."
                ),
                "confidence": 0.98,
                "sources": [
                    {
                        "chunk": 17,
                        "filename": "example.xlsx",
                    }
                ],
            },
            {
                "chunk_id": 18,
                "matches": False,
                "answer": None,
                "confidence": 0.0,
                "sources": [],
            },
        ]
    }

    output_example_json = json.dumps(
        output_example,
        indent=2,
    )

    return f"""
You are a precise spreadsheet retrieval assistant.

Answer the user's question using ONLY the provided spreadsheet context.


GENERAL RULES:

1. Return ONLY valid JSON.

2. Do not return markdown.

3. Do not hallucinate information.

4. Preserve important values from the context accurately.

5. Every answer must be supported by the provided spreadsheet row.

6. Confidence must be between 0.0 and 1.0.


SPREADSHEET RECORD RULES:

7. Every tabular context block represents ONE independent
   spreadsheet record.

8. Evaluate every provided tabular record independently.

9. Never combine values from different spreadsheet rows.

10. Never move a value from one row into another row.

11. Keep fields from the same row associated with that row.

12. Do NOT assume that any business field uniquely identifies
    a spreadsheet row.

Fields that may legitimately repeat include, but are not limited to:

- statement numbers
- invoice numbers
- order numbers
- claim IDs
- customer names
- provider names
- employee names
- dates
- categories
- account numbers

13. If two rows contain different Row Data, treat them as
    different records even if some values are identical.

14. Only consider two records duplicates if they literally refer
    to the same retrieved CHUNK ID.


PER-CHUNK DECISION RULES:

15. Return exactly ONE decision for EVERY provided tabular CHUNK ID.

16. Every provided tabular CHUNK ID must appear exactly once in
    the "records" array.

17. If a row contains information that answers the user's question:

    "matches": true

18. If a row does NOT answer the user's question:

    "matches": false

    and:

    "answer": null

19. Never silently omit a provided spreadsheet row.

20. A row returning "matches": false is completely valid.

21. Always copy the exact CHUNK ID from the context into
    the "chunk_id" field.

22. Do not generate an answer for an irrelevant row merely to
    satisfy the one-decision-per-row requirement.


ANSWER FORMAT RULES:

23. When "matches" is true, "answer" MUST be a string.

24. "answer" must NOT be a JSON object.

25. "answer" must NOT be an array.

26. Write a clear, natural-language response.

27. The answer may be:

- one sentence
- multiple sentences
- a short paragraph
- another concise natural-language format

Use whatever is clearest for the user's question.

28. Do NOT force the response into exactly one sentence.

29. Include all information explicitly requested by the user
    when that information exists in the matching row.

30. Do not omit a requested value that is present in the row.

31. Do not include unrelated spreadsheet fields merely because
    they exist.

32. Preserve the meaning and association of the row's fields.

33. The wording may be natural and conversational as long as the
    factual values remain grounded in the row.


FIELD SELECTION:

34. Use the spreadsheet headers and Row Data to determine which
    values answer the user's question.

35. Do not assume all spreadsheets use the same column names.

36. Determine field meaning semantically.

For example:

- "charged" may refer to a billed or charged amount
- "paid" may refer to an amount paid
- "balance" may refer to an amount due
- "order number" may correspond to an order/reference identifier

Use the actual available headers and row values.

37. If the requested value does not exist in the row, do not
    invent it.


FIELD ASSOCIATION:

38. Every value used in an answer must come from the SAME
    spreadsheet record.

39. Never take one field from one row and another field from a
    different row to construct a spreadsheet-record answer.


EXAMPLE:

Suppose the user asks:

"How much did Dr. Sue charge for office visits?
Include the date and statement number."

And one row contains:

Provider Name: Dr. Sue
Description of Services: Office Visit
Total Amount Billed: 525
Bill Date: 2025-01-12
Statement Number: 1240

A valid answer could be:

"Dr. Sue charged $525 for the office visit on 2025-01-12.
The statement number is 1240."

This is also valid:

"Dr. Sue charged $525 for the office visit on 2025-01-12
with statement number 1240."

Both are acceptable because the answer is natural-language text.

Do NOT return this as the answer value:

{{
    "Provider Name": "Dr. Sue",
    "Bill Date": "2025-01-12",
    "Statement Number": "1240",
    "Total Amount Billed": 525
}}

The "answer" field itself must remain a string.


OUTPUT FORMAT:

{output_example_json}


IMPORTANT:

Every provided spreadsheet CHUNK ID must receive exactly one decision.

Matching record:

"matches": true
"answer": "Readable natural-language response."

Non-matching record:

"matches": false
"answer": null


CONTEXT:

{context}


QUESTION:

{question}
""".strip()


# ── Normal text/PDF/DOCX prompt ───────────────────────────────────────────────

def build_text_prompt(
    question: str,
    chunks: List[dict],
) -> str:

    context = build_context(
        chunks
    )

    output_example = {
        "answers": [
            {
                "answer": (
                    "The relevant information from the provided "
                    "documents can be synthesized into a clear "
                    "natural-language response."
                ),
                "confidence": 0.95,
                "sources": [
                    {
                        "chunk": 10,
                        "filename": "document.pdf",
                    },
                    {
                        "chunk": 11,
                        "filename": "document.pdf",
                    },
                ],
            }
        ]
    }

    output_example_json = json.dumps(
        output_example,
        indent=2,
    )

    return f"""
You are a precise retrieval assistant.

Answer the user's question using ONLY the provided document context.


GENERAL RULES:

1. Return ONLY valid JSON.

2. Do not return markdown.

3. Do not hallucinate information.

4. Every answer must be supported by the provided context.

5. Preserve important names, dates, amounts, identifiers,
   quotations, and factual values accurately.

6. Confidence must be between 0.0 and 1.0.


TEXT DOCUMENT RULES:

7. These chunks may come from:

- PDF files
- TXT files
- DOCX files
- Markdown files
- document metadata
- other normal text documents

8. Text chunks are NOT independent spreadsheet records.

9. Multiple text chunks may contain different pieces of information
   that together answer the user's question.

10. You MAY synthesize information across multiple relevant text
    chunks when they jointly support the answer.

11. Do NOT return one answer per chunk merely because multiple
    chunks were supplied.

12. Ignore chunks that do not help answer the question.

13. If one natural response can combine the relevant information,
    prefer a coherent synthesized response.

14. Multiple answer objects may be returned when the question
    naturally has multiple distinct answers.

15. If none of the provided context supports an answer, return:

    "answers": []


ANSWER FORMAT:

16. The "answer" field MUST be a string.

17. The "answer" field must NOT be a JSON object.

18. The "answer" field must NOT be an array.

19. Use clear natural language.

20. The answer may be:

- one sentence
- multiple sentences
- one or more short paragraphs

Use whatever format communicates the answer clearly.

21. Do NOT force the answer into exactly one sentence.

22. Include relevant information explicitly requested by the user
    when the context supports it.


SOURCES:

23. Cite only chunks that actually support the answer.

24. One answer may cite multiple chunks.

25. Use the exact CHUNK IDs and filenames from the context.


OUTPUT FORMAT:

{output_example_json}


CONTEXT:

{context}


QUESTION:

{question}
""".strip()


# ── OpenAI call ───────────────────────────────────────────────────────────────

def call_openai(
    prompt: str,
) -> str:

    response = client.chat.completions.create(
        model=LLM_MODEL,
        response_format={
            "type": "json_object",
        },
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise retrieval assistant. "
                    "Return strictly valid JSON. "
                    "Never use information outside the supplied context."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.2,
    )

    content = response.choices[0].message.content

    if content is None:
        return ""

    return content


# ── Shared JSON parser ────────────────────────────────────────────────────────

def parse_llm_json(
    raw: str,
) -> dict:

    cleaned_raw = clean_json_response(
        raw
    )

    try:
        parsed = json.loads(
            cleaned_raw
        )

    except json.JSONDecodeError as exc:

        logger.warning("LLM response was not valid JSON: %s", exc.__class__.__name__)

        return {}

    if not isinstance(
        parsed,
        dict,
    ):
        logger.warning("LLM response was not a JSON object")

        return {}

    return parsed


# ── Spreadsheet generation ────────────────────────────────────────────────────

def generate_tabular_answer(
    question: str,
    chunks: List[dict],
) -> dict:

    if not chunks:
        return {
            "records": [],
        }

    prompt = build_tabular_prompt(
        question,
        chunks,
    )

    raw = call_openai(
        prompt
    )

    parsed = parse_llm_json(
        raw
    )

    records = parsed.get(
        "records"
    )

    if not isinstance(
        records,
        list,
    ):
        logger.warning("Tabular LLM response did not contain a valid records array")

        return {
            "records": [],
        }

    return {
        "records": records,
    }


# ── Normal text generation ────────────────────────────────────────────────────

def generate_text_answer(
    question: str,
    chunks: List[dict],
) -> dict:

    if not chunks:
        return {
            "answers": [],
        }

    prompt = build_text_prompt(
        question,
        chunks,
    )

    raw = call_openai(
        prompt
    )

    parsed = parse_llm_json(
        raw
    )

    answers = parsed.get(
        "answers"
    )

    if not isinstance(
        answers,
        list,
    ):
        logger.warning("Text LLM response did not contain a valid answers array")

        return {
            "answers": [],
        }

    return {
        "answers": answers,
    }


# ── Public interface ──────────────────────────────────────────────────────────

def generate_answer(
    question: str,
    chunks: List[dict],
) -> dict:
    """
    Routes retrieved chunks according to content type.

    Tabular chunks:
        one explicit MATCH / NO MATCH decision per row.

    Normal text chunks:
        normal multi-chunk RAG synthesis.

    Returns:

    {
        "records": [...],
        "answers": [...]
    }
    """

    tabular_chunks = [
        chunk
        for chunk in chunks
        if chunk.get("content_type") == "tabular"
    ]

    text_chunks = [
        chunk
        for chunk in chunks
        if chunk.get("content_type") != "tabular"
    ]

    result = {
        "records": [],
        "answers": [],
    }

    # ------------------------------------------------------------------
    # Spreadsheet rows
    # ------------------------------------------------------------------

    if tabular_chunks:

        tabular_result = generate_tabular_answer(
            question,
            tabular_chunks,
        )

        result["records"].extend(
            tabular_result.get(
                "records",
                [],
            )
        )

    # ------------------------------------------------------------------
    # PDF / TXT / DOCX / Markdown / metadata / other text
    # ------------------------------------------------------------------

    if text_chunks:

        text_result = generate_text_answer(
            question,
            text_chunks,
        )

        result["answers"].extend(
            text_result.get(
                "answers",
                [],
            )
        )

    return result
