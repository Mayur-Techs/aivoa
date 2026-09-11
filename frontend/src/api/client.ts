import type { AssistantResponse, ComplaintForm, RiskAssessment } from "../types";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, options: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(payload.detail ?? "Request failed");
  }
  return response.json() as Promise<T>;
}

export function sendChat(message: string, currentComplaint: ComplaintForm): Promise<AssistantResponse> {
  return request("/api/ai/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, current_complaint: currentComplaint }),
  });
}

export function uploadComplaintDocument(file: File, currentComplaint: ComplaintForm): Promise<AssistantResponse> {
  const data = new FormData();
  data.append("file", file);
  data.append("current_complaint", JSON.stringify(currentComplaint));
  return request("/api/documents/extract", { method: "POST", body: data });
}

export function saveComplaint(payload: AssistantResponse): Promise<{ id: number; complaint: ComplaintForm; risk_assessment: RiskAssessment }> {
  return request("/api/complaints", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
