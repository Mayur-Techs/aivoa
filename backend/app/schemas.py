from typing import Literal

from pydantic import BaseModel, Field


class ComplaintForm(BaseModel):
    customer_source: str | None = None
    customer_name: str | None = None
    product_name: str | None = None
    product_strength_grade: str | None = None
    batch_lot_number: str | None = None
    # Dates can be full (2026-03-15) or partial (March 2026); never invent a day.
    manufacturing_date: str | None = None
    expiry_date: str | None = None
    affected_quantity: str | None = None
    complaint_type: str | None = None
    complaint_date: str | None = None
    detailed_complaint_description: str | None = None
    initial_severity: str | None = None
    priority: str | None = None


class RiskAssessment(BaseModel):
    severity: Literal["Critical", "Major", "Minor", "Pending assessment"]
    priority: Literal["Urgent", "High", "Normal", "Low", "Pending triage"]
    suggested_next_action: str
    rationale: str
    completeness_score: int = Field(ge=0, le=100)
    missing_fields: list[str] = Field(default_factory=list)
    root_cause_hypotheses: list[str] = Field(default_factory=list)
    capa_recommendation: str


class AssistantRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    current_complaint: ComplaintForm = Field(default_factory=ComplaintForm)


class AssistantResponse(BaseModel):
    complaint: ComplaintForm
    risk_assessment: RiskAssessment
    assistant_message: str
    mode: Literal["llm", "rules"]
    extracted_fields: list[str] = Field(default_factory=list)


class SavedComplaint(BaseModel):
    id: int
    complaint: ComplaintForm
    risk_assessment: RiskAssessment
