import { useEffect, useRef, useState } from "react";
import type { ChangeEvent, FormEvent, KeyboardEvent } from "react";
import { useDispatch, useSelector } from "react-redux";
import { saveComplaint } from "./api/client";
import type { AppDispatch, RootState } from "./app/store";
import { addUserMessage, clearError, resetIntake, submitChat, submitDocument } from "./features/complaint/complaintSlice";
import { createVoiceRecognition } from "./features/complaint/speechRecognition";
import type { VoiceRecognition } from "./features/complaint/speechRecognition";
import type { ChatMessage } from "./types";

const fieldGroups = [
  { title: "1. Origin & customer details", fields: [["Customer source", "customer_source"], ["Customer name", "customer_name"]] },
  { title: "2. Product & batch identification", fields: [["Product name", "product_name"], ["Product strength / grade", "product_strength_grade"], ["Batch / lot number", "batch_lot_number"], ["Manufacturing date", "manufacturing_date"], ["Expiry date", "expiry_date"], ["Quantity affected", "affected_quantity"]] },
  { title: "3. Complaint details", fields: [["Complaint type", "complaint_type"], ["Complaint date", "complaint_date"]] },
] as const;

function FormField({ label, value }: { label: string; value?: string | null }) {
  return <label className="form-field"><span>{label}</span><input readOnly value={value ?? ""} placeholder="Awaiting AI extraction..." aria-label={label} /></label>;
}

function App() {
  const dispatch = useDispatch<AppDispatch>();
  const { complaint, risk, messages, isProcessing, error, lastResponse } = useSelector((state: RootState) => state.complaint);
  const [message, setMessage] = useState("");
  const [saveNotice, setSaveNotice] = useState<string | null>(null);
  const [voiceStatus, setVoiceStatus] = useState<"idle" | "listening" | "error">("idle");
  const [voiceNotice, setVoiceNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const composerInput = useRef<HTMLTextAreaElement>(null);
  const recognitionRef = useRef<VoiceRecognition | null>(null);

  useEffect(() => () => recognitionRef.current?.abort(), []);

  useEffect(() => {
    const input = composerInput.current;
    if (!input) return;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 144)}px`;
  }, [message]);

  const send = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = message.trim();
    if (!trimmed || isProcessing) return;
    dispatch(addUserMessage(trimmed));
    setMessage("");
    await dispatch(submitChat({ message: trimmed, current: complaint }));
  };

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || isProcessing) return;
    dispatch(addUserMessage(`Uploaded ${file.name} for extraction.`));
    await dispatch(submitDocument({ file, current: complaint }));
  };

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };

  const persist = async () => {
    if (!lastResponse) { setSaveNotice("Use the AI co-pilot to create a complaint before saving."); return; }
    try {
      const saved = await saveComplaint(lastResponse);
      setSaveNotice(`Complaint #${saved.id} saved successfully.`);
    } catch (saveError) {
      setSaveNotice(saveError instanceof Error ? saveError.message : "Unable to save complaint.");
    }
  };

  const startVoiceInput = () => {
    if (isProcessing || voiceStatus === "listening") return;
    const recognition = createVoiceRecognition();
    if (!recognition) {
      setVoiceStatus("error");
      setVoiceNotice("Speech-to-text is not supported in this browser. You can still type or upload a document.");
      return;
    }
    recognitionRef.current = recognition;
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0]?.transcript ?? "")
        .join(" ")
        .trim();
      if (transcript) setMessage((current) => `${current} ${transcript}`.trim());
    };
    recognition.onerror = (event) => {
      setVoiceStatus("error");
      setVoiceNotice(event.error === "not-allowed" ? "Microphone access was not allowed. Enable it in your browser settings and try again." : "I could not hear a transcript. Please try again or type your message.");
    };
    recognition.onend = () => setVoiceStatus((status) => (status === "error" ? "error" : "idle"));
    setVoiceNotice("Listening - speak your complaint or correction.");
    setVoiceStatus("listening");
    try {
      recognition.start();
    } catch {
      setVoiceStatus("error");
      setVoiceNotice("Microphone input is unavailable right now. Please try again or type your message.");
    }
  };

  return <main className="shell">
    <section className="intake-card" aria-label="Log customer complaint">
      <header className="panel-header">
        <div><h1>Log Customer Complaint</h1><p>API & FDF Quality Assurance Module</p></div>
        <span className="status-pill">Pending triage</span>
      </header>
      <div className="form-note"><span>✦</span> This is an AI-controlled form. Use the co-pilot to create or update every field.</div>
      {fieldGroups.map((group) => <section className="form-section" key={group.title}>
        <h2>{group.title}</h2>
        <div className="field-grid">{group.fields.map(([label, key]) => <FormField key={key} label={label} value={complaint[key]} />)}</div>
      </section>)}
      <section className="form-section complaint-description">
        <h2>Detailed complaint description</h2>
        <textarea readOnly value={complaint.detailed_complaint_description ?? ""} placeholder="Awaiting AI extraction..." aria-label="Detailed complaint description" />
      </section>
      <section className="risk-section">
        <div className="risk-heading"><div><p className="eyebrow">AI co-pilot risk assessment</p><h2>Decision support, not a final QA release</h2></div><span className={`severity ${risk.severity.toLowerCase()}`}>{risk.severity}</span></div>
        <div className="risk-grid">
          <article><span>Priority</span><strong>{risk.priority}</strong></article>
          <article><span>Completeness</span><strong>{risk.completeness_score}%</strong></article>
          <article className="wide"><span>Recommended next action</span><strong>{risk.suggested_next_action}</strong></article>
        </div>
        <p className="rationale">{risk.rationale}</p>
        {risk.missing_fields.length > 0 && <p className="missing"><strong>Still needed:</strong> {risk.missing_fields.join(" · ")}</p>}
        {risk.root_cause_hypotheses.length > 0 && <details><summary>QA investigation cues & CAPA recommendation</summary><ul>{risk.root_cause_hypotheses.map((item: string) => <li key={item}>{item}</li>)}</ul><p>{risk.capa_recommendation}</p></details>}
      </section>
      <footer className="form-actions">
        <button className="secondary" onClick={() => { dispatch(resetIntake()); setSaveNotice(null); }}>↻ Reset form</button>
        <button className="primary" onClick={persist}>▣ Save complaint</button>
      </footer>
      {saveNotice && <p className="save-notice" role="status">{saveNotice}</p>}
    </section>

    <section className="assistant-card" aria-label="AIVOA co-pilot">
      <header className="panel-header assistant-header"><div><p className="brand-mark">✦ <span>AIVOA</span></p><h1>Co-Pilot</h1><p>Complaint intake assistant</p></div><span className="beta">BETA</span></header>
      <button className="upload-zone" onClick={() => fileInput.current?.click()} disabled={isProcessing}>
        <span className="upload-icon">⇧</span><strong>Drop a complaint document here</strong><small>or click to browse · PDF, DOCX, TXT, CSV, EML · max 10 MB</small>
      </button>
      <input ref={fileInput} className="visually-hidden" type="file" accept=".pdf,.docx,.txt,.csv,.eml" onChange={upload} />
      <p className="or">or</p>
      <button className="paste-action" onClick={() => setMessage("Paste the complaint text or email content below:")}>▤ Paste complaint text / email</button>
      {isProcessing && <div className="progress" aria-live="polite"><div /><span>Extracting complaint facts and assessing risk...</span></div>}
      <section className="conversation" aria-live="polite">
        {messages.map((item: ChatMessage) => <div className={`message ${item.role}`} key={item.id}><span>{item.role === "assistant" ? "✦" : "You"}</span><p>{item.content}</p></div>)}
      </section>
      {error && <div className="error" role="alert"><span>{error}</span><button onClick={() => dispatch(clearError())}>Dismiss</button></div>}
      {voiceNotice && <p className={`voice-notice ${voiceStatus}`} role="status">{voiceNotice}</p>}
      <form className="composer" onSubmit={send}>
        <button className="attach" type="button" onClick={() => fileInput.current?.click()} disabled={isProcessing} aria-label="Attach complaint document" title="Attach complaint document">⌕</button>
        <textarea ref={composerInput} rows={1} value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={handleComposerKeyDown} placeholder="Message AIVOA Co-Pilot..." disabled={isProcessing} aria-label="Message AIVOA Co-Pilot" />
        <button className={`voice ${voiceStatus}`} type="button" onClick={startVoiceInput} disabled={isProcessing || voiceStatus === "listening"} aria-label="Speak complaint" aria-pressed={voiceStatus === "listening"} title="Speak complaint">
          {voiceStatus === "listening" ? "●" : "◉"}
        </button>
        <button className="send" type="submit" disabled={!message.trim() || isProcessing} aria-label="Send message">➤</button>
      </form>
      <p className="composer-hint">Enter to send · Shift + Enter for a new line</p>
      <p className="disclaimer">AI output supports QA triage. Verify all information before disposition.</p>
    </section>
  </main>;
}

export default App;
