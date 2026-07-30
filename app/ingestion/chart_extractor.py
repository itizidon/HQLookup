# app/ingestion/chart_extractor.py

import openpyxl
from typing import List, Dict, Any
from .models import ExtractedChart, ChartSeries


def extract_charts_from_worksheet(ws: openpyxl.worksheet.worksheet.Worksheet) -> List[ExtractedChart]:
    """Phase 11a: Reads embedded openpyxl charts from a worksheet."""
    extracted_charts = []

    # openpyxl stores charts in ws._charts
    for idx, chart in enumerate(getattr(ws, "_charts", [])):
        title = "Untitled Chart"
        if hasattr(chart, "title") and chart.title:
            # Title can be a string or a Title object with text
            title = str(chart.title.text) if hasattr(chart.title, "text") else str(chart.title)

        chart_type = chart.__class__.__name__.replace("Chart", "").lower()
        
        x_title = getattr(getattr(chart, "x_axis", None), "title", None)
        y_title = getattr(getattr(chart, "y_axis", None), "title", None)

        series_list = []
        for s in getattr(chart, "series", []):
            s_title = str(s.title) if hasattr(s, "title") and s.title else "Series"
            
            # Extract raw categories (X) and values (Y) if cached
            cats = list(s.categories.values) if hasattr(s, "categories") and s.categories else []
            vals = list(s.values.values) if hasattr(s, "values") and s.values else []
            
            series_list.append(ChartSeries(
                title=s_title,
                categories=cats,
                values=vals
            ))

        extracted_charts.append(ExtractedChart(
            chart_id=f"{ws.title}_chart_{idx}",
            sheet_name=ws.title,
            title=title,
            chart_type=chart_type,
            x_axis_title=str(x_title) if x_title else None,
            y_axis_title=str(y_title) if y_title else None,
            series=series_list
        ))

    return extracted_charts