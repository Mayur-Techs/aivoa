# AIVOA AI-powered complaint intake

An assessment-ready customer complaint intake product for pharmaceutical API and FDF workflows. The React form is intentionally read-only: users converse with the co-pilot or upload a document, and the assistant updates the intake record and risk assessment.

## What is implemented

- React + Redux Toolkit UI using Inter, designed around the supplied split-panel reference.
- FastAPI API with a PostgreSQL-ready SQLAlchemy model and Docker Compose database.
- A LangGraph pipeline: `extract -> merge -> assess`.
- Groq structured extraction through `langchain-groq` when `GROQ_API_KEY` is configured.
- A conservative local rules fallback for offline demos, provider outages, and free-tier rate limits.
- Natural-language corrections preserve prior complaint data.
- Document intake for PDF, DOCX, TXT, CSV, and EML (10 MB limit) and a realistic demo email in [`demo-assets/`](demo-assets/).
- Browser-based speech-to-text input for hands-free complaint entry. It uses the device's speech-recognition capability and never uploads audio to this application backend.
- Decision-support extras: completeness scoring, missing-field prompts, root-cause investigation cues, CAPA recommendation, and deterministic AI risk classification.

## Architecture

```text
React + Redux Toolkit
        |
        v
FastAPI routes (/api/ai/chat, /api/documents/extract, /api/complaints)
        |
        v
LangGraph: extract -> merge previous state -> assess risk
        |                         |
Groq structured output       PostgreSQL persistence
        |
Rules fallback (no API key / provider error)
```

The fallback is an availability feature, not a replacement for QA review. It only extracts values that appear in the submitted text and uses visible rule-based risk classification. In production, all AI outputs should be reviewed by qualified QA personnel.

## Run locally

Prerequisites: Node 20+, Python 3.11+. PostgreSQL and Docker are optional.

```powershell
Copy-Item .env.example .env

cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```powershell
cd frontend
pnpm install
pnpm dev
```

Open `http://localhost:5173`.

The included `.env.example` uses SQLite, so no database installation is needed for the assessment demo. If you previously copied an older `.env.example` and the API says `ConnectionRefusedError` for port `5432`, change only this line in your root `.env`:

```dotenv
DATABASE_URL=sqlite+aiosqlite:///./aivoa.db
```

To use Docker PostgreSQL instead, run `docker compose up -d database` and set `DATABASE_URL=postgresql+asyncpg://aivoa:aivoa@localhost:5432/aivoa`.

The API accepts the usual Vite local development addresses (`localhost` or `127.0.0.1` on ports 5173 and 5174), so it remains usable if Vite selects port 5174 because 5173 is occupied. Restart the backend after changing configuration or pulling updates.

### Voice input

Select the microphone beside the co-pilot prompt, allow the browser microphone permission, and speak naturally. The transcript appears in the prompt; review it and press Send. Voice input is an optional convenience feature - if a browser does not support speech recognition, normal text entry and document upload remain available.

## Groq configuration

Add `GROQ_API_KEY` to the root `.env` beside this README. Use the key exactly as issued; quotes are optional but unnecessary, so `GROQ_API_KEY=gsk_...` is preferred. The application safely falls back to local extraction rules if the key is absent, invalid, rate-limited, or a model is unavailable. The original brief names `gemma2-9b-it`; Groq retired that model on 2025-10-08. The default is therefore Groq's supported `llama-3.1-8b-instant`. Set `GROQ_MODEL` explicitly if the reviewer requires a different currently available Groq model.

## Demo path

1. Type: `Apollo Pharmacy reported discolored capsules in Amoxicillin Capsules 500 mg. Batch number AMX240602. Manufacturing date March 2026. Expiry date February 2028. Please log this complaint.`
2. Then correct it: `Sorry, the batch number is BMX24602 and the affected quantity is 48 capsules.`
3. Reset, upload `demo-assets/metformin-complaint.eml`, then say: `Sorry, the batch number is CHG260712A and affected quantity is 50 kg 2 HDPE drums.`
4. Verify the read-only form, risk assessment, and save action update without manual field entry.

The co-pilot text area expands as you type up to a safe limit, then scrolls internally. Press Enter to send and Shift + Enter to add a line. The attach icon in the composer and the upload area above both open the same secure document picker.

## Validation

```powershell
cd backend
pytest

cd ../frontend
pnpm build
```
