"""Integration coverage for spreadsheet chunk specs at the RAG persistence seam."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference

from app import rag
from app.services import spreadsheet_ingestion as ingestion


class _EncodedRows:
    def __init__(self, rows: list[list[float]]) -> None:
        self.rows = rows

    def tolist(self) -> list[list[float]]:
        return self.rows


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []

    def encode(self, texts, **kwargs) -> _EncodedRows:
        copied_texts = list(texts)
        self.calls.append((copied_texts, kwargs))
        return _EncodedRows([[float(index)] * 384 for index, _ in enumerate(copied_texts)])


class RecordingSession:
    def __init__(self) -> None:
        self.added: list = []
        self.commits = 0

    def add_all(self, objects) -> None:
        self.added.extend(objects)

    def commit(self) -> None:
        self.commits += 1


def _workbook_with_line_chart(path: Path) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(["Month", "Revenue"])
    sheet.append(["Jan", 100])
    sheet.append(["Feb", 120])
    sheet.append(["Mar", 150])

    chart = LineChart()
    chart.title = "Monthly Revenue"
    chart.add_data(
        Reference(sheet, min_col=2, min_row=1, max_row=4),
        titles_from_data=True,
    )
    chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=4))
    sheet.add_chart(chart, "E2")
    workbook.save(path)
    return path


def test_ingest_document_persists_normalized_spreadsheet_chunks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = _workbook_with_line_chart(tmp_path / "revenue.xlsx")
    analysis = {
        "spreadsheet_summary": "Monthly revenue workbook.",
        "tables": [
            {
                "sheet_name": "Data",
                "table_name": "Monthly Revenue",
                "cell_range": "A1:B4",
                "column_headers": ["Month", "Revenue"],
                "description": "Revenue by month.",
            }
        ],
        "visual_semantics": [
            {
                "visual_id": "Data:chart:0",
                "name": "Monthly Revenue",
                "description": "Monthly revenue trend.",
                "x_axis_semantic": "Month",
                "y_axis_semantic": "Revenue",
                "unit": "USD",
            }
        ],
        "key_findings": ["Revenue increased each month."],
    }

    def build_without_external_llm(file_path: str, filename: str, **_kwargs):
        return ingestion.build_spreadsheet_chunk_specs(
            file_path,
            filename,
            analysis=analysis,
        )

    embedder = FakeEmbedder()
    session = RecordingSession()
    monkeypatch.setattr(rag, "get_embedder", lambda: embedder)
    monkeypatch.setattr(
        rag,
        "build_spreadsheet_chunk_specs",
        build_without_external_llm,
    )

    count = rag.ingest_document(
        session,
        business_id=7,
        document_id=11,
        file_path=str(path),
        filename=path.name,
    )

    assert count == 9
    assert len(session.added) == 9
    assert session.commits == 1
    assert len(embedder.calls) == 1
    embedded_texts, encode_options = embedder.calls[0]
    assert embedded_texts == [chunk.text for chunk in session.added]
    assert encode_options == {
        "show_progress_bar": False,
        "normalize_embeddings": True,
    }

    assert [chunk.chunk_index for chunk in session.added] == list(range(9))
    assert all(chunk.business_id == 7 for chunk in session.added)
    assert all(chunk.document_id == 11 for chunk in session.added)

    by_type: dict[str, list] = {}
    for chunk in session.added:
        by_type.setdefault(chunk.chunk_type, []).append(chunk)
    assert {key: len(value) for key, value in by_type.items()} == {
        "tabular_record": 3,
        "workbook_metadata": 2,
        "chart_metadata": 1,
        "chart_datapoint": 3,
    }
    assert all(chunk.content_type == "tabular" for chunk in by_type["tabular_record"])
    assert all(
        chunk.content_type == "metadata"
        for kind in ("workbook_metadata", "chart_metadata", "chart_datapoint")
        for chunk in by_type[kind]
    )

    march = next(
        chunk
        for chunk in by_type["chart_datapoint"]
        if "Category: Mar" in chunk.text
    )
    assert "Series: Revenue" in march.text
    assert "Value: 150" in march.text
    assert "X Axis: Month" in march.parent_text
    assert "Y Axis: Revenue" in march.parent_text
    assert "Unit: USD" in march.parent_text


def test_ingest_document_forwards_notes_to_spreadsheet_builder(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = _workbook_with_line_chart(tmp_path / "noted-revenue.xlsx")
    captured: dict[str, object] = {}

    def record_build(file_path: str, filename: str, **kwargs):
        captured.update(
            {
                "file_path": file_path,
                "filename": filename,
                **kwargs,
            }
        )
        return [
            {
                "text": "Sheet: Data\nMonth: Jan | Revenue: 100",
                "parent": "Sheet: Data\nMonth: Jan | Revenue: 100",
                "chunk_type": "tabular_record",
                "content_type": "tabular",
            }
        ]

    session = RecordingSession()
    monkeypatch.setattr(rag, "get_embedder", lambda: FakeEmbedder())
    monkeypatch.setattr(rag, "build_spreadsheet_chunk_specs", record_build)

    count = rag.ingest_document(
        session,
        business_id=7,
        document_id=11,
        file_path=str(path),
        filename=path.name,
        ingestion_notes="The first three rows are KPI summary cards.",
    )

    assert count == 1
    assert captured == {
        "file_path": str(path),
        "filename": path.name,
        "client": rag.client,
        "ingestion_notes": "The first three rows are KPI summary cards.",
    }
