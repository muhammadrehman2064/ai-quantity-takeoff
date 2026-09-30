import os
import re
import json
import base64
import uuid
from pathlib import Path
from typing import List, Optional

import fitz
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from groq import Groq

from excel_export import create_takeoff_excel


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)
else:
    groq_client = None


# ============================================================
# PATHS
# ============================================================

BASE = Path(__file__).resolve().parent

DATA = BASE / "data"
UPLOADS = DATA / "uploads"
REPORTS = DATA / "reports"

UPLOADS.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="AI Quantity Takeoff MVP",
    version="0.2.0"
)


# ============================================================
# CORS
# ============================================================

frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")

allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

if frontend_url:
    allowed_origins.append(frontend_url)

extra_origins = os.getenv("ALLOWED_ORIGINS", "")

if extra_origins:
    allowed_origins.extend(
        [
            x.strip()
            for x in extra_origins.split(",")
            if x.strip()
        ]
    )

allowed_origins = list(dict.fromkeys(allowed_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# DATA MODELS
# ============================================================

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


# ============================================================
# HELPERS
# ============================================================

def parse_scale(scale: str) -> Optional[float]:
    match = re.search(
        r"1\s*:\s*([0-9]+(?:\.[0-9]+)?)",
        scale or ""
    )

    return float(match.group(1)) if match else None


def extract_dimension_candidates(text: str):

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

        for match in re.finditer(
            pattern,
            text,
            flags=re.I
        ):

            raw = match.group(0).strip()

            if raw not in seen:

                seen.add(raw)

                found.append(raw)

    return found[:200]


def encode_page_image(page):

    """
    Render PDF page to JPEG and return a base64 data URL.

    150 DPI is a compromise between:
    - readable architectural dimensions
    - API payload size
    """

    pix = page.get_pixmap(
        matrix=fitz.Matrix(150 / 72, 150 / 72),
        alpha=False
    )

    image_bytes = pix.tobytes(
        "jpeg",
        jpg_quality=85
    )

    encoded = base64.b64encode(
        image_bytes
    ).decode("utf-8")

    return f"data:image/jpeg;base64,{encoded}"


def clean_json_response(content: str):

    """
    Groq JSON mode should return JSON, but this also handles
    accidental markdown fences.
    """

    if not content:
        raise ValueError("Empty AI response.")

    content = content.strip()

    if content.startswith("```"):
        content = re.sub(
            r"^```(?:json)?",
            "",
            content,
            flags=re.I
        )

        content = re.sub(
            r"```$",
            "",
            content
        )

    return json.loads(content.strip())


# ============================================================
# AI DRAWING ANALYSIS
# ============================================================

DRAWING_SYSTEM_PROMPT = """
You are an architectural drawing quantity-takeoff assistant.

Your task is to inspect ONE architectural drawing page.

You must be conservative.

IMPORTANT RULES:

1. Do NOT invent dimensions.
2. Do NOT estimate a dimension from visual proportions.
3. Only report a dimension when:
   - it is visibly written on the drawing, OR
   - it can be directly and unambiguously read from a dimension string.
4. If a measurement cannot be reliably determined, leave the numerical
   value as 0 and mark the item as unable_to_verify.
5. Do not assume that every number on a drawing is a dimension.
6. Room numbers, detail numbers, drawing numbers and levels are NOT
   dimensions unless clearly used as dimensions.
7. Preserve the page number.
8. Give a confidence between 0 and 1.
9. Confidence means confidence that the extracted information is actually
   visible and correctly interpreted — NOT confidence based on guessing.
10. Never fabricate a wall thickness, height, door size or window size.
11. If scale is visible, report it. Do not infer scale from page size.
12. Return ONLY valid JSON.

The objective is measurement extraction, not architectural design advice.
"""


def analyze_page_with_ai(
    image_data_url: str,
    page_number: int,
    extracted_text: str,
    dimension_candidates: list
):

    if not groq_client:
        raise HTTPException(
            status_code=500,
            detail=(
                "GROQ_API_KEY is not configured. "
                "Add it as an environment variable."
            )
        )

    user_prompt = f"""
Analyze architectural drawing page {page_number}.

PDF text extracted from this page:

{extracted_text[:12000]}

Potential dimension candidates detected by text extraction:

{json.dumps(dimension_candidates[:100], ensure_ascii=False)}

Return JSON using EXACTLY this structure:

{{
  "page": {page_number},
  "drawing_scale": null,
  "drawing_units": null,
  "elements": [
    {{
      "description": "",
      "element_type": "room|wall|door|window|beam|column|slab|stair|other",
      "numbers": 1,
      "length_mm": 0,
      "width_mm": 0,
      "height_mm": 0,
      "unit": "m2|m3|m|nos",
      "quantity": null,
      "source_dimension": "",
      "confidence": 0,
      "status": "verified_from_drawing|candidate|unable_to_verify"
    }}
  ],
  "notes": []
}}

For rooms:
- length_mm and width_mm should only be populated when dimensions
  are explicitly visible.
- Do not calculate a room size from an assumed scale.

For walls:
- only populate wall length/thickness/height if clearly dimensioned.

For doors/windows:
- use numbers only when count can be reasonably established from
  clearly visible labels/symbols.
- Do not invent dimensions.

For slabs:
- only report measurable dimensions that are actually visible.

For quantity:
- calculate only when the required dimensions are available.
- Otherwise use null.

For source_dimension:
- write the actual visible dimension, e.g. "4200 mm x 3600 mm".
- If there is no clear source dimension, leave empty.

Do not include explanations outside JSON.
"""

    try:

        completion = groq_client.chat.completions.create(

            model=GROQ_MODEL,

            messages=[
                {
                    "role": "system",
                    "content": DRAWING_SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_data_url
                            }
                        }
                    ]
                }
            ],

            temperature=0,

            max_completion_tokens=4000,

            response_format={
                "type": "json_object"
            }
        )

        content = completion.choices[0].message.content

        return clean_json_response(content)

    except Exception as exc:

        raise HTTPException(
            status_code=502,
            detail=f"AI drawing analysis failed: {str(exc)}"
        )


# ============================================================
# CONVERT AI RESULT → MEASUREMENT ROWS
# ============================================================

def ai_elements_to_measurements(
    analysis: dict,
    page_number: int
):

    measurements = []

    elements = analysis.get(
        "elements",
        []
    )

    for element in elements:

        element_type = str(
            element.get(
                "element_type",
                "other"
            )
        )

        description = str(
            element.get(
                "description",
                ""
            )
        ).strip()

        numbers = float(
            element.get(
                "numbers",
                1
            ) or 1
        )

        length_mm = float(
            element.get(
                "length_mm",
                0
            ) or 0
        )

        width_mm = float(
            element.get(
                "width_mm",
                0
            ) or 0
        )

        height_mm = float(
            element.get(
                "height_mm",
                0
            ) or 0
        )

        unit = str(
            element.get(
                "unit",
                "nos"
            )
        )

        confidence = element.get(
            "confidence"
        )

        if confidence is not None:

            try:
                confidence = max(
                    0,
                    min(
                        1,
                        float(confidence)
                    )
                )
            except Exception:
                confidence = None

        status = str(
            element.get(
                "status",
                "candidate"
            )
        )

        source_dimension = str(
            element.get(
                "source_dimension",
                ""
            )
        )

        # Convert mm → metres for QS calculations.
        length_m = length_mm / 1000
        width_m = width_mm / 1000
        height_m = height_mm / 1000

        quantity = None

        if unit == "m2" and length_m > 0 and width_m > 0:
            quantity = numbers * length_m * width_m

        elif (
            unit == "m3"
            and length_m > 0
            and width_m > 0
            and height_m > 0
        ):
            quantity = (
                numbers
                * length_m
                * width_m
                * height_m
            )

        elif unit == "m" and length_m > 0:
            quantity = numbers * length_m

        elif unit == "nos" and numbers > 0:
            quantity = numbers

        # Do not silently treat an unverified item as reliable.
        verified = (
            status == "verified_from_drawing"
            and confidence is not None
            and confidence >= 0.90
        )

        measurements.append(
            {
                "item_no": 0,
                "description": description or element_type,
                "element_type": element_type,
                "numbers": numbers,
                "length": round(length_m, 4),
                "width": round(width_m, 4),
                "height": round(height_m, 4),
                "unit": unit,
                "formula": "",
                "quantity": (
                    round(quantity, 4)
                    if quantity is not None
                    else None
                ),
                "source": "ai",
                "confidence": confidence,
                "page": page_number,
                "verified": verified,
                "ai_status": status,
                "source_dimension": source_dimension
            }
        )

    return measurements


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    return {
        "status": "ok",
        "service": "ai-quantity-takeoff",
        "ai_configured": bool(GROQ_API_KEY),
        "model": GROQ_MODEL
    }


# ============================================================
# UPLOAD DRAWING
# ============================================================

@app.post("/api/drawings/upload")
async def upload_drawing(
    file: UploadFile = File(...)
):

    if not file.filename.lower().endswith(".pdf"):

        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported."
        )

    drawing_id = uuid.uuid4().hex

    destination = (
        UPLOADS
        / f"{drawing_id}.pdf"
    )

    content = await file.read()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded PDF is empty."
        )

    destination.write_bytes(content)

    try:

        doc = fitz.open(destination)

    except Exception as exc:

        destination.unlink(
            missing_ok=True
        )

        raise HTTPException(
            status_code=400,
            detail=f"Invalid PDF: {exc}"
        )

    pages = []
    all_candidates = []

    for page_index in range(len(doc)):

        page = doc[page_index]

        text = page.get_text("text")

        candidates = extract_dimension_candidates(
            text
        )

        all_candidates.extend(
            candidates
        )

        pages.append(
            {
                "page": page_index + 1,
                "width_pt": round(
                    page.rect.width,
                    2
                ),
                "height_pt": round(
                    page.rect.height,
                    2
                ),
                "text_length": len(text),
                "dimension_candidates": candidates
            }
        )

    doc.close()

    metadata = {
        "drawing_id": drawing_id,
        "filename": file.filename,
        "pages": len(pages),
        "pages_detail": pages,
        "dimension_candidates": list(
            dict.fromkeys(
                all_candidates
            )
        )
    }

    (
        UPLOADS
        / f"{drawing_id}.json"
    ).write_text(
        json.dumps(
            metadata,
            indent=2
        ),
        encoding="utf-8"
    )

    return metadata


# ============================================================
# AI ANALYSIS ENDPOINT
# ============================================================

@app.post(
    "/api/drawings/{drawing_id}/analyze"
)
def analyze_drawing(
    drawing_id: str
):

    pdf_path = (
        UPLOADS
        / f"{drawing_id}.pdf"
    )

    if not pdf_path.exists():

        raise HTTPException(
            status_code=404,
            detail="Drawing not found."
        )

    if not GROQ_API_KEY:

        raise HTTPException(
            status_code=500,
            detail=(
                "GROQ_API_KEY is not configured."
            )
        )

    try:

        doc = fitz.open(pdf_path)

    except Exception as exc:

        raise HTTPException(
            status_code=400,
            detail=f"Could not open PDF: {exc}"
        )

    all_measurements = []
    page_results = []
    detected_scales = []

    try:

        for page_index in range(len(doc)):

            page_number = page_index + 1

            page = doc[page_index]

            text = page.get_text("text")

            candidates = extract_dimension_candidates(
                text
            )

            image_data_url = encode_page_image(
                page
            )

            analysis = analyze_page_with_ai(
                image_data_url=image_data_url,
                page_number=page_number,
                extracted_text=text,
                dimension_candidates=candidates
            )

            drawing_scale = analysis.get(
                "drawing_scale"
            )

            if drawing_scale:
                detected_scales.append(
                    drawing_scale
                )

            measurements = (
                ai_elements_to_measurements(
                    analysis,
                    page_number
                )
            )

            start_number = (
                len(all_measurements) + 1
            )

            for index, measurement in enumerate(
                measurements
            ):

                measurement["item_no"] = (
                    start_number + index
                )

                all_measurements.append(
                    measurement
                )

            page_results.append(
                {
                    "page": page_number,
                    "drawing_scale": drawing_scale,
                    "drawing_units": analysis.get(
                        "drawing_units"
                    ),
                    "notes": analysis.get(
                        "notes",
                        []
                    ),
                    "measurement_count": len(
                        measurements
                    )
                }
            )

    finally:

        doc.close()

    return {
        "drawing_id": drawing_id,
        "model": GROQ_MODEL,
        "pages_analyzed": len(page_results),
        "detected_scales": list(
            dict.fromkeys(
                detected_scales
            )
        ),
        "pages": page_results,
        "measurements": all_measurements
    }


# ============================================================
# DRAWING FILE
# ============================================================

@app.get(
    "/api/drawings/{drawing_id}/file"
)
def drawing_file(
    drawing_id: str
):

    path = (
        UPLOADS
        / f"{drawing_id}.pdf"
    )

    if not path.exists():

        raise HTTPException(
            status_code=404,
            detail="Drawing not found."
        )

    return FileResponse(
        path,
        media_type="application/pdf"
    )


# ============================================================
# DRAWING METADATA
# ============================================================

@app.get(
    "/api/drawings/{drawing_id}/metadata"
)
def drawing_metadata(
    drawing_id: str
):

    path = (
        UPLOADS
        / f"{drawing_id}.json"
    )

    if not path.exists():

        raise HTTPException(
            status_code=404,
            detail="Drawing not found."
        )

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


# ============================================================
# EXCEL EXPORT
# ============================================================

@app.post(
    "/api/takeoff/export"
)
def export_takeoff(
    request: TakeoffRequest
):

    rows = []

    for m in request.measurements:

        n = m.numbers or 1

        L = m.length or 0

        W = m.width or 0

        H = m.height or 0

        if m.unit == "m2":

            quantity = (
                n * L * W
            )

            formula = (
                f"{n:g} × "
                f"{L:g} × "
                f"{W:g}"
            )

        elif m.unit == "m3":

            quantity = (
                n * L * W * H
            )

            formula = (
                f"{n:g} × "
                f"{L:g} × "
                f"{W:g} × "
                f"{H:g}"
            )

        elif m.unit == "m":

            quantity = (
                n * L
            )

            formula = (
                f"{n:g} × "
                f"{L:g}"
            )

        elif m.unit == "nos":

            quantity = n

            formula = f"{n:g}"

        else:

            quantity = (
                m.quantity or 0
            )

            formula = (
                m.formula
                or "Manual"
            )

        rows.append(
            {
                **m.model_dump(),
                "formula": formula,
                "quantity": round(
                    quantity,
                    4
                )
            }
        )

    report_id = uuid.uuid4().hex

    output = (
        REPORTS
        / f"{report_id}.xlsx"
    )

    create_takeoff_excel(
        output_path=output,
        project_name=request.project_name,
        scale=request.scale,
        drawing_units=request.drawing_units,
        rows=rows
    )

    return {
        "report_id": report_id,
        "filename": output.name,
        "download_url": (
            f"/api/takeoff/"
            f"{report_id}/download"
        ),
        "rows": len(rows)
    }


# ============================================================
# DOWNLOAD EXCEL
# ============================================================

@app.get(
    "/api/takeoff/{report_id}/download"
)
def download_takeoff(
    report_id: str
):

    path = (
        REPORTS
        / f"{report_id}.xlsx"
    )

    if not path.exists():

        raise HTTPException(
            status_code=404,
            detail="Report not found."
        )

    return FileResponse(
        path,
        media_type=(
            "application/vnd.openxmlformats-"
            "officedocument.spreadsheetml.sheet"
        ),
        filename="quantity_takeoff.xlsx"
    )
