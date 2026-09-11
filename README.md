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

Prerequisites: Node 20+, Python 3.11+, and optionally Docker Desktop for PostgreSQL.

```powershell
Copy-Item .env.example .env
docker compose up -d database

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

Open `http://localhost:5173`. Without Docker, leave `DATABASE_URL` unset and the backend will use local SQLite for the demonstration; Docker Compose supplies the required PostgreSQL path.

## Groq configuration

Add `GROQ_API_KEY` to `.env`. The original brief names `gemma2-9b-it`; Groq retired that model on 2025-10-08. The default is therefore Groq's supported `llama-3.1-8b-instant`. Set `GROQ_MODEL` explicitly if the reviewer requires a different currently available Groq model.

## Demo path

1. Type: `Apollo Pharmacy reported discolored capsules in Amoxicillin capsules 500 mg.`
2. Then correct it: `Sorry, the batch number is BMX24602 and the affected quantity is 48 capsules.`
3. Reset, upload `demo-assets/metformin-complaint.eml`, then say: `Sorry, the batch number is CHG260712A and affected quantity is 50 kg 2 HDPE drums.`
4. Verify the read-only form, risk assessment, and save action update without manual field entry.

## Validation

```powershell
cd backend
pytest

cd ../frontend
pnpm build
```

## Deployment notes

This repository includes a free-tier Render Blueprint in `render.yaml`. It creates a FastAPI web service, a static Vite site, and a free PostgreSQL database. Free services can sleep when idle, so the first request may take longer.

1. Create an **empty** GitHub repository (do not add a README or `.gitignore`), push this repository, then create a new Render Blueprint from it.
2. In Render, choose unique names if the default names are unavailable. Deploy the API and database first.
3. Copy the API's `https://<api-name>.onrender.com` address into the static site's `VITE_API_URL` environment variable.
4. Copy the static site's `https://<site-name>.onrender.com` address into the API's `FRONTEND_ORIGIN` variable.
5. Add `GROQ_API_KEY` to the API service only, then redeploy both services.

Render supplies the PostgreSQL connection string automatically and the Blueprint pins Python 3.12.14. The backend converts the standard `postgresql://` form to SQLAlchemy's asynchronous driver URL. Keep `GROQ_API_KEY` server-side only; never set it as a frontend `VITE_` variable.
