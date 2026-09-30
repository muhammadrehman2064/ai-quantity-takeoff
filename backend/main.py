from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pathlib import Path
from typing import List, Optional
import fitz
import re
import uuid
import json
import math

from excel_export import create_takeoff_excel

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
UPLOADS = DATA / "uploads"
REPORTS = DATA / "reports"
UPLOADS.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AI Quantity Takeoff MVP", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Measurement(BaseModel):
    item_no: int
    description: str
    element_type: str = "other"
    numbers: float = Field(default=1, ge=0)
    length: float = Field(default=0, ge=0)
    width: float = Field(default=0, ge=0)
    height: float = Field(default=0, ge=0)
    unit: str = "m2"
    formula: Optional[str] = ""
    quantity: Optional[float] = None
    source: str = "manual"
    confidence: Optional[float] = None
    page: Optional[int] = None
    verified: bool = False


class TakeoffRequest(BaseModel):
    project_name: str = "Untitled Project"
    scale: str = "1:100"
    drawing_units: str = "mm"
    measurements: List[Measurement]


def parse_scale(scale: str) -> Optional[float]:
    m = re.search(r"1\s*:\s*([0-9]+(?:\.[0-9]+)?)", scale or "")
    return float(m.group(1)) if m else None


def extract_dimension_candidates(text: str):
    """
    Extract common dimension labels such as:
    4200, 4200 mm, 4.2 m, 3'-6", 3' 6"
    This is intentionally conservative. It returns candidates for review,
    rather than pretending every number is a dimension.
    """
    patterns = [
        r"\b\d{2,5}(?:\.\d+)?\s*mm\b",
        r"\b\d+(?:\.\d+)?\s*m\b",
        r"\b\d+(?:\.\d+)?\s*(?:ft|feet)\b",
        r"\b\d+'\s*\d+(?:\.\d+)?\"\b",
        r"\b\d{3,5}\b",
    ]
    found = []
    seen = set()
    for pattern in patterns:
        for m in re.finditer(pattern, text, flags=re.I):
            raw = m.group(0).strip()
            if raw not in seen:
                seen.add(raw)
                found.append(raw)
    return found[:200]


@app.get("/health")
def health():
    return {"status": "ok", "service": "ai-quantity-takeoff"}


@app.post("/api/drawings/upload")
async def upload_drawing(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    drawing_id = uuid.uuid4().hex
    destination = UPLOADS / f"{drawing_id}.pdf"
    content = await file.read()
    destination.write_bytes(content)

    try:
        doc = fitz.open(destination)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Invalid PDF: {exc}")

    pages = []
    all_candidates = []

    for page_index in range(len(doc)):
        page = doc[page_index]
        text = page.get_text("text")
        candidates = extract_dimension_candidates(text)
        all_candidates.extend(candidates)

        pages.append({
            "page": page_index + 1,
            "width_pt": round(page.rect.width, 2),
            "height_pt": round(page.rect.height, 2),
            "text_length": len(text),
            "dimension_candidates": candidates,
        })

    doc.close()

    metadata = {
        "drawing_id": drawing_id,
        "filename": file.filename,
        "pages": len(pages),
        "pages_detail": pages,
        "dimension_candidates": list(dict.fromkeys(all_candidates)),
    }
    (UPLOADS / f"{drawing_id}.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    return metadata


@app.get("/api/drawings/{drawing_id}/file")
def drawing_file(drawing_id: str):
    path = UPLOADS / f"{drawing_id}.pdf"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Drawing not found.")
    return FileResponse(path, media_type="application/pdf")


@app.get("/api/drawings/{drawing_id}/metadata")
def drawing_metadata(drawing_id: str):
    path = UPLOADS / f"{drawing_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Drawing not found.")
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/api/takeoff/export")
def export_takeoff(request: TakeoffRequest):
    # Deterministic calculation. The client can provide quantity, but the
    # server recalculates it from dimensions for auditability.
    rows = []
    for m in request.measurements:
        n = m.numbers or 1
        L, W, H = m.length or 0, m.width or 0, m.height or 0

        if m.unit == "m2":
            quantity = n * L * W
            formula = f"{n:g} × {L:g} × {W:g}"
        elif m.unit == "m3":
            quantity = n * L * W * H
            formula = f"{n:g} × {L:g} × {W:g} × {H:g}"
        elif m.unit == "m":
            quantity = n * L
            formula = f"{n:g} × {L:g}"
        elif m.unit == "nos":
            quantity = n
            formula = f"{n:g}"
        else:
            quantity = m.quantity or 0
            formula = m.formula or "Manual"

        rows.append({
            **m.model_dump(),
            "formula": formula,
            "quantity": round(quantity, 4),
        })

    report_id = uuid.uuid4().hex
    output = REPORTS / f"{report_id}.xlsx"
    create_takeoff_excel(
        output_path=output,
        project_name=request.project_name,
        scale=request.scale,
        drawing_units=request.drawing_units,
        rows=rows,
    )

    return {
        "report_id": report_id,
        "filename": output.name,
        "download_url": f"/api/takeoff/{report_id}/download",
        "rows": len(rows),
    }


@app.get("/api/takeoff/{report_id}/download")
def download_takeoff(report_id: str):
    path = REPORTS / f"{report_id}.xlsx"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found.")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="quantity_takeoff.xlsx",
    )
