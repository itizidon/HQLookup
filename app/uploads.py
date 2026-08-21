"""Streaming and structural validation for untrusted document uploads."""

from __future__ import annotations

import codecs
from dataclasses import dataclass
import csv
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ElementTree
import zipfile

from fastapi import UploadFile

from app.settings import settings


ALLOWED_EXTENSIONS = {".csv", ".docx", ".md", ".pdf", ".txt", ".xls", ".xlsm", ".xlsx"}
_ZIP_EXTENSIONS = {".docx", ".xlsm", ".xlsx"}
_TEXT_EXTENSIONS = {".csv", ".md", ".txt"}
_OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
_CHUNK_SIZE = 1024 * 1024
_MAX_ARCHIVE_ENTRIES = 10_000


class UnsafeUpload(ValueError):
    """Raised when an upload violates structural or resource limits."""


@dataclass(frozen=True)
class StoredUpload:
    path: str
    filename: str
    extension: str
    size_bytes: int


def _validate_archive(path: str, extension: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > _MAX_ARCHIVE_ENTRIES:
                raise UnsafeUpload("Archive contains too many entries")

            total_uncompressed = sum(entry.file_size for entry in entries)
            total_compressed = sum(entry.compress_size for entry in entries)
            max_uncompressed = settings.max_archive_uncompressed_mb * 1024 * 1024
            if total_uncompressed > max_uncompressed:
                raise UnsafeUpload("Archive expands beyond the configured limit")
            if total_uncompressed and total_uncompressed / max(total_compressed, 1) > settings.max_archive_ratio:
                raise UnsafeUpload("Archive compression ratio exceeds the configured limit")
            if any(entry.file_size > max_uncompressed for entry in entries):
                raise UnsafeUpload("Archive entry expands beyond the configured limit")
            if any(
                entry.file_size
                and entry.file_size / max(entry.compress_size, 1) > settings.max_archive_ratio
                for entry in entries
            ):
                raise UnsafeUpload("Archive entry compression ratio exceeds the configured limit")

            names = {entry.filename for entry in entries}
            if "[Content_Types].xml" not in names:
                raise UnsafeUpload("Office archive is missing its content manifest")
            if extension == ".docx" and not any(name.startswith("word/") for name in names):
                raise UnsafeUpload("DOCX archive is missing document content")
            if extension in {".xlsx", ".xlsm"} and not any(
                name.startswith("xl/") for name in names
            ):
                raise UnsafeUpload("Excel archive is missing workbook content")
    except zipfile.BadZipFile as exc:
        raise UnsafeUpload("Office upload is not a valid ZIP archive") from exc


def _validate_signature(path: str, extension: str) -> None:
    with open(path, "rb") as stream:
        sample = stream.read(8192)

    if extension == ".pdf" and not sample.startswith(b"%PDF-"):
        raise UnsafeUpload("PDF signature does not match its extension")
    if extension == ".xls" and not sample.startswith(_OLE_SIGNATURE):
        raise UnsafeUpload("XLS signature does not match its extension")
    if extension in _TEXT_EXTENSIONS:
        if b"\x00" in sample:
            raise UnsafeUpload("Text upload contains binary data")
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnsafeUpload("Text uploads must use UTF-8 encoding") from exc
    if extension in _ZIP_EXTENSIONS:
        _validate_archive(path, extension)


def count_spreadsheet_rows(path: str, extension: str, *, stop_after: int) -> int:
    """Count spreadsheet data rows without loading an entire workbook in memory.

    The function stops as soon as it can prove that the configured limit was
    exceeded.  For Office Open XML files, counting the worksheet ``row`` nodes
    also avoids trusting attacker-controlled worksheet dimensions.
    """

    if stop_after < 0:
        raise ValueError("stop_after must be non-negative")

    try:
        if extension == ".csv":
            with open(path, "r", encoding="utf-8-sig", newline="") as source:
                rows = csv.reader(source)
                next(rows, None)  # The application treats the first row as a header.
                count = 0
                for _ in rows:
                    count += 1
                    if count > stop_after:
                        return count
                return count

        if extension in {".xlsx", ".xlsm"}:
            count = 0
            with zipfile.ZipFile(path) as archive:
                worksheet_names = sorted(
                    name
                    for name in archive.namelist()
                    if name.startswith("xl/worksheets/") and name.endswith(".xml")
                )
                for worksheet_name in worksheet_names:
                    with archive.open(worksheet_name) as worksheet:
                        for _, element in ElementTree.iterparse(worksheet, events=("end",)):
                            if element.tag.rsplit("}", 1)[-1] == "row":
                                count += 1
                                if count > stop_after:
                                    return count
                            element.clear()
            return count

        if extension == ".xls":
            import xlrd

            workbook = xlrd.open_workbook(path, on_demand=True)
            try:
                count = sum(workbook.sheet_by_index(index).nrows for index in range(workbook.nsheets))
            finally:
                workbook.release_resources()
            return count
    except UnsafeUpload:
        raise
    except Exception as exc:
        raise UnsafeUpload("Unable to validate spreadsheet row limit") from exc

    return 0


def store_upload(
    upload: UploadFile,
    *,
    max_file_bytes: int,
    max_remaining_bytes: int,
) -> StoredUpload:
    """Stream an UploadFile to a mode-0600 temp file and validate it."""

    filename = Path(upload.filename or "").name
    extension = Path(filename).suffix.lower()
    if (
        not filename
        or len(filename) > 255
        or any(ord(character) < 32 for character in filename)
        or extension not in ALLOWED_EXTENSIONS
    ):
        raise UnsafeUpload("Unsupported file type")

    maximum = min(max_file_bytes, max_remaining_bytes)
    if maximum <= 0:
        raise UnsafeUpload("Aggregate upload limit exceeded")

    path: str | None = None
    size = 0
    text_decoder = (
        codecs.getincrementaldecoder("utf-8")()
        if extension in _TEXT_EXTENSIONS
        else None
    )
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix="hqlookup-upload-",
            suffix=extension,
            delete=False,
        ) as destination:
            path = destination.name
            while True:
                chunk = upload.file.read(_CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > maximum:
                    raise UnsafeUpload("Upload exceeds the configured size limit")
                if text_decoder is not None:
                    if b"\x00" in chunk:
                        raise UnsafeUpload("Text upload contains binary data")
                    try:
                        text_decoder.decode(chunk)
                    except UnicodeDecodeError as exc:
                        raise UnsafeUpload("Text uploads must use UTF-8 encoding") from exc
                destination.write(chunk)

            if text_decoder is not None:
                try:
                    text_decoder.decode(b"", final=True)
                except UnicodeDecodeError as exc:
                    raise UnsafeUpload("Text uploads must use UTF-8 encoding") from exc

        if size == 0:
            raise UnsafeUpload("Upload is empty")
        _validate_signature(path, extension)
        return StoredUpload(
            path=path,
            filename=filename,
            extension=extension,
            size_bytes=size,
        )
    except Exception:
        if path:
            Path(path).unlink(missing_ok=True)
        raise
    finally:
        upload.file.close()
