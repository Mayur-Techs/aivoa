"""
AIVOA LangGraph pipeline.
Primary model: Groq (openai/gpt-oss-20b)
Fallback model: Gemini (gemini-2.5-flash) — activates automatically if Groq fails
"""

from datetime import date
from typing import TypedDict

from fastapi import HTTPException, status
from langgraph.graph import END, START, StateGraph

from ..config import get_settings
from ..schemas import ComplaintForm, RiskAssessment
from .rules import merge_complaint

_CURRENT_YEAR = date.today().year

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = f"""You are a pharmaceutical complaint data extraction assistant.
Today's year is {_CURRENT_YEAR}.

TOOL CONTEXT — decide which tool applies:
  • LOG COMPLAINT TOOL  : user is reporting a NEW complaint (first message or document text)
  • EDIT COMPLAINT TOOL : user is correcting or adding a detail to an existing complaint
                         (keywords: "change", "update", "correct", "I made a mistake", "sorry", "it should be")

FIELD DEFINITIONS — map natural language to EXACTLY these Python field names:
  customer_source        → source channel (e.g. "Direct Customer", "Distributor", "Document upload")
  customer_name          → customer or company name (e.g. "Apollo Pharmacy", "Northstar Pharma")
  product_name           → pharmaceutical product name (e.g. "Amoxicillin Capsules", "Metformin Hydrochloride API")
  product_strength_grade → dosage strength or grade (e.g. "500 mg", "IP/BP", "250 mg/5 ml")
  batch_lot_number       → batch number or lot number (e.g. "AMX240602", "MFH260712A")
  manufacturing_date     → when the product was made; phrases: "manufacturing date", "mfg date", "manufacture date", "manufactured in"
  expiry_date            → product expiry; phrases: "expiry date", "expiration date", "exp date", "expires"
  affected_quantity      → how many units/kg affected (e.g. "48 capsules", "50 kg", "2 HDPE drums")
  complaint_type         → category (e.g. "Product appearance", "Packaging defect", "Potential contamination", "Performance issue")
  complaint_date         → when the complaint was filed; phrases: "complaint date", "date of complaint", "reported date", "reported on"
  detailed_complaint_description → full narrative of the complaint issue

DATE FORMATTING RULES:
  "25 September" or "September 25"           → "{_CURRENT_YEAR}-09-25"
  "25 September 2025" or "September 25 2025" → "2025-09-25"
  "April 2026" / "March 2026"               → keep as-is: "April 2026"
  "2026-03-15"                              → keep as-is

LOG COMPLAINT TOOL RULES (new complaint or document upload):
  1. Extract every fact explicitly stated in the message.
  2. Set detailed_complaint_description to the full complaint text.
  3. Infer complaint_type from the issue described if clearly supported.
  4. If customer_source not stated and this is a document/email → "Document upload".
  5. If customer_source not stated and this is a chat message → "Direct Customer".

EDIT COMPLAINT TOOL RULES (correction/update to existing form):
  1. Extract ONLY the field(s) the user is correcting or adding.
  2. Set ALL other fields to null — do NOT copy from CURRENT STATE.
  3. Do NOT update detailed_complaint_description for short corrections (< 120 chars).
  4. Do NOT invent or hallucinate values not stated in the message.

UNIVERSAL RULES:
  • Never invent batch numbers, dates, or quantities not explicitly stated.
  • If a field is not mentioned in the message, output null for that field.
"""

ASSESSMENT_PROMPT = f"""You are a senior pharmaceutical Quality Assurance expert.
Today's year is {_CURRENT_YEAR}.

Review the complaint data and produce a professional, reasoned Risk Assessment.

SEVERITY CLASSIFICATION:
  Critical  → patient-safety risk, contamination, microbial issue, wrong product, foreign matter, sterility failure
  Major     → visible quality defect: discoloration, leakage, broken seal, dissolution failure, labelling error
  Minor     → administrative or informational complaint without a clear quality/safety signal
  Pending assessment → insufficient data

PRIORITY:
  Urgent → Critical severity OR potential recall/regulatory risk
  High   → Major severity OR multiple customers affected
  Normal → Minor severity, routine triage
  Low    → Informational only

Fill ALL output fields:
  severity, priority, suggested_next_action, rationale, root_cause_hypotheses (2-3 items),
  capa_recommendation.
  Set completeness_score=0 and missing_fields=[] — they are calculated deterministically.
"""


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------

class IntakeState(TypedDict, total=False):
    text: str
    current: ComplaintForm
    extracted: ComplaintForm
    complaint: ComplaintForm
    risk_assessment: RiskAssessment
    assistant_message: str
    mode: str
    extracted_fields: list[str]
    ai_provider: str   # "groq" | "gemini"


# ---------------------------------------------------------------------------
# LLM builders
# ---------------------------------------------------------------------------

def _groq_client(temperature: float = 0):
    from langchain_groq import ChatGroq
    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY not configured")
    return ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=temperature,
    )


def _gemini_client(temperature: float = 0):
    from langchain_google_genai import ChatGoogleGenerativeAI
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=temperature,
    )


def _get_client(temperature: float = 0):
    """Return (client, provider_name). Tries Groq first, falls back to Gemini."""
    try:
        return _groq_client(temperature), "groq"
    except Exception:
        pass
    try:
        return _gemini_client(temperature), "gemini"
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Both Groq and Gemini are unavailable. "
                "Add GROQ_API_KEY or GEMINI_API_KEY to environment variables."
            ),
        )


# ---------------------------------------------------------------------------
# Core LLM functions
# ---------------------------------------------------------------------------

def _llm_extract(text: str, current: ComplaintForm) -> tuple[ComplaintForm, str]:
    """Returns (extracted_form, provider_name). Tries Groq → Gemini automatically."""
    settings = get_settings()
    current_json = current.model_dump_json(exclude_none=True)
    prompt = (
        f"{EXTRACTION_PROMPT}\n\n"
        f"CURRENT STATE (already in the form):\n{current_json}\n\n"
        f"NEW USER MESSAGE:\n{text}"
    )

    # Try Groq first
    if settings.groq_api_key:
        try:
            model = _groq_client(0).with_structured_output(ComplaintForm)
            return model.invoke(prompt), "groq"
        except Exception:
            pass  # Fall through to Gemini

    # Fallback: Gemini
    if settings.gemini_api_key:
        try:
            model = _gemini_client(0).with_structured_output(ComplaintForm)
            return model.invoke(prompt), "gemini"
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Gemini extraction failed: {exc}",
            ) from exc

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="No AI provider configured. Add GROQ_API_KEY or GEMINI_API_KEY.",
    )


def _llm_assess(complaint: ComplaintForm, provider: str) -> RiskAssessment:
    """Generate risk assessment. Uses the same provider as extraction."""
    settings = get_settings()
    complaint_json = complaint.model_dump_json(exclude_none=True)
    prompt = f"{ASSESSMENT_PROMPT}\n\nCOMPLAINT DATA:\n{complaint_json}"

    if provider == "groq" and settings.groq_api_key:
        try:
            model = _groq_client(0.2).with_structured_output(RiskAssessment)
            assessment = model.invoke(prompt)
        except Exception:
            provider = "gemini"  # retry with Gemini

    if provider == "gemini" and settings.gemini_api_key:
        try:
            model = _gemini_client(0.2).with_structured_output(RiskAssessment)
            assessment = model.invoke(prompt)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Risk assessment failed: {exc}",
            ) from exc

    # Deterministic completeness — LLMs are unreliable at counting
    required = {
        "Customer": complaint.customer_name,
        "Product": complaint.product_name,
        "Batch / lot": complaint.batch_lot_number,
        "Affected quantity": complaint.affected_quantity,
        "Complaint description": complaint.detailed_complaint_description,
    }
    missing = [name for name, value in required.items() if not value]
    score = round((len(required) - len(missing)) / len(required) * 100)
    assessment.missing_fields = missing
    assessment.completeness_score = score
    return assessment


# ---------------------------------------------------------------------------
# LangGraph nodes
# ---------------------------------------------------------------------------

def extract_node(state: IntakeState) -> dict:
    extracted, provider = _llm_extract(state["text"], state.get("current", ComplaintForm()))
    return {"extracted": extracted, "mode": "llm", "ai_provider": provider}


def merge_node(state: IntakeState) -> dict:
    complaint, fields = merge_complaint(state["current"], state["extracted"])
    return {"complaint": complaint, "extracted_fields": fields}


def assess_node(state: IntakeState) -> dict:
    provider = state.get("ai_provider", "groq")
    assessment = _llm_assess(state["complaint"], provider)

    extracted_fields = state.get("extracted_fields", [])
    display_fields = [
        f.replace("_", " ")
        for f in extracted_fields
        if f != "detailed_complaint_description"
    ]

    provider_label = "Groq" if provider == "groq" else "Gemini"
    if display_fields:
        field_note = ", ".join(display_fields)
        response = (
            f"✅ [{provider_label}] Updated: {field_note}. "
            f"Risk: {assessment.severity} / {assessment.priority}."
        )
    else:
        response = (
            f"[{provider_label}] Reviewed the complaint. "
            f"Risk: {assessment.severity} / {assessment.priority}."
        )

    return {"risk_assessment": assessment, "assistant_message": response}


# ---------------------------------------------------------------------------
# Graph wiring
# ---------------------------------------------------------------------------

def _build_graph():
    graph = StateGraph(IntakeState)
    graph.add_node("extract", extract_node)
    graph.add_node("merge", merge_node)
    graph.add_node("assess", assess_node)
    graph.add_edge(START, "extract")
    graph.add_edge("extract", "merge")
    graph.add_edge("merge", "assess")
    graph.add_edge("assess", END)
    return graph.compile()


_intake_graph = _build_graph()


def run_intake(text: str, current: ComplaintForm) -> dict:
    """Entry point for Log Complaint, Edit Complaint, and Document Extract tools."""
    return _intake_graph.invoke({"text": text, "current": current})


# ---------------------------------------------------------------------------
# AI health check — used by /api/health/ai endpoint
# ---------------------------------------------------------------------------

def check_ai_health() -> dict:
    """
    Returns {"groq": "ok"|"error", "gemini": "ok"|"error", "active": "groq"|"gemini"|"none"}
    Used by the frontend status dot.
    """
    settings = get_settings()
    result = {"groq": "error", "gemini": "error", "active": "none"}

    if settings.groq_api_key:
        try:
            _groq_client(0).invoke("ping")
            result["groq"] = "ok"
            result["active"] = "groq"
        except Exception:
            pass

    if result["active"] == "none" and settings.gemini_api_key:
        try:
            _gemini_client(0).invoke("ping")
            result["gemini"] = "ok"
            result["active"] = "gemini"
        except Exception:
            pass

    return result
