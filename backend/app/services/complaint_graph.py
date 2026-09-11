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


EXTRACTION_PROMPT = """You extract structured pharmaceutical customer-complaint facts.
Return only facts explicitly stated in the new message. Do not invent traceability details.
For a correction, return only the changed fields. Infer a concise complaint_type only when the text clearly supports it.
Use ISO dates when dates are explicit. Put the original statement in detailed_complaint_description only for a new complaint or document, not a correction.
"""


def _llm_extract(text: str) -> ComplaintForm:
    from langchain_groq import ChatGroq

    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    model = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=0,
    ).with_structured_output(ComplaintForm)
    return model.invoke(f"{EXTRACTION_PROMPT}\n\nNew message:\n{text}")


def extract_node(state: IntakeState) -> dict:
    try:
        return {"extracted": _llm_extract(state["text"]), "mode": "llm"}
    except Exception:
        # A local deterministic fallback keeps demonstrations useful without credentials or during provider outages.
        return {"extracted": rule_extract(state["text"]), "mode": "rules"}


def merge_node(state: IntakeState) -> dict:
    complaint, fields = merge_complaint(state["current"], state["extracted"])
    return {"complaint": complaint, "extracted_fields": fields}


def assess_node(state: IntakeState) -> dict:
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
