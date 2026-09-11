import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import { sendChat, uploadComplaintDocument } from "../../api/client";
import type { AssistantResponse, ChatMessage, ComplaintForm, RiskAssessment } from "../../types";

const initialComplaint: ComplaintForm = {};
const initialRisk: RiskAssessment = {
  severity: "Pending assessment",
  priority: "Pending triage",
  suggested_next_action: "Share a complaint description or upload a document to begin triage.",
  rationale: "The AI co-pilot will assess risk once complaint details are available.",
  completeness_score: 0,
  missing_fields: ["Customer", "Product", "Batch / lot", "Affected quantity", "Complaint description"],
  root_cause_hypotheses: [],
  capa_recommendation: "A CAPA recommendation will be generated after complaint intake.",
};

type IntakeState = {
  complaint: ComplaintForm;
  risk: RiskAssessment;
  messages: ChatMessage[];
  isProcessing: boolean;
  error: string | null;
  lastResponse: AssistantResponse | null;
};

const getMessage = (error: unknown) => (error instanceof Error ? error.message : "Something went wrong. Please try again.");

export const submitChat = createAsyncThunk(
  "complaint/submitChat",
  async ({ message, current }: { message: string; current: ComplaintForm }) => sendChat(message, current),
);

export const submitDocument = createAsyncThunk(
  "complaint/submitDocument",
  async ({ file, current }: { file: File; current: ComplaintForm }) => uploadComplaintDocument(file, current),
);

const initialState: IntakeState = {
  complaint: initialComplaint,
  risk: initialRisk,
  messages: [
    {
      id: "welcome",
      role: "assistant",
      content: "Describe the complaint in plain language, upload a document, or correct a field later. I will update the intake form for you.",
    },
  ],
  isProcessing: false,
  error: null,
  lastResponse: null,
};

const addResponse = (state: IntakeState, response: AssistantResponse) => {
  state.complaint = response.complaint;
  state.risk = response.risk_assessment;
  state.lastResponse = response;
  state.messages.push({ id: crypto.randomUUID(), role: "assistant", content: response.assistant_message });
};

const complaintSlice = createSlice({
  name: "complaint",
  initialState,
  reducers: {
    addUserMessage(state, action: { payload: string }) {
      state.messages.push({ id: crypto.randomUUID(), role: "user", content: action.payload });
      state.error = null;
    },
    resetIntake: () => initialState,
    clearError(state) {
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(submitChat.pending, (state) => { state.isProcessing = true; state.error = null; })
      .addCase(submitDocument.pending, (state) => { state.isProcessing = true; state.error = null; })
      .addCase(submitChat.fulfilled, (state, action) => { state.isProcessing = false; addResponse(state, action.payload); })
      .addCase(submitDocument.fulfilled, (state, action) => { state.isProcessing = false; addResponse(state, action.payload); })
      .addCase(submitChat.rejected, (state, action) => { state.isProcessing = false; state.error = getMessage(action.error); })
      .addCase(submitDocument.rejected, (state, action) => { state.isProcessing = false; state.error = getMessage(action.error); });
  },
});

export const { addUserMessage, clearError, resetIntake } = complaintSlice.actions;
export default complaintSlice.reducer;
