# app/ingestion/chart_chunker.py

from typing import List, Any
from .models import ExtractedChart, RAGChunk, EnhancedChunkMetadata


def summarize_chart_trend(chart: ExtractedChart, llm_client: Any = None) -> str:
    """Uses LLM to summarize key findings and trends from the chart series data."""
    if not llm_client or not chart.series:
        return f"Chart titled '{chart.title}' illustrating {chart.chart_type} distribution."

    series_data_summary = []
    for s in chart.series:
        series_data_summary.append(f"Series: {s.title}\nCategories: {s.categories}\nValues: {s.values}")

    prompt = f"""
    You are an expert financial analyst. Summarize key trends in 2-3 sentences.
    Chart Title: {chart.title}
    Type: {chart.chart_type}
    X-Axis: {chart.x_axis_title or 'N/A'}, Y-Axis: {chart.y_axis_title or 'N/A'}
    Data:
    {chr(10).join(series_data_summary)}
    """

    try:
        response = llm_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return f"Visual trend summary for {chart.title}."


def create_chart_chunk(
    chart: ExtractedChart, 
    filename: str, 
    llm_client: Any = None
) -> RAGChunk:
    """Phase 11b: Builds a RAGChunk for an extracted chart."""
    
    trend_summary = summarize_chart_trend(chart, llm_client)

    # 1. Build Markdown Representation
    md_lines = [
        f"## Chart: {chart.title}",
        f"**Sheet:** {chart.sheet_name} | **Type:** {chart.chart_type.upper()}",
        f"**X-Axis:** {chart.x_axis_title or 'Categories'} | **Y-Axis:** {chart.y_axis_title or 'Values'}",
        "",
        f"### Key Trend Summary",
        trend_summary,
        "",
        f"### Series Data"
    ]

    # Append structured table representation of series
    for s in chart.series:
        md_lines.append(f"**Series Title:** {s.title}")
        if s.categories and s.values:
            pairs = [f"{c}: {v}" for c, v in zip(s.categories, s.values)]
            md_lines.append(" | ".join(pairs))
        md_lines.append("")

    content = "\n".join(md_lines)

    # 2. Attach Phase 8/9 Metadata
    metadata = {
        "file_name": filename,
        "sheet_name": chart.sheet_name,
        "table_name": chart.title,
        "entity_type": "Chart",
        "chunk_strategy": "SUMMARY",
        "confidence_score": 1.0,
        "business_context": trend_summary,
        "is_chart": True
    }

    return RAGChunk(
        chunk_id=f"chunk_{chart.chart_id}",
        content=content,
        metadata=metadata
    )