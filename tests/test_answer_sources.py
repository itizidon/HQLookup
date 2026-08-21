"""Tests for authoritative per-answer source attribution."""

from types import SimpleNamespace

from app import rag
import app.main as main_app
from app.main import AskRequest, resolve_answer_sources


class _Rows:
    def __init__(self, rows) -> None:
        self.rows = rows

    def fetchall(self):
        return self.rows


class _RetrievalSession:
    def __init__(self, rows_by_vector) -> None:
        self.rows_by_vector = iter(rows_by_vector)

    def execute(self, _statement, _params):
        return _Rows(next(self.rows_by_vector))


class _BusinessQuery:
    def __init__(self, business) -> None:
        self.business = business

    def filter(self, *_args):
        return self

    def first(self):
        return self.business


class _AskSession:
    def __init__(self, business) -> None:
        self.business = business
        self.added = []
        self.commits = 0

    def query(self, _model):
        return _BusinessQuery(self.business)

    def add(self, value) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1


def test_resolve_answer_sources_uses_retrieved_metadata_and_deduplicates() -> None:
    chunks = [
        {
            "id": 1,
            "filename": "first.pdf",
            "score": 0.99,
        },
        {
            "id": 12,
            "filename": "actual.xlsx",
            "score": 0.91234,
        },
        {
            "id": 13,
            "filename": "notes.pdf",
            "score": 0.0,
        },
    ]
    requested_sources = [
        {
            "chunk_id": "13",
            "filename": "hallucinated.pdf",
            "correlation": 1.0,
        },
        {
            "chunk": 13,
            "filename": "duplicate.pdf",
        },
        {
            "chunk": 999,
            "filename": "not-retrieved.pdf",
        },
        {
            "chunk": 12.9,
            "filename": "fractional-id.pdf",
        },
        {
            "chunk": True,
            "filename": "boolean-id.pdf",
        },
    ]

    assert resolve_answer_sources(chunks, requested_sources) == [
        {
            "chunk": 13,
            "filename": "notes.pdf",
            "correlation": 0.0,
        }
    ]


def test_resolve_answer_sources_falls_back_to_the_supplied_context() -> None:
    chunks = [
        {
            "id": 21,
            "filename": "policy.pdf",
            "score": 0.87654,
        },
        {
            "id": 22,
            "filename": "handbook.docx",
            "score": None,
        },
    ]

    assert resolve_answer_sources(
        chunks,
        None,
        fallback_to_all=True,
    ) == [
        {
            "chunk": 21,
            "filename": "policy.pdf",
            "correlation": 0.8765,
        },
        {
            "chunk": 22,
            "filename": "handbook.docx",
            "correlation": None,
        },
    ]


def test_resolve_answer_sources_does_not_fallback_unless_requested() -> None:
    chunks = [
        {
            "id": 31,
            "filename": "report.csv",
            "score": 0.7,
        }
    ]

    assert resolve_answer_sources(chunks, []) == []
    assert resolve_answer_sources(
        chunks,
        [{"chunk": 999}],
    ) == []


def test_multiquery_retrieval_keeps_the_strongest_correlation(
    monkeypatch,
) -> None:
    def row(score: float):
        return SimpleNamespace(
            id=41,
            text="Relevant policy text.",
            parent_text="Relevant policy text.",
            chunk_index=4,
            chunk_type="child",
            content_type="text",
            document_id=8,
            filename="policy.pdf",
            score=score,
        )

    session = _RetrievalSession([
        [row(0.61)],
        [row(0.87)],
    ])
    monkeypatch.setattr(rag, "get_embedder", lambda: object())

    result = rag.retrieve_chunks_multi(
        db=session,
        business_id=2,
        query="What is the policy?",
        get_k=5,
        vectors=[[0.1], [0.2]],
    )

    assert result["results"][0]["score"] == 0.87


def test_active_query_cache_key_is_versioned_for_source_metadata() -> None:
    assert rag.get_active_query_key(9) == "active_query:v2:9"


def test_ask_returns_and_caches_authoritative_per_answer_sources(
    monkeypatch,
) -> None:
    organization = SimpleNamespace(id=3)
    business = SimpleNamespace(
        id=2,
        organization=organization,
    )
    user = SimpleNamespace(
        id=9,
        plan="free",
    )
    session = _AskSession(business)
    chunks = [
        {
            "id": 101,
            "text": "Claim row.",
            "chunk_index": 7,
            "chunk_type": "tabular_record",
            "content_type": "tabular",
            "filename": "claims.xlsx",
            "score": 0.91,
        },
        {
            "id": 202,
            "text": "Policy section.",
            "chunk_index": 4,
            "chunk_type": "child",
            "content_type": "text",
            "filename": "policy.pdf",
            "score": 0.82,
        },
        {
            "id": 203,
            "text": "Handbook section.",
            "chunk_index": 8,
            "chunk_type": "child",
            "content_type": "text",
            "filename": "handbook.docx",
            "score": 0.74,
        },
    ]
    cached = {}

    monkeypatch.setattr(
        main_app,
        "require_business_access",
        lambda *_args, **_kwargs: business,
    )
    monkeypatch.setattr(
        main_app,
        "get_billing_owner",
        lambda *_args, **_kwargs: user,
    )
    monkeypatch.setattr(
        main_app,
        "get_business_doc_state",
        lambda *_args: {"document_count": 2, "latest_document_id": 8},
    )
    monkeypatch.setattr(
        main_app,
        "reserve_search",
        lambda *_args: (True, 1, 50),
    )
    monkeypatch.setattr(main_app, "limit_search", lambda *_args: None)
    monkeypatch.setattr(main_app, "get_active_query", lambda *_args: None)
    monkeypatch.setattr(
        main_app,
        "retrieve_chunks_multi",
        lambda **_kwargs: {
            "results": chunks,
            "vectors": [[0.1]],
        },
    )
    monkeypatch.setattr(
        main_app,
        "generate_answer",
        lambda *_args: {
            "records": [
                {
                    "chunk_id": 101,
                    "matches": True,
                    "answer": "Matching claim.",
                    "confidence": 0.96,
                    "sources": [
                        {
                            "chunk": 999,
                            "filename": "hallucinated.xlsx",
                        }
                    ],
                }
            ],
            "answers": [
                {
                    "answer": "Combined policy answer.",
                    "confidence": 0.88,
                    "sources": [
                        {
                            "chunk": "202",
                            "filename": "wrong-name.pdf",
                        },
                        {
                            "chunk": 203,
                            "filename": "also-wrong.docx",
                        },
                        {
                            "chunk": 999,
                            "filename": "not-retrieved.pdf",
                        },
                    ],
                }
            ],
        },
    )
    monkeypatch.setattr(
        main_app,
        "set_active_query",
        lambda **kwargs: cached.update(kwargs),
    )
    monkeypatch.setattr(
        main_app,
        "MAX_RETRIEVAL_SIZE",
        main_app.INITIAL_RETRIEVAL_SIZE,
    )

    response = main_app.ask_question(
        AskRequest(
            question="What applies?",
            business_id=2,
            get_k=5,
            offset=0,
        ),
        db=session,
        current_context=(user, None),
    )

    expected_answers = [
        {
            "answer": "Matching claim.",
            "confidence": 0.96,
            "sources": [
                {
                    "chunk": 101,
                    "filename": "claims.xlsx",
                    "correlation": 0.91,
                }
            ],
        },
        {
            "answer": "Combined policy answer.",
            "confidence": 0.88,
            "sources": [
                {
                    "chunk": 202,
                    "filename": "policy.pdf",
                    "correlation": 0.82,
                },
                {
                    "chunk": 203,
                    "filename": "handbook.docx",
                    "correlation": 0.74,
                },
            ],
        },
    ]

    assert response["answer"]["answers"] == expected_answers
    assert set(response["sources"]) == {
        "claims.xlsx",
        "policy.pdf",
        "handbook.docx",
    }
    assert cached["answers"] == expected_answers
