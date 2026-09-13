from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .database import create_tables, get_session
from .models import ComplaintRecord
from .schemas import AssistantRequest, AssistantResponse, ComplaintForm, SavedComplaint
from .services.complaint_graph import check_ai_health, run_intake
from .services.document_text import UnsupportedDocumentError, extract_document_text

settings = get_settings()
LOCAL_DEVELOPMENT_ORIGINS = {
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    await create_tables()
    yield


app = FastAPI(title="AIVOA Complaint Intake API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted({settings.frontend_origin, *LOCAL_DEVELOPMENT_ORIGINS}),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def to_response(result: dict) -> AssistantResponse:
    return AssistantResponse(
        complaint=result["complaint"],
        risk_assessment=result["risk_assessment"],
        assistant_message=result["assistant_message"],
        mode=result["mode"],
        extracted_fields=result.get("extracted_fields", []),
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health/ai")
async def ai_health() -> dict[str, str]:
    """
    Returns current AI provider status.
    Frontend uses this to drive the blinking status dot.
    Response: {"groq": "ok"|"error", "gemini": "ok"|"error", "active": "groq"|"gemini"|"none"}
    """
    return check_ai_health()


@app.post("/api/ai/chat", response_model=AssistantResponse)
async def chat(request: AssistantRequest) -> AssistantResponse:
    return to_response(run_intake(request.message, request.current_complaint))


@app.post("/api/documents/extract", response_model=AssistantResponse)
async def extract_document(
    file: UploadFile = File(...),
    current_complaint: str = "{}",
) -> AssistantResponse:
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Document exceeds the 10 MB limit.")
    if not file.filename:
        raise HTTPException(status_code=400, detail="A filename is required.")
    try:
        current = ComplaintForm.model_validate_json(current_complaint)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="The current complaint payload is invalid.") from exc
    try:
        text = extract_document_text(file.filename, content)
    except UnsupportedDocumentError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not text.strip():
        raise HTTPException(status_code=422, detail="No readable text was found in this document.")
    return to_response(run_intake(text, current))


@app.post("/api/complaints", response_model=SavedComplaint, status_code=status.HTTP_201_CREATED)
async def save_complaint(response: AssistantResponse, session: AsyncSession = Depends(get_session)) -> SavedComplaint:
    record = ComplaintRecord(
        product_name=response.complaint.product_name,
        batch_lot_number=response.complaint.batch_lot_number,
        complaint_data=response.complaint.model_dump(mode="json"),
        risk_data=response.risk_assessment.model_dump(mode="json"),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return SavedComplaint(id=record.id, complaint=response.complaint, risk_assessment=response.risk_assessment)
