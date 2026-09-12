from typing import TypedDict
import json

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


EXTRACTION_PROMPT = """You are an AI assistant processing pharmaceutical customer complaints.
You are given the CURRENT STATE of a complaint form, and a NEW USER MESSAGE (which might be an initial report, a document upload, or a correction).
Your task is to extract ONLY the new or updated structured facts from the new message.
Do not invent traceability details. Do not repeat fields that are already in the CURRENT STATE unless they are being corrected.
For a correction, return only the changed fields. Infer a concise complaint_type only when the text clearly supports it.
Use ISO dates when dates are explicit. Put the original statement in detailed_complaint_description only for a new complaint or document, not a correction.
"""

ASSESSMENT_PROMPT = """You are an AI Quality Assurance expert. Review the following pharmaceutical complaint and generate a Risk Assessment based on your own reasoning.
Classify the severity (Critical, Major, Minor, Pending assessment) and priority (Urgent, High, Normal, Low, Pending triage).
Provide a clear suggested_next_action (e.g. Route to QA investigation, quarantine stock, issue replacement).
Provide a rationale explaining your classification.
Provide 1 to 3 root_cause_hypotheses that QA should investigate (e.g. Review batch manufacturing records, check retained samples).
Provide a capa_recommendation (Corrective and Preventive Action) based on the likely root cause.
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
    prompt = f"{EXTRACTION_PROMPT}\n\nCURRENT STATE:\n{current_json}\n\nNEW MESSAGE:\n{text}"
    return model.invoke(prompt)

def _llm_assess(complaint: ComplaintForm) -> RiskAssessment:
    from langchain_groq import ChatGroq

    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    model = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=0.2, # slightly higher for reasoning 
    ).with_structured_output(RiskAssessment)
    
    complaint_json = complaint.model_dump_json(exclude_none=True)
    prompt = f"{ASSESSMENT_PROMPT}\n\nCOMPLAINT DATA:\n{complaint_json}"
    assessment = model.invoke(prompt)
    
    # Deterministically calculate missing fields & score to ensure accuracy
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
        return {"extracted": _llm_extract(state["text"], state.get("current", ComplaintForm())), "mode": "llm"}
    except Exception:
        # A local deterministic fallback keeps demonstrations useful without credentials or during provider outages.
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
        
    field_note = ", ".join(field.replace("_", " ") for field in state.get("extracted_fields", []))
    response = (
        f"I updated {field_note}. " if field_note else "I reviewed the complaint. "
    ) + f"Current triage: {assessment.severity} severity / {assessment.priority} priority."
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
