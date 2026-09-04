"""Regression coverage for document-upload request metadata."""

from __future__ import annotations

import json
from io import BytesIO
from types import SimpleNamespace

from starlette.datastructures import UploadFile

from app import main as main_app
from app.models import Document
from app.uploads import StoredUpload


class RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.rollbacks = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        document = self.added[-1]
        assert isinstance(document, Document)
        document.id = 16 + len(self.added)

    def rollback(self) -> None:
        self.rollbacks += 1


def _configure_route(
    monkeypatch,
    business,
    stored_uploads: list[StoredUpload],
    ingestion_calls: list[dict[str, object]],
) -> None:
    stored_iterator = iter(stored_uploads)

    monkeypatch.setattr(
        main_app,
        "require_business_access",
        lambda _db, _user, _business_id: business,
    )
    monkeypatch.setattr(main_app, "limit_document_upload", lambda _user_id: None)
    monkeypatch.setattr(
        main_app,
        "get_billing_owner",
        lambda _db, _organization: SimpleNamespace(plan="free"),
    )
    monkeypatch.setattr(
        main_app,
        "store_upload",
        lambda *_args, **_kwargs: next(stored_iterator),
    )
    monkeypatch.setattr(
        main_app,
        "count_spreadsheet_rows",
        lambda *_args, **_kwargs: 2,
    )

    def record_ingestion(**kwargs) -> int:
        ingestion_calls.append(kwargs)
        return 3

    monkeypatch.setattr(main_app, "ingest_document", record_ingestion)
    monkeypatch.setattr(main_app, "clear_active_query", lambda _user_id: None)


def test_upload_multiple_forwards_xlsx_ingestion_notes(
    tmp_path,
    monkeypatch,
) -> None:
    upload_path = tmp_path / "forecast.xlsx"
    upload_path.write_bytes(b"stored workbook")
    stored = StoredUpload(
        path=str(upload_path),
        filename="forecast.xlsx",
        extension=".xlsx",
        size_bytes=15,
    )
    business = SimpleNamespace(id=9, organization=object())
    user = SimpleNamespace(id=4)
    session = RecordingSession()
    ingestion_calls: list[dict[str, object]] = []
    _configure_route(monkeypatch, business, [stored], ingestion_calls)

    result = main_app.upload_documents(
        business_id=business.id,
        file_contexts=json.dumps(
            {"forecast.xlsx": "  Yellow cells indicate pending approval.  "}
        ),
        current_context=(user, None),
        files=[UploadFile(file=BytesIO(b"request body"), filename="forecast.xlsx")],
        db=session,
    )

    expected_notes = "Yellow cells indicate pending approval."
    assert ingestion_calls == [
        {
            "db": session,
            "business_id": business.id,
            "document_id": 17,
            "file_path": str(upload_path),
            "filename": "forecast.xlsx",
            "ingestion_notes": expected_notes,
        }
    ]
    assert len(session.added) == 1
    document = session.added[0]
    assert isinstance(document, Document)
    assert document.description == expected_notes
    assert session.rollbacks == 0
    assert result == {
        "uploaded": [
            {
                "filename": "forecast.xlsx",
                "document_id": 17,
                "chunks": 3,
            }
        ]
    }
    assert not upload_path.exists()


def test_upload_multiple_aligns_notes_when_filenames_are_identical(
    tmp_path,
    monkeypatch,
) -> None:
    first_path = tmp_path / "first-copy.xlsx"
    second_path = tmp_path / "second-copy.xlsx"
    first_path.write_bytes(b"first workbook")
    second_path.write_bytes(b"second workbook")
    stored_uploads = [
        StoredUpload(
            path=str(first_path),
            filename="forecast.xlsx",
            extension=".xlsx",
            size_bytes=14,
        ),
        StoredUpload(
            path=str(second_path),
            filename="forecast.xlsx",
            extension=".xlsx",
            size_bytes=15,
        ),
    ]
    business = SimpleNamespace(id=9, organization=object())
    user = SimpleNamespace(id=4)
    session = RecordingSession()
    ingestion_calls: list[dict[str, object]] = []
    _configure_route(monkeypatch, business, stored_uploads, ingestion_calls)

    result = main_app.upload_documents(
        business_id=business.id,
        file_contexts=json.dumps(["First workbook note", "Second workbook note"]),
        current_context=(user, None),
        files=[
            UploadFile(file=BytesIO(b"first"), filename="forecast.xlsx"),
            UploadFile(file=BytesIO(b"second"), filename="forecast.xlsx"),
        ],
        db=session,
    )

    assert [call["ingestion_notes"] for call in ingestion_calls] == [
        "First workbook note",
        "Second workbook note",
    ]
    assert [document.description for document in session.added] == [
        "First workbook note",
        "Second workbook note",
    ]
    assert [item["document_id"] for item in result["uploaded"]] == [17, 18]
    assert not first_path.exists()
    assert not second_path.exists()
