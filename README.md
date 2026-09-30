# AI Quantity Takeoff MVP

A starter MVP for extracting architectural drawing measurements from PDF files and generating a formula-driven Excel quantity takeoff.

## What this MVP does

1. Upload an architectural PDF.
2. Inspect PDF pages with PyMuPDF.
3. Detect basic dimension text using OCR/text extraction.
4. Accept drawing scale and units from the user.
5. Let the user create/edit measurement rows.
6. Calculate area/volume deterministically in Python.
7. Export an Excel workbook with formulas.
8. Provide a browser UI with PDF preview and measurement table.

## Important

This is an MVP foundation, not a certified automatic QS measurement engine. AI/Vision extraction should be treated as assisted extraction and verified by a QS before final use.

## Run locally

### Backend

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

The frontend expects the backend at `http://localhost:8000`.

## Current extraction strategy

The MVP intentionally separates:

- PDF/vector/text extraction
- optional AI interpretation
- deterministic calculations
- human verification
- Excel reporting

This prevents the LLM from being the source of mathematical truth.

## Next production steps

- Add a vision provider adapter for Gemini/OpenAI.
- Add OCR fallback for scanned drawings.
- Add PDF canvas overlays with exact element coordinates.
- Add PostgreSQL + project storage.
- Add user authentication.
- Add structural takeoff modules for RCC, excavation and reinforcement.
