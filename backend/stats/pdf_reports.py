from __future__ import annotations

from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def draw_table_pdf(title: str, headers: List[str], rows: List[List[Any]]) -> bytes:
    from io import BytesIO
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=landscape(A4))
    width, height = landscape(A4)
    y = height - 20 * mm
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(20 * mm, y, title)
    y -= 15 * mm
    col_widths = [(width - 40 * mm) / max(1, len(headers))] * len(headers)
    pdf.setFont("Helvetica-Bold", 10)
    for i, header in enumerate(headers):
        pdf.drawString(20 * mm + sum(col_widths[:i]), y, str(header).upper())
    y -= 8 * mm
    pdf.setFont("Helvetica", 9)
    for row in rows:
        if y < 20 * mm:
            pdf.showPage()
            y = height - 20 * mm
            pdf.setFont("Helvetica", 9)
        for i, cell in enumerate(row):
            text = str(cell)
            if len(text) > 30:
                text = text[:27] + "..."
            pdf.drawString(20 * mm + sum(col_widths[:i]), y, text)
        y -= 6 * mm
    pdf.save()
    return buffer.getvalue()


def _draw_bar_plot_on_canvas(pdf: canvas.Canvas, title: str, x: float, y: float, w: float, h: float, labels: List[str], values: List[float]) -> None:
    values = [float(v) if v is not None else 0.0 for v in values]
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(x, y + h + 5 * mm, title)
    if not values:
        pdf.setFont("Helvetica", 10)
        pdf.drawString(x, y + h / 2, "No data")
        return
    max_val = max(max(values), 1.0)
    bar_width = w / max(1, len(values))
    pdf.setStrokeColor(colors.lightgrey)
    pdf.line(x, y, x + w, y)
    pdf.line(x, y, x, y + h)
    for i, (label, val) in enumerate(zip(labels, values)):
        bar_h = (val / max_val) * h
        bar_x = x + i * bar_width + bar_width * 0.1
        bar_w = bar_width * 0.8
        pdf.setFillColor(colors.HexColor("#3b82f6"))
        pdf.rect(bar_x, y, bar_w, bar_h, fill=1, stroke=0)
        pdf.setFillColor(colors.black)
        pdf.setFont("Helvetica", 7)
        pdf.drawCentredString(bar_x + bar_w / 2, y + bar_h + 1 * mm, str(round(val, 1)))
        lbl = str(label)
        if len(lbl) > 10:
            lbl = lbl[:8] + ".."
        pdf.saveState()
        pdf.translate(bar_x + bar_w / 2, y - 2 * mm)
        pdf.rotate(-45)
        pdf.drawString(0, 0, lbl)
        pdf.restoreState()


def _draw_line_plot_on_canvas(pdf: canvas.Canvas, title: str, x: float, y: float, w: float, h: float, labels: List[str], values: List[float]) -> None:
    values = [float(v) if v is not None else 0.0 for v in values]
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(x, y + h + 5 * mm, title)
    if not values:
        pdf.setFont("Helvetica", 10)
        pdf.drawString(x, y + h / 2, "No data")
        return
    max_val = max(max(values), 1.0)
    pt_w = w / max(1, len(values) - 1) if len(values) > 1 else w
    pdf.setStrokeColor(colors.lightgrey)
    pdf.line(x, y, x + w, y)
    pdf.line(x, y, x, y + h)
    points = []
    for i, val in enumerate(values):
        pt_x = x + i * pt_w
        pt_y = y + (val / max_val) * h
        points.append((pt_x, pt_y))
    if len(points) > 1:
        pdf.setStrokeColor(colors.HexColor("#2563eb"))
        pdf.setLineWidth(2)
        p = pdf.beginPath()
        p.moveTo(points[0][0], points[0][1])
        for pt in points[1:]:
            p.lineTo(pt[0], pt[1])
        pdf.drawPath(p, stroke=1, fill=0)
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica", 7)
    for i, (pt, label, val) in enumerate(zip(points, labels, values)):
        pdf.drawCentredString(pt[0], pt[1] + 2 * mm, str(round(val, 1)))
        lbl = str(label)
        if len(lbl) > 10:
            lbl = lbl[:8] + ".."
        pdf.saveState()
        pdf.translate(pt[0], y - 2 * mm)
        pdf.rotate(-45)
        pdf.drawString(0, 0, lbl)
        pdf.restoreState()


def draw_plots_pdf(
    title: str,
    plots: List[Dict[str, Any]],
    tables: List[Dict[str, Any]] | None = None,
) -> bytes:
    from io import BytesIO
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=landscape(A4))
    width, height = landscape(A4)
    y = height - 20 * mm
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(20 * mm, y, title)
    y -= 10 * mm
    
    for i, p in enumerate(plots):
        if i % 2 == 0:
            y -= 60 * mm
        if y < 30 * mm:
            pdf.showPage()
            y = height - 70 * mm
        x = 20 * mm if i % 2 == 0 else width / 2 + 10 * mm
        pw = (width - 60 * mm) / 2
        ph = 50 * mm
        if p.get("type") == "line":
            _draw_line_plot_on_canvas(pdf, str(p.get("title")), x, y, pw, ph, p.get("labels", []), p.get("values", []))
        else:
            _draw_bar_plot_on_canvas(pdf, str(p.get("title")), x, y, pw, ph, p.get("labels", []), p.get("values", []))
    
    if tables:
        for tbl in tables:
            pdf.showPage()
            ty = height - 20 * mm
            pdf.setFont("Helvetica-Bold", 14)
            pdf.drawString(20 * mm, ty, str(tbl.get("title")))
            ty -= 15 * mm
            headers = tbl.get("headers", [])
            col_widths = [(width - 40 * mm) / max(1, len(headers))] * len(headers)
            pdf.setFont("Helvetica-Bold", 10)
            for j, header in enumerate(headers):
                pdf.drawString(20 * mm + sum(col_widths[:j]), ty, str(header).upper())
            ty -= 8 * mm
            pdf.setFont("Helvetica", 9)
            for row in tbl.get("rows", []):
                if ty < 20 * mm:
                    pdf.showPage()
                    ty = height - 20 * mm
                    pdf.setFont("Helvetica", 9)
                for j, cell in enumerate(row):
                    text = str(cell)
                    if len(text) > 30:
                        text = text[:27] + "..."
                    pdf.drawString(20 * mm + sum(col_widths[:j]), ty, text)
                ty -= 6 * mm
    pdf.save()
    return buffer.getvalue()
