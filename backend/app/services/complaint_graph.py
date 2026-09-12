from datetime import date
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ..config import get_settings
from ..schemas import ComplaintForm, RiskAssessment
from .rules import assess, merge_complaint, rule_extract


class IntakeState(TypedDict, total=False):
    text: str
    current: ComplaintForm
    extracted: ComplaintForm
    complaint: ComplaintForm
    risk_assessment: RiskAssessment
    assistant_message: str
    mode: str
    extracted_fields: list[str]


# Current year injected so the LLM can resolve "25 September" → "2026-09-25"
_CURRENT_YEAR = date.today().year

EXTRACTION_PROMPT = f"""You are a data extraction assistant for a pharmaceutical complaint management system.
Today's year is {_CURRENT_YEAR}.

FIELD DEFINITIONS — map the user's natural language to EXACTLY these field names:
  customer_source      → where the complaint came from (e.g. "Direct Customer", "Distributor", "Document upload")
  customer_name        → name of the customer or company filing the complaint (e.g. "Apollo Pharmacy")
  product_name         → pharmaceutical product name (e.g. "Amoxicillin Capsules", "Metformin Hydrochloride API")
  product_strength_grade → dosage strength or grade (e.g. "500 mg", "IP/BP", "250 mg/5 ml")
  batch_lot_number     → batch number or lot number (e.g. "AMX240602", "MFH260712A")
  manufacturing_date   → date the product was manufactured; user may say "manufacturing date", "mfg date", "manufacture date"
  expiry_date          → expiry/expiration date of the product; user may say "expiry date", "expiration date", "exp date"
  affected_quantity    → how many units are affected (e.g. "48 capsules", "50 kg", "2 HDPE drums")
  complaint_type       → category of complaint (e.g. "Product appearance", "Packaging defect", "Potential contamination")
  complaint_date       → the date the complaint was filed/received; user may say "complaint date", "date of complaint", "reported date"
  detailed_complaint_description → full description of what happened (only set for NEW complaints or documents, NOT for short corrections)

DATE FORMATTING RULES:
  - Full date like "25 September" or "September 25" → use year {_CURRENT_YEAR}: output "2026-09-25"
  - "25 September 2025" → output "2025-09-25"
  - "April 2026" or "March 2026" → output as-is: "April 2026", "March 2026"
  - ISO dates like "2026-03-15" → keep as-is

INSTRUCTIONS:
  1. You receive CURRENT STATE (what is already in the form) and a NEW USER MESSAGE.
  2. If the message is a CORRECTION (user says "change X", "I made a mistake in X", "update X", "correct X"):
     - Extract ONLY the field(s) being corrected.
     - Set all other fields to null — do NOT copy from CURRENT STATE.
  3. If the message is a NEW COMPLAINT or DOCUMENT UPLOAD:
     - Extract all facts mentioned. Set detailed_complaint_description to the full text.
  4. Do NOT invent values. Do NOT hallucinate field values not stated in the message.
  5. Do NOT repeat fields that are already correct in CURRENT STATE.
  6. If a field is not mentioned in the NEW MESSAGE, set it to null in your output.
"""

ASSESSMENT_PROMPT = """You are an AI Quality Assurance expert reviewing a pharmaceutical customer complaint.
Generate a professional Risk Assessment based on your reasoning about the complaint.

SEVERITY GUIDANCE:
  - Critical: contamination, microbial issue, patient safety risk, wrong product, foreign matter
  - Major: discoloration, leakage, broken/defective packaging, dissolution failure, labelling issue
  - Minor: general complaints without a clear safety or quality defect signal

OUTPUT REQUIREMENTS:
  - severity: one of "Critical", "Major", "Minor", "Pending assessment"
  - priority: one of "Urgent", "High", "Normal", "Low", "Pending triage"
  - suggested_next_action: a concrete, professional QA action (e.g. "Route to QA investigation and issue replacement")
  - rationale: 1-2 sentences explaining your classification
  - root_cause_hypotheses: 2-3 specific investigation cues for QA (e.g. "Review batch manufacturing records for lot AMX240602")
  - capa_recommendation: one concrete CAPA sentence
  - completeness_score and missing_fields will be filled automatically — set them to 0 and [] respectively
"""


def _llm_extract(text: str, current: ComplaintForm) -> ComplaintForm:
    from langchain_groq import ChatGroq

    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    model = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=0,
    ).with_structured_output(ComplaintForm)

    current_json = current.model_dump_json(exclude_none=True)
    prompt = (
        f"{EXTRACTION_PROMPT}\n\n"
        f"CURRENT STATE:\n{current_json}\n\n"
        f"NEW USER MESSAGE:\n{text}"
    )
    return model.invoke(prompt)


def _llm_assess(complaint: ComplaintForm) -> RiskAssessment:
    from langchain_groq import ChatGroq

    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    model = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=0.2,
    ).with_structured_output(RiskAssessment)

    complaint_json = complaint.model_dump_json(exclude_none=True)
    prompt = f"{ASSESSMENT_PROMPT}\n\nCOMPLAINT DATA:\n{complaint_json}"
    assessment = model.invoke(prompt)

    # Always calculate these deterministically — LLMs are unreliable at counting
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


def extract_node(state: IntakeState) -> dict:
    try:
        extracted = _llm_extract(state["text"], state.get("current", ComplaintForm()))
        return {"extracted": extracted, "mode": "llm"}
    except Exception:
        # Conservative regex fallback — keeps demo useful without API key or during outages
        return {"extracted": rule_extract(state["text"]), "mode": "rules"}


def merge_node(state: IntakeState) -> dict:
    complaint, fields = merge_complaint(state["current"], state["extracted"])
    return {"complaint": complaint, "extracted_fields": fields}


def assess_node(state: IntakeState) -> dict:
    mode = state.get("mode", "rules")
    if mode == "llm":
        try:
            assessment = _llm_assess(state["complaint"])
        except Exception:
            assessment = assess(state["complaint"])
    else:
        assessment = assess(state["complaint"])

    extracted_fields = state.get("extracted_fields", [])
    # Filter out noisy fields from the "updated" message (description is implicit)
    display_fields = [
        f.replace("_", " ")
        for f in extracted_fields
        if f != "detailed_complaint_description"
    ]

    if display_fields:
        field_note = ", ".join(display_fields)
        response = f"✅ Updated: {field_note}. Current triage: {assessment.severity} severity / {assessment.priority} priority."
    else:
        response = (
            f"I reviewed the complaint but didn't detect any field changes in your message. "
            f"Try saying something like: \"change the complaint date to 25 September\" or "
            f"\"update batch number to XYZ123\". "
            f"Current triage: {assessment.severity} / {assessment.priority}."
        )
    return {"risk_assessment": assessment, "assistant_message": response}


def build_graph():
    graph = StateGraph(IntakeState)
    graph.add_node("extract", extract_node)
    graph.add_node("merge", merge_node)
    graph.add_node("assess", assess_node)
    graph.add_edge(START, "extract")
    graph.add_edge("extract", "merge")
    graph.add_edge("merge", "assess")
    graph.add_edge("assess", END)
    return graph.compile()


intake_graph = build_graph()


def run_intake(text: str, current: ComplaintForm) -> dict:
    return intake_graph.invoke({"text": text, "current": current})
