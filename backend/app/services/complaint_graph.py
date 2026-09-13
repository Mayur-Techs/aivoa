"""
AIVOA LangGraph pipeline — strict LLM-only mode.

Three tools:
  1. Log Complaint   — extract + risk-assess a new natural-language complaint
  2. Edit Complaint  — targeted field update, re-evaluate risk assessment
  3. Document Extract — parse uploaded document text, same pipeline as Log Complaint
"""

from datetime import date
from typing import TypedDict

from fastapi import HTTPException, status
from langgraph.graph import END, START, StateGraph

from ..config import get_settings
from ..schemas import ComplaintForm, RiskAssessment
from .rules import merge_complaint  # merge logic is pure Python — kept

_CURRENT_YEAR = date.today().year


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = f"""You are a pharmaceutical complaint data extraction assistant.
Today's year is {_CURRENT_YEAR}.

TOOL CONTEXT — decide which tool applies to the user message:
  • LOG COMPLAINT TOOL  : user is reporting a NEW complaint (first message or document text)
  • EDIT COMPLAINT TOOL : user is correcting or adding a specific detail to an existing complaint
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
  "25 September" or "September 25"          → "{_CURRENT_YEAR}-09-25"
  "25 September 2025" or "September 25 2025"→ "2025-09-25"
  "April 2026" / "March 2026"               → keep as-is: "April 2026"
  "2026-03-15"                              → keep as-is

LOG COMPLAINT TOOL RULES (new complaint or document upload):
  1. Extract every fact explicitly stated in the message.
  2. Set detailed_complaint_description to the full complaint text.
  3. Infer complaint_type from the issue described if clearly supported.
  4. If customer_source is not stated and this is a document/email, set it to "Document upload".
  5. If customer_source is not stated and this is a chat message, set it to "Direct Customer".

EDIT COMPLAINT TOOL RULES (correction/update to existing form):
  1. Extract ONLY the field(s) the user is correcting or adding.
  2. Set ALL other fields to null — do NOT copy from CURRENT STATE.
  3. Do NOT update detailed_complaint_description for short corrections (< 120 chars of new text).
  4. Do NOT invent or hallucinate values not stated in the message.

UNIVERSAL RULES:
  • Never invent batch numbers, dates, or quantities not explicitly stated.
  • If a field is not mentioned in the message, output null for that field.
"""

ASSESSMENT_PROMPT = f"""You are a senior pharmaceutical Quality Assurance expert.
Today's year is {_CURRENT_YEAR}.

Review the complaint data below and produce a professional, reasoned Risk Assessment.
Use your domain knowledge about pharmaceutical quality defects and GMP regulations.

SEVERITY CLASSIFICATION GUIDE:
  Critical  → patient-safety risk, contamination, microbial issue, wrong product, foreign matter, sterility failure
  Major     → visible quality defect: discoloration, leakage, broken seal, dissolution failure, labelling error, HDPE drum integrity issue
  Minor     → administrative or informational complaint without a clear quality/safety signal
  Pending assessment → insufficient data to classify

PRIORITY GUIDE:
  Urgent → Critical severity OR potential regulatory/recall risk
  High   → Major severity OR multiple customers affected
  Normal → Minor severity, routine triage
  Low    → Informational only

OUTPUT FIELDS — fill all of them:
  severity               → one of: "Critical", "Major", "Minor", "Pending assessment"
  priority               → one of: "Urgent", "High", "Normal", "Low", "Pending triage"
  suggested_next_action  → concrete, professional QA action sentence
                           (e.g. "Route to QA investigation, retain complaint evidence, and issue replacement batch")
  rationale              → 2-3 sentences of domain reasoning explaining your classification
  root_cause_hypotheses  → list of 2–3 specific, actionable investigation cues tied to the actual batch/product
                           (e.g. "Review batch manufacturing records for lot {{batch_lot_number}}")
  capa_recommendation    → one concrete CAPA sentence appropriate for the defect type
  completeness_score     → set to 0  (calculated deterministically after you respond)
  missing_fields         → set to [] (calculated deterministically after you respond)
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


# ---------------------------------------------------------------------------
# LLM helpers — no fallback, raises on any error
# ---------------------------------------------------------------------------

def _get_groq_client(temperature: float = 0):
    """Return a configured ChatGroq instance. Raises HTTP 503 if key is missing."""
    from langchain_groq import ChatGroq

    settings = get_settings()
    if not settings.groq_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "GROQ_API_KEY is not configured. "
                "Add it to the backend environment variables and redeploy."
            ),
        )
    return ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=temperature,
    )


def _llm_extract(text: str, current: ComplaintForm) -> ComplaintForm:
    """
    Tool 1 & 2 & 3: extract or update complaint fields using the LLM.
    Raises HTTPException on failure — no silent fallback.
    """
    model = _get_groq_client(temperature=0).with_structured_output(ComplaintForm)
    current_json = current.model_dump_json(exclude_none=True)
    prompt = (
        f"{EXTRACTION_PROMPT}\n\n"
        f"CURRENT STATE (already in the form):\n{current_json}\n\n"
        f"NEW USER MESSAGE:\n{text}"
    )
    try:
        return model.invoke(prompt)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Groq extraction failed: {exc}",
        ) from exc


def _llm_assess(complaint: ComplaintForm) -> RiskAssessment:
    """
    Tool 1 & 2 & 3: generate AI risk assessment using the LLM.
    Raises HTTPException on failure — no silent fallback.
    """
    model = _get_groq_client(temperature=0.2).with_structured_output(RiskAssessment)
    complaint_json = complaint.model_dump_json(exclude_none=True)
    prompt = f"{ASSESSMENT_PROMPT}\n\nCOMPLAINT DATA:\n{complaint_json}"
    try:
        assessment = model.invoke(prompt)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Groq risk assessment failed: {exc}",
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
    """
    Calls the LLM extraction tool.
    Raises HTTPException if the API key is missing or Groq is unavailable.
    No fallback — strict LLM-only mode as required.
    """
    extracted = _llm_extract(state["text"], state.get("current", ComplaintForm()))
    return {"extracted": extracted, "mode": "llm"}


def merge_node(state: IntakeState) -> dict:
    complaint, fields = merge_complaint(state["current"], state["extracted"])
    return {"complaint": complaint, "extracted_fields": fields}


def assess_node(state: IntakeState) -> dict:
    """
    Calls the LLM risk assessment tool.
    Raises HTTPException if Groq is unavailable — no rule fallback.
    """
    assessment = _llm_assess(state["complaint"])

    extracted_fields = state.get("extracted_fields", [])
    display_fields = [
        f.replace("_", " ")
        for f in extracted_fields
        if f != "detailed_complaint_description"
    ]

    if display_fields:
        field_note = ", ".join(display_fields)
        response = (
            f"✅ Updated: {field_note}. "
            f"Risk assessment: {assessment.severity} severity / {assessment.priority} priority."
        )
    else:
        response = (
            f"I reviewed the complaint. "
            f"Risk assessment: {assessment.severity} severity / {assessment.priority} priority."
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
    """
    Entry point for all three tools:
      • Log Complaint Tool   — new natural-language complaint text
      • Edit Complaint Tool  — correction/update message with existing form state
      • Document Extract Tool — parsed document text with empty/existing form state
    """
    return _intake_graph.invoke({"text": text, "current": current})
