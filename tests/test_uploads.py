from io import BytesIO
from pathlib import Path
import zipfile

import pytest
from starlette.datastructures import UploadFile

from app.uploads import UnsafeUpload, count_spreadsheet_rows, store_upload


def _upload(name: str, payload: bytes) -> UploadFile:
    return UploadFile(file=BytesIO(payload), filename=name)


def test_store_upload_streams_and_validates_pdf():
    stored = store_upload(
        _upload("report.pdf", b"%PDF-1.7\nsmall test document"),
        max_file_bytes=1024,
        max_remaining_bytes=1024,
    )
    try:
        assert stored.filename == "report.pdf"
        assert stored.size_bytes > 0
        assert Path(stored.path).stat().st_mode & 0o777 == 0o600
    finally:
        Path(stored.path).unlink(missing_ok=True)


def test_store_upload_rejects_mismatched_signature():
    with pytest.raises(UnsafeUpload, match="signature"):
        store_upload(
            _upload("report.pdf", b"not a pdf"),
            max_file_bytes=1024,
            max_remaining_bytes=1024,
        )


def test_store_upload_enforces_limit_while_streaming():
    with pytest.raises(UnsafeUpload, match="size limit"):
        store_upload(
            _upload("notes.txt", b"a" * 32),
            max_file_bytes=16,
            max_remaining_bytes=16,
        )


def test_store_upload_validates_the_entire_text_stream():
    with pytest.raises(UnsafeUpload, match="binary data"):
        store_upload(
            _upload("notes.txt", b"a" * 9000 + b"\x00hidden-binary"),
            max_file_bytes=20_000,
            max_remaining_bytes=20_000,
        )


def test_store_upload_accepts_minimal_structural_xlsx():
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("xl/workbook.xml", "<workbook />")

    stored = store_upload(
        _upload("workbook.xlsx", payload.getvalue()),
        max_file_bytes=4096,
        max_remaining_bytes=4096,
    )
    Path(stored.path).unlink(missing_ok=True)


def test_xlsx_row_count_stops_after_limit():
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("xl/workbook.xml", "<workbook />")
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            "<worksheet><sheetData><row/><row/><row/></sheetData></worksheet>",
        )

    stored = store_upload(
        _upload("workbook.xlsx", payload.getvalue()),
        max_file_bytes=4096,
        max_remaining_bytes=4096,
    )
    try:
        assert count_spreadsheet_rows(stored.path, ".xlsx", stop_after=1) == 2
    finally:
        Path(stored.path).unlink(missing_ok=True)
