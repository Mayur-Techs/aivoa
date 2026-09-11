export type ComplaintForm = {
  customer_source?: string | null;
  customer_name?: string | null;
  product_name?: string | null;
  product_strength_grade?: string | null;
  batch_lot_number?: string | null;
  manufacturing_date?: string | null;
  expiry_date?: string | null;
  affected_quantity?: string | null;
  complaint_type?: string | null;
  complaint_date?: string | null;
  detailed_complaint_description?: string | null;
  initial_severity?: string | null;
  priority?: string | null;
};

export type RiskAssessment = {
  severity: string;
  priority: string;
  suggested_next_action: string;
  rationale: string;
  completeness_score: number;
  missing_fields: string[];
  root_cause_hypotheses: string[];
  capa_recommendation: string;
};

export type AssistantResponse = {
  complaint: ComplaintForm;
  risk_assessment: RiskAssessment;
  assistant_message: string;
  mode: "llm" | "rules";
  extracted_fields: string[];
};

export type ChatMessage = {
  id: string;
  role: "assistant" | "user";
  content: string;
};
