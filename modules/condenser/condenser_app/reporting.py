"""Report export: one Excel workbook or one PDF from any module's DesignResult."""
from __future__ import annotations

import io
from typing import Any
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .common.units import convert
from .schemas import Category, CheckState, DesignResult, Status, iter_inputs

DISCLAIMER = (
    "Preliminary design for coursework. Mechanical design and code compliance (ASME, TEMA, HEI, ISO) are not established "
    "by this report and need qualified engineering review against the applicable edition."
)
STATUS_TEXT = {
    Status.OK: "Completed with no warnings or failed checks",
    Status.OK_WITH_WARNINGS: "Completed with warnings or failed checks: review them",
    Status.INVALID_INPUT: "Not run: invalid input",
    Status.NOT_CONVERGED: "Not converged: results are not usable",
    Status.FAILED: "Failed: no solution",
}


def _display(value: Any) -> Any:
    if isinstance(value, float):
        return float(f"{value:.5g}")
    return value


def input_rows(inputs: Any) -> list[dict]:
    """Inputs in the units the user entered them, for the report."""
    rows = []
    for path, owner, name, meta in iter_inputs(inputs):
        value = getattr(owner, name)
        if value is None:
            continue
        unit, shown = meta["unit"], meta["display_unit"]
        if isinstance(value, (int, float)) and not isinstance(value, bool) and unit and shown != unit:
            value = convert(value, unit, shown)
        rows.append({"Input": meta["label"], "Value": _display(value), "Unit": shown or "", "Field": path})
    return rows


def _frames(result: DesignResult, inputs: Any) -> dict[str, pd.DataFrame]:
    outputs = [{"Category": q.category.value, "Result": q.label, "Value": _display(q.value), "Unit": q.unit, "Source": q.source} for q in result.outputs]
    steps = [{"Category": s.category.value, "Step": s.label, "Symbol": s.symbol, "Formula": s.formula, "Numbers": s.substitution,
              "Result": _display(s.value), "Unit": s.unit, "Source": s.source} for s in result.steps]
    checks = [{"Category": c.category.value, "Check": c.name, "State": c.state.value, "Detail": c.detail, "Source": c.source} for c in result.checks]
    notes = (
        [{"Type": "Warning", "Note": n} for n in result.warnings]
        + [{"Type": "Assumption", "Note": n} for n in result.assumptions]
        + [{"Type": "Source gap", "Note": n} for n in result.source_gaps]
        + [{"Type": "Reference", "Note": n} for n in result.references]
        + [{"Type": "Disclaimer", "Note": DISCLAIMER}]
    )
    convergence = [{"Iteration": c.name, "Converged": c.converged, "Passes": c.iterations, "Tolerance": c.tolerance, "Final residual": c.residual} for c in result.convergence]
    return {
        "Inputs": pd.DataFrame(input_rows(inputs)),
        "Results": pd.DataFrame(outputs),
        "Calculation steps": pd.DataFrame(steps),
        "Checks": pd.DataFrame(checks),
        "Convergence": pd.DataFrame(convergence),
        "Notes": pd.DataFrame(notes),
    }


def to_excel(result: DesignResult, inputs: Any) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        summary = pd.DataFrame({"Item": ["Module", "Status", "Message"], "Value": [result.title, STATUS_TEXT[result.status], result.message]})
        summary.to_excel(writer, sheet_name="Summary", index=False)
        for name, frame in _frames(result, inputs).items():
            frame.to_excel(writer, sheet_name=name[:31], index=False)
        for sheet in writer.book.worksheets:
            for column in sheet.columns:
                longest = max((len(str(c.value)) for c in column if c.value is not None), default=8)
                sheet.column_dimensions[column[0].column_letter].width = min(longest + 2, 70)
    return buffer.getvalue()


_GREEK = str.maketrans({
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "Δ": "Delta", "ε": "eps", "η": "eta", "θ": "theta", "λ": "lambda",
    "μ": "mu", "ν": "nu", "π": "pi", "ρ": "rho", "σ": "sigma", "τ": "tau", "φ": "phi", "Φ": "Phi", "χ": "chi", "ψ": "psi", "ω": "omega",
    "≤": "<=", "≥": ">=", "≈": "~", "×": "x", "−": "-", "–": "-", "—": "-", "→": "->", "⇒": "=>", "∫": "integral ", "√": "sqrt", "∞": "inf",
    "⁴": "^4", "⁻": "^-", "₁": "1", "₂": "2", "✓": "ok",
})


def _safe(value: Any) -> str:
    """The PDF's built-in font covers Latin-1 only, so transliterate symbols and escape markup."""
    if isinstance(value, float):
        value = f"{value:.5g}"
    text = str(value).translate(_GREEK).encode("latin-1", "replace").decode("latin-1")
    return escape(text)


def to_pdf(result: DesignResult, inputs: Any) -> bytes:
    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["BodyText"], fontSize=8.5, leading=10.5)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=9)
    head = ParagraphStyle("head", parent=base["Heading2"], textColor=colors.HexColor("#19468C"), fontSize=11.5, spaceBefore=8, spaceAfter=3, keepWithNext=1)

    def table(rows: list[list[Any]], widths: list[float]) -> Table:
        cells = [[Paragraph(_safe(c), small) for c in row] for row in rows]
        t = Table(cells, colWidths=[w * mm for w in widths], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6ECF5")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ]))
        return t

    def bullets(title: str, items: list[str]) -> list:
        if not items:
            return []
        return [Paragraph(title, head)] + [Paragraph("- " + _safe(i), body) for i in items]

    story: list = [
        Paragraph(_safe(result.title), base["Title"]),
        Paragraph(f"<b>Status:</b> {_safe(STATUS_TEXT[result.status])}", body),
    ]
    if result.message:
        story.append(Paragraph(_safe(result.message), body))
    story += [Spacer(1, 3), Paragraph(f"<i>{_safe(DISCLAIMER)}</i>", small)]

    rows = input_rows(inputs)
    if rows:
        story += [Paragraph("Inputs", head), table([["Input", "Value", "Unit"]] + [[r["Input"], r["Value"], r["Unit"]] for r in rows], [105, 40, 30])]
    for category in Category:
        selected = [q for q in result.outputs if q.category is category]
        if selected:
            story += [Paragraph(f"Results: {category.value}", head), table([["Result", "Value", "Unit", "Source"]] + [[q.label, q.value, q.unit, q.source] for q in selected], [62, 58, 20, 35])]
    if result.checks:
        mark = {CheckState.PASS: "PASS", CheckState.FAIL: "FAIL", CheckState.NOT_ASSESSED: "NOT ASSESSED"}
        story += [Paragraph("Engineering checks", head), table([["Check", "State", "Detail", "Source"]] + [[c.name, mark[c.state], c.detail, c.source] for c in result.checks], [50, 20, 75, 30])]
    story += bullets("Warnings", result.warnings)
    if result.steps:
        story += [Paragraph("Calculation steps (formula = numbers = result)", head),
                  table([["Step", "Formula", "Numbers", "Result", "Source"]] + [[s.label, s.formula_text(), s.substitution, s.result_text(), s.source] for s in result.steps], [38, 45, 42, 25, 25])]
    if result.convergence:
        story += [Paragraph("Convergence", head), table([["Iteration", "Converged", "Passes", "Tolerance", "Residual"]] + [[c.name, c.converged, c.iterations, c.tolerance, c.residual] for c in result.convergence], [75, 25, 20, 27, 28])]
    story += bullets("Assumptions", result.assumptions)
    story += bullets("Source gaps", result.source_gaps)
    story += bullets("References", result.references)

    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
                      title=_safe(result.title)).build(story)
    return buffer.getvalue()
