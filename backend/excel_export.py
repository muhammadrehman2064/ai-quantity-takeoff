from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter


HEADERS = [
    "Item No.", "Description / Structural Element", "Element Type",
    "Numbers / Quantity", "Length", "Width", "Height/Depth",
    "Unit", "Formula", "Total Quantity", "Source", "Confidence",
    "Drawing Page", "Verified"
]


def create_takeoff_excel(output_path: Path, project_name: str, scale: str,
                         drawing_units: str, rows: list):
    wb = Workbook()
    ws = wb.active
    ws.title = "Measurement Sheet"

    ws["A1"] = "AI QUANTITY TAKEOFF"
    ws["A1"].font = Font(bold=True, size=16)
    ws["A2"] = "Project"
    ws["B2"] = project_name
    ws["A3"] = "Drawing Scale"
    ws["B3"] = scale
    ws["A4"] = "Drawing Units"
    ws["B4"] = drawing_units

    header_row = 6
    for col, header in enumerate(HEADERS, 1):
        cell = ws.cell(header_row, col, header)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.fill = PatternFill("solid", fgColor="D9EAF7")

    for idx, row in enumerate(rows, header_row + 1):
        ws.cell(idx, 1, row["item_no"])
        ws.cell(idx, 2, row["description"])
        ws.cell(idx, 3, row["element_type"])
        ws.cell(idx, 4, row["numbers"])
        ws.cell(idx, 5, row["length"])
        ws.cell(idx, 6, row["width"])
        ws.cell(idx, 7, row["height"])
        ws.cell(idx, 8, row["unit"])
        ws.cell(idx, 9, row["formula"])

        # Keep the quantity formula visible and auditable in Excel.
        unit = row["unit"]
        if unit == "m2":
            formula = f"=D{idx}*E{idx}*F{idx}"
        elif unit == "m3":
            formula = f"=D{idx}*E{idx}*F{idx}*G{idx}"
        elif unit == "m":
            formula = f"=D{idx}*E{idx}"
        elif unit == "nos":
            formula = f"=D{idx}"
        else:
            formula = f"=0"

        ws.cell(idx, 10, formula)
        ws.cell(idx, 11, row["source"])
        ws.cell(idx, 12, row["confidence"])
        ws.cell(idx, 13, row["page"])
        ws.cell(idx, 14, "YES" if row["verified"] else "NO")

    total_row = header_row + len(rows) + 2
    ws.cell(total_row, 9, "TOTAL")
    ws.cell(total_row, 9).font = Font(bold=True)
    ws.cell(total_row, 10, f"=SUM(J{header_row+1}:J{total_row-2})")
    ws.cell(total_row, 10).font = Font(bold=True)

    # Add a second sheet explaining formulas and verification.
    notes = wb.create_sheet("Verification")
    notes["A1"] = "Verification Notes"
    notes["A1"].font = Font(bold=True, size=14)
    notes["A3"] = "AI extraction is assisted extraction and must be checked against the drawing."
    notes["A4"] = "Quantities are calculated deterministically from Numbers × L × W × H where applicable."
    notes["A5"] = "Source indicates how a dimension entered the system (manual, PDF text, scale-derived, AI)."
    notes["A6"] = "Verified = YES means a user has reviewed the measurement."

    for sheet in wb.worksheets:
        for col in range(1, sheet.max_column + 1):
            max_len = 0
            for cell in sheet[get_column_letter(col)]:
                if cell.value is not None:
                    max_len = max(max_len, len(str(cell.value)))
            sheet.column_dimensions[get_column_letter(col)].width = min(max(max_len + 2, 12), 42)
        for row in sheet.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="top")
        sheet.freeze_panes = "A7" if sheet.title == "Measurement Sheet" else "A3"

    wb.save(output_path)
