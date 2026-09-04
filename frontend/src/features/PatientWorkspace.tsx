import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, api } from "../api/client";
import type {
  Artifact,
  GoalSuggestion,
  HomeProgramSuggestion,
  PatientDocumentSummary,
  PatientWorkspace as PatientWorkspaceData,
  Referral,
  TimelineEvent,
  WorkspaceUser,
} from "../api/types";
import { formatDate, formatTime } from "../lib/format";
import { ConfirmActionDialog } from "./ConfirmActionDialog";
import { PatientFormDialog } from "./PatientFormDialog";

type WorkspaceTab = "overview" | "documentation" | "care-plan" | "operations" | "safety";

const outcomeMeasures = [
  ["lefs", "LEFS"],
  ["odi", "ODI"],
  ["ndi", "NDI"],
  ["quickdash", "QuickDASH"],
  ["tug", "Timed Up and Go"],
  ["berg", "Berg Balance Scale"],
  ["psfs", "Patient-Specific Functional Scale"],
] as const;

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function dateInputValue(daysAhead = 0) {
  const date = new Date();
  date.setDate(date.getDate() + daysAhead);
  return date.toISOString().slice(0, 10);
}

interface PatientWorkspaceProps {
  patientId: string;
  user: WorkspaceUser;
  onClose: () => void;
}

export function PatientWorkspace({ patientId, user, onClose }: PatientWorkspaceProps) {
  const [workspace, setWorkspace] = useState<PatientWorkspaceData | null>(null);
  const [tab, setTab] = useState<WorkspaceTab>("overview");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showEdit, setShowEdit] = useState(false);
  const [showDeactivate, setShowDeactivate] = useState(false);

  const loadWorkspace = useCallback(async () => {
    setError("");
    try {
      setWorkspace(await api.workspace(patientId));
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load the protected patient workspace."));
    }
  }, [patientId]);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  useEffect(() => {
    setTab("overview");
    setNotice("");
  }, [patientId]);

  function report(message: string) {
    setNotice(message);
  }

  if (error) {
    return <section className="page-error" role="alert"><h2>Workspace unavailable</h2><p>{error}</p><button className="secondary-button" onClick={onClose}>Back to patients</button></section>;
  }
  if (!workspace) {
    return <section className="surface-card workspace-loading" aria-live="polite">Loading the protected patient workspace...</section>;
  }

  const tabs: Array<[WorkspaceTab, string]> = [["overview", "Overview"]];
  if (workspace.clinical) {
    tabs.push(["documentation", "Documentation"], ["care-plan", "Care plan"]);
  }
  if (workspace.operations) {
    tabs.push(["operations", "Operations"]);
  }
  if (workspace.safety) {
    tabs.push(["safety", "Safety & audit"]);
  }

  const clinical = workspace.clinical;
  const operations = workspace.operations;
  const patient = workspace.patient;
  return (
    <section className="patient-workspace" aria-labelledby="patient-workspace-title">
      <header className="workspace-chart-header">
        <div>
          <p className="eyebrow">Role-scoped patient workspace</p>
          <h2 id="patient-workspace-title">{patient.fullName}</h2>
          <p>{patient.medicalRecordNumber} · DOB {formatDate(patient.dateOfBirth)}</p>
          {clinical && <p className="chart-context"><strong>Diagnoses:</strong> {patient.diagnoses || "Not recorded"} <span aria-hidden="true">|</span> <strong>Precautions:</strong> {patient.precautions || "None recorded"}</p>}
        </div>
        <div className="button-row">
          {user.capabilities.canManageSchedule && <button className="secondary-button" onClick={() => setShowEdit(true)}>Edit patient</button>}
          {user.capabilities.canManageSchedule && patient.status !== "inactive" && <button className="text-action" onClick={() => setShowDeactivate(true)}>Deactivate</button>}
          <button className="secondary-button" onClick={onClose}>Close workspace</button>
        </div>
      </header>

      <WorkflowGrid workspace={workspace} onSelect={(nextTab) => setTab(nextTab)} />

      <nav className="workspace-tabs" aria-label="Patient workspace sections">
        {tabs.map(([value, label]) => <button key={value} className={tab === value ? "active" : ""} onClick={() => setTab(value)}>{label}</button>)}
      </nav>
      {notice && <p className="form-notice" role="status">{notice}</p>}

      {tab === "overview" && <OverviewPanel workspace={workspace} patientId={patientId} />}
      {tab === "documentation" && clinical && <DocumentationPanel workspace={workspace} patientId={patientId} refresh={loadWorkspace} report={report} />}
      {tab === "care-plan" && clinical && <CarePlanPanel workspace={workspace} patientId={patientId} refresh={loadWorkspace} report={report} />}
      {tab === "operations" && operations && <OperationsPanel workspace={workspace} patientId={patientId} refresh={loadWorkspace} report={report} />}
      {tab === "safety" && workspace.safety && <SafetyPanel workspace={workspace} />}

      {showEdit && (
        <PatientFormDialog
          patientId={patientId}
          canEditClinicalFields={Boolean(clinical)}
          onClose={() => setShowEdit(false)}
          onSave={(body) => api.updatePatient(patientId, body)}
          onSaved={async () => { setShowEdit(false); await loadWorkspace(); }}
        />
      )}
      {showDeactivate && (
        <ConfirmActionDialog
          eyebrow={patient.medicalRecordNumber}
          title={`Deactivate ${patient.fullName}?`}
          body="This marks the chart inactive. No records are deleted, and the patient can be reactivated at any time by editing their status."
          confirmLabel="Deactivate patient"
          onClose={() => setShowDeactivate(false)}
          onConfirm={async () => { await api.deactivatePatient(patientId); setShowDeactivate(false); await loadWorkspace(); }}
        />
      )}
    </section>
  );
}

function WorkflowGrid({ workspace, onSelect }: { workspace: PatientWorkspaceData; onSelect: (tab: WorkspaceTab) => void }) {
  const clinical = workspace.clinical;
  const operations = workspace.operations;
  const cards: Array<{ label: string; detail: string; tab: WorkspaceTab; available: boolean }> = [
    { label: "Progress & discharge drafts", detail: clinical ? `${clinical.artifacts.length} source-backed drafts` : "Clinical access required", tab: "documentation", available: Boolean(clinical) },
    { label: "Outcome tracking", detail: clinical ? `${clinical.outcomes.length} active measure trends` : "Clinical access required", tab: "care-plan", available: Boolean(clinical) },
    { label: "Compliance checks", detail: clinical ? `${clinical.complianceFindings.length} chart-level findings` : "Clinical access required", tab: "overview", available: Boolean(clinical) },
    { label: "Voice-to-note", detail: clinical ? "Reviewed transcript workflow" : "Clinical access required", tab: "documentation", available: Boolean(clinical) },
    { label: "Home program", detail: clinical ? `${clinical.homePrograms.length} program drafts / active plans` : "Clinical access required", tab: "care-plan", available: Boolean(clinical) },
    { label: "Patient instructions", detail: clinical ? "Reviewable visit-summary drafts" : "Clinical access required", tab: "documentation", available: Boolean(clinical) },
    { label: "Operations", detail: operations ? "Scheduling, intake, consent, billing, messages" : "Role access required", tab: "operations", available: Boolean(operations) },
    { label: "Timeline & handoff", detail: clinical ? `${clinical.timeline.length} recent events` : "Clinical access required", tab: "overview", available: Boolean(clinical) },
    { label: "Safety controls", detail: workspace.safety ? "Audit history and role controls" : "Authorized audit role required", tab: "safety", available: Boolean(workspace.safety) },
  ];
  return <div className="workflow-grid" aria-label="Requested workflow coverage">
    {cards.map((card) => <button key={card.label} disabled={!card.available} onClick={() => onSelect(card.tab)}>
      <strong>{card.label}</strong><small>{card.detail}</small>
    </button>)}
  </div>;
}

function OverviewPanel({ workspace, patientId }: { workspace: PatientWorkspaceData; patientId: string }) {
  const [timeline, setTimeline] = useState<TimelineEvent[]>(workspace.clinical?.timeline || []);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const clinical = workspace.clinical;

  useEffect(() => {
    setTimeline(workspace.clinical?.timeline || []);
  }, [workspace]);

  async function searchTimeline(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!clinical) return;
    setError("");
    try {
      const payload = await api.timeline(patientId, query);
      setTimeline(payload.events);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to search the clinical timeline."));
    }
  }

  return <div className="workspace-panel-grid">
    {clinical ? <>
      <article className="surface-card">
        <header className="card-heading"><div><p className="eyebrow">Compliance</p><h3>Clinical checks</h3></div></header>
        {clinical.complianceFindings.length ? <ul className="attention-list">{clinical.complianceFindings.map((finding) => <li key={finding.code}><span className={`severity-dot ${finding.severity}`} /><span><strong>{finding.title}</strong><small>{finding.detail}{finding.finalizationBlocker ? " Finalization blocker." : ""}</small></span></li>)}</ul> : <p className="empty-copy positive">No chart-level compliance findings are currently due.</p>}
        {clinical.notes.length > 0 && <div className="compact-subsection"><strong>Draft-note review</strong><ul className="summary-list">{clinical.notes.map((note) => <li key={note.id}><span><strong>{note.noteTypeLabel}</strong><small>{formatDate(note.serviceDate)} · {note.statusLabel}</small></span>{note.complianceFindings?.some((finding) => finding.finalizationBlocker) && <span className="status-pill review_required">Check required</span>}</li>)}</ul></div>}
      </article>
      <article className="surface-card">
        <header className="card-heading"><div><p className="eyebrow">Care progress</p><h3>Goals & outcomes</h3></div></header>
        <div className="summary-split">
          <div><strong>Measurable goals</strong>{clinical.goals.length ? <ul className="summary-list">{clinical.goals.map((goal) => <li key={goal.id}><strong>{goal.functionalTask}</strong><small>{goal.currentValue ?? goal.baselineValue} to {goal.targetValue} {goal.unit} · {goal.statusLabel}</small></li>)}</ul> : <p className="empty-copy">No goals recorded.</p>}</div>
          <div><strong>Outcome trends</strong>{clinical.outcomes.length ? <ul className="summary-list">{clinical.outcomes.map((outcome) => <li key={outcome.measure}><strong>{outcome.label}: {outcome.latest}{outcome.maximum !== null ? ` / ${outcome.maximum}` : ""}</strong><small>{outcome.trend} · change {outcome.delta} {outcome.unit}</small></li>)}</ul> : <p className="empty-copy">No scores recorded.</p>}</div>
        </div>
      </article>
      <article className="surface-card workspace-wide-card">
        <header className="card-heading"><div><p className="eyebrow">Clinical timeline</p><h3>Searchable chart events</h3><p className="muted">Search runs on the protected server. Results identify matching events without returning note narrative in the timeline.</p></div></header>
        <form className="inline-form" onSubmit={searchTimeline}><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search note type, outcome, or clinical text" aria-label="Search clinical timeline" /><button className="secondary-button" type="submit">Search timeline</button></form>
        {error && <p className="form-error" role="alert">{error}</p>}
        {timeline.length ? <ol className="timeline-list">{timeline.map((event) => <li key={event.id}><time>{formatDate(event.occurredAt, { month: "short", day: "numeric", year: "numeric" })}</time><span><strong>{event.label}</strong><small>{event.detail}</small></span></li>)}</ol> : <p className="empty-copy">No timeline events match this search.</p>}
      </article>
    </> : <article className="surface-card workspace-wide-card"><header className="card-heading"><div><p className="eyebrow">Operations-only chart</p><h3>Minimum-necessary access</h3></div></header><p className="empty-copy">This role can use the permitted operational tools without receiving clinical documentation, diagnoses, or outcome narratives.</p></article>}
    {workspace.operations?.appointments && <article className="surface-card workspace-wide-card"><header className="card-heading"><div><p className="eyebrow">Visits</p><h3>Scheduled appointments</h3></div></header>{workspace.operations.appointments.length ? <ul className="agenda-list">{workspace.operations.appointments.map((appointment) => <li key={appointment.id}><time><strong>{formatDate(appointment.date, { month: "short", day: "numeric" })}</strong><small>{formatTime(appointment.startsAt)}</small></time><span><strong>{appointment.kindLabel}</strong><small>{appointment.therapist.displayName} · {appointment.isHomeVisit ? "Home visit" : appointment.location || "Location pending"}</small></span><span className={`status-pill ${appointment.status}`}>{appointment.statusLabel}</span></li>)}</ul> : <p className="empty-copy">No scheduled visits are visible.</p>}</article>}
  </div>;
}

function DocumentationPanel({ workspace, patientId, refresh, report }: { workspace: PatientWorkspaceData; patientId: string; refresh: () => Promise<void>; report: (message: string) => void }) {
  const clinical = workspace.clinical!;
  return <div className="workspace-panel-grid">
    <DraftPanel artifacts={clinical.artifacts} patientId={patientId} canSign={workspace.permissions.canSignNotes} refresh={refresh} report={report} />
    <VoicePanel captures={clinical.voiceCaptures} patientId={patientId} refresh={refresh} report={report} />
    <DocumentsPanel patientId={patientId} report={report} />
  </div>;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function DocumentsPanel({ patientId, report }: { patientId: string; report: (message: string) => void }) {
  const [documents, setDocuments] = useState<PatientDocumentSummary[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const loadDocuments = useCallback(async () => {
    try {
      setDocuments((await api.patientDocuments(patientId)).documents);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load documents."));
    }
  }, [patientId]);

  useEffect(() => { void loadDocuments(); }, [loadDocuments]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError("Choose a file to upload.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.uploadPatientDocument(patientId, file, title || file.name, description);
      setTitle("");
      setDescription("");
      setFile(null);
      (event.target as HTMLFormElement).reset();
      await loadDocuments();
      report("Document uploaded to this patient's chart.");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to upload this document."));
    } finally {
      setBusy(false);
    }
  }

  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Chart attachments</p><h3>Documents</h3><p className="muted">Reference files such as outside imaging or referral paperwork. PDF, PNG, JPG, DOC, or DOCX up to 15 MB.</p></div></header>
    <form className="stack-form" onSubmit={upload}>
      <label>File<input type="file" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx" onChange={(event) => setFile(event.target.files?.[0] || null)} required /></label>
      <label>Title<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Outside imaging report" /></label>
      <label>Description<textarea rows={2} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
      {error && <p className="form-error" role="alert">{error}</p>}
      <button className="primary-button" type="submit" disabled={busy}>{busy ? "Uploading..." : "Upload document"}</button>
    </form>
    {documents.length ? (
      <ul className="record-list">
        {documents.map((document) => (
          <li key={document.id}>
            <span><strong>{document.title}</strong><small>{document.originalFilename} · {formatFileSize(document.sizeBytes)} · {document.uploadedBy} · {formatDate(document.uploadedAt)}</small></span>
            <a className="secondary-button" href={api.patientDocumentDownloadUrl(patientId, document.id)} target="_blank" rel="noreferrer">Download</a>
          </li>
        ))}
      </ul>
    ) : <p className="empty-copy">No documents uploaded to this chart yet.</p>}
  </article>;
}

function DraftPanel({ artifacts, patientId, canSign, refresh, report }: { artifacts: Artifact[]; patientId: string; canSign: boolean; refresh: () => Promise<void>; report: (message: string) => void }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  async function create(kind: string) {
    setBusy(kind); setError("");
    try { await api.createDraft(patientId, kind); await refresh(); report("A source-backed draft was created. It remains a therapist-reviewed draft, not final documentation."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to create a clinical draft.")); }
    finally { setBusy(""); }
  }
  async function review(id: string, action: "approve" | "reject" | "apply") {
    setBusy(`${id}-${action}`); setError("");
    try { await api.reviewDraft(id, action); await refresh(); report(action === "apply" ? "Draft applied to a new editable note. Review every section before finalizing." : action === "approve" ? "Draft approved with the therapist approval control." : "Draft rejected and retained in the audit trail."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to update the draft review.")); }
    finally { setBusy(""); }
  }
  return <article className="surface-card workspace-wide-card">
    <header className="card-heading"><div><p className="eyebrow">AI-assisted documentation</p><h3>Source-backed draft queue</h3><p className="muted">Only prior signed visits, active goals, and outcome trends are used. No generated content is a final note.</p></div></header>
    <div className="button-row">{[["progress", "Draft progress note"], ["discharge", "Draft discharge summary"], ["handoff", "Draft handoff"], ["patient_summary", "Draft patient visit summary"]].map(([kind, label]) => <button className="secondary-button" key={kind} disabled={Boolean(busy)} onClick={() => void create(kind)}>{busy === kind ? "Creating..." : label}</button>)}</div>
    {error && <p className="form-error" role="alert">{error}</p>}
    {artifacts.length ? <div className="artifact-list">{artifacts.map((artifact) => <article key={artifact.id} className="workflow-record"><header><span><strong>{artifact.kindLabel}</strong><small>{artifact.statusLabel} · {artifact.sourceNoteCount} signed source note{artifact.sourceNoteCount === 1 ? "" : "s"}</small></span><span className={`status-pill ${artifact.status}`}>{artifact.statusLabel}</span></header><p className="safety-copy">{artifact.safetyNotice}</p><details><summary>View draft and provenance</summary><pre>{artifact.draftText || "Draft content is available in the protected chart."}</pre><small>Provider: {artifact.provider} · {artifact.modelVersion}</small></details>{canSign && artifact.status === "draft" && <div className="button-row"><button className="secondary-button" disabled={Boolean(busy)} onClick={() => void review(artifact.id, "approve")}>{busy === `${artifact.id}-approve` ? "Approving..." : "Therapist approve"}</button><button className="text-action" disabled={Boolean(busy)} onClick={() => void review(artifact.id, "reject")}>Reject draft</button></div>}{canSign && artifact.status === "approved" && ["progress", "discharge", "handoff"].includes(artifact.kind) && <button className="secondary-button" disabled={Boolean(busy)} onClick={() => void review(artifact.id, "apply")}>{busy === `${artifact.id}-apply` ? "Applying..." : "Apply to editable note"}</button>}</article>)}</div> : <p className="empty-copy">No AI drafts are in this chart.</p>}
  </article>;
}

function VoicePanel({ captures, patientId, refresh, report }: { captures: NonNullable<PatientWorkspaceData["clinical"]>["voiceCaptures"]; patientId: string; refresh: () => Promise<void>; report: (message: string) => void }) {
  const [transcript, setTranscript] = useState("");
  const [durationSeconds, setDurationSeconds] = useState("0");
  const [consentConfirmed, setConsentConfirmed] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function saveTranscript(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("save"); setError("");
    try {
      await api.saveVoiceCapture(patientId, { transcript, durationSeconds: Number(durationSeconds), consentConfirmed });
      setTranscript(""); setDurationSeconds("0"); setConsentConfirmed(false);
      await refresh();
      report("Reviewed transcript saved. Raw audio was not stored.");
    } catch (requestError) { setError(requestMessage(requestError, "Unable to save the reviewed transcript.")); }
    finally { setBusy(""); }
  }
  async function createNote(captureId: string) {
    setBusy(captureId); setError("");
    try { await api.createNoteFromVoice(captureId); await refresh(); report("A draft daily note was created from the reviewed transcript. Complete the documentation before finalizing."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to create a note from this transcript.")); }
    finally { setBusy(""); }
  }
  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Mobile documentation</p><h3>Voice-to-note review</h3><p className="muted">Transcript-only workflow. Do not record or upload audio here until approved voice infrastructure is configured.</p></div></header>
    <p className="safety-copy">A signed voice-documentation consent is required before a reviewed transcript can be saved.</p>
    <form className="stack-form" onSubmit={saveTranscript}>
      <label>Reviewed transcript<textarea rows={6} value={transcript} onChange={(event) => setTranscript(event.target.value)} placeholder="Paste or enter the reviewed transcript. Verify it before saving." required /></label>
      <label>Duration in seconds<input type="number" min="0" max="14400" value={durationSeconds} onChange={(event) => setDurationSeconds(event.target.value)} required /></label>
      <label className="check-label"><input type="checkbox" checked={consentConfirmed} onChange={(event) => setConsentConfirmed(event.target.checked)} /> I confirmed the patient has applicable voice-documentation consent.</label>
      <button className="primary-button" type="submit" disabled={busy === "save"}>{busy === "save" ? "Saving..." : "Save reviewed transcript"}</button>
    </form>
    {error && <p className="form-error" role="alert">{error}</p>}
    {captures.length ? <ul className="record-list">{captures.map((capture) => <li key={capture.id}><span><strong>{capture.statusLabel}</strong><small>{formatDate(capture.createdAt)} · {capture.durationSeconds}s · {capture.therapist}</small></span>{capture.linkedNoteId ? <span className="status-pill active">Linked to draft note</span> : <button className="secondary-button" disabled={Boolean(busy)} onClick={() => void createNote(capture.id)}>{busy === capture.id ? "Creating..." : "Create draft note"}</button>}</li>)}</ul> : <p className="empty-copy">No reviewed voice transcripts are stored in this chart.</p>}
  </article>;
}

function CarePlanPanel({ workspace, patientId, refresh, report }: { workspace: PatientWorkspaceData; patientId: string; refresh: () => Promise<void>; report: (message: string) => void }) {
  const clinical = workspace.clinical!;
  return <div className="workspace-panel-grid">
    <GoalPanel goals={clinical.goals} patientId={patientId} canSign={workspace.permissions.canSignNotes} refresh={refresh} report={report} />
    <OutcomePanel outcomes={clinical.outcomes} patientId={patientId} refresh={refresh} report={report} />
    <HomeProgramPanel programs={clinical.homePrograms} patientId={patientId} canSign={workspace.permissions.canSignNotes} refresh={refresh} report={report} />
  </div>;
}

interface GoalDraft {
  functionalLimitation: string;
  functionalTask: string;
  baselineValue: string;
  targetValue: string;
  currentValue: string;
  unit: string;
  measurementMethod: string;
  targetDate: string;
  suggestedWording: string;
}

const blankGoalDraft = (): GoalDraft => ({ functionalLimitation: "", functionalTask: "", baselineValue: "", targetValue: "", currentValue: "", unit: "", measurementMethod: "", targetDate: dateInputValue(42), suggestedWording: "" });

function GoalPanel({ goals, patientId, canSign, refresh, report }: { goals: NonNullable<PatientWorkspaceData["clinical"]>["goals"]; patientId: string; canSign: boolean; refresh: () => Promise<void>; report: (message: string) => void }) {
  const [limitation, setLimitation] = useState("");
  const [measure, setMeasure] = useState("");
  const [suggestions, setSuggestions] = useState<GoalSuggestion[]>([]);
  const [draft, setDraft] = useState<GoalDraft>(blankGoalDraft);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  async function getSuggestions(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("suggest"); setError("");
    try { const payload = await api.goalSuggestions(patientId, limitation, measure); setSuggestions(payload.suggestions); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to generate goal suggestions.")); }
    finally { setBusy(""); }
  }
  function useSuggestion(suggestion: GoalSuggestion) {
    setDraft({ functionalLimitation: suggestion.functional_limitation, functionalTask: suggestion.functional_task, baselineValue: "", targetValue: "", currentValue: "", unit: "", measurementMethod: suggestion.measurement_method, targetDate: dateInputValue(suggestion.timeframe_weeks * 7), suggestedWording: suggestion.wording });
  }
  async function saveGoal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("save"); setError("");
    try { await api.createGoal(patientId, { ...draft }); setDraft(blankGoalDraft()); await refresh(); report("Measurable goal saved as a clinician-review draft."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to save the goal draft.")); }
    finally { setBusy(""); }
  }
  async function approve(goalId: string) {
    setBusy(goalId); setError("");
    try { await api.approveGoal(goalId); await refresh(); report("Goal activated by an authorized therapist."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to approve this goal.")); }
    finally { setBusy(""); }
  }
  return <article className="surface-card workspace-wide-card">
    <header className="card-heading"><div><p className="eyebrow">Functional goals</p><h3>Measurable goals tied to limitations</h3><p className="muted">Suggestions are editable templates. Set real baseline, target, unit, method, and deadline before approval.</p></div></header>
    <form className="inline-form" onSubmit={getSuggestions}><input value={limitation} onChange={(event) => setLimitation(event.target.value)} placeholder="State the functional limitation, e.g. cannot descend stairs safely" aria-label="Functional limitation" required /><select value={measure} onChange={(event) => setMeasure(event.target.value)} aria-label="Outcome measure"><option value="">Optional outcome measure</option>{outcomeMeasures.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><button className="secondary-button" type="submit" disabled={busy === "suggest"}>{busy === "suggest" ? "Generating..." : "Suggest goals"}</button></form>
    {suggestions.length > 0 && <div className="suggestion-grid">{suggestions.map((suggestion) => <article key={suggestion.wording}><strong>{suggestion.functional_task}</strong><small>Baseline: {suggestion.baseline_hint} · Target: {suggestion.target_hint}</small><p>{suggestion.wording}</p><button className="text-action" onClick={() => useSuggestion(suggestion)}>Use as editable draft</button></article>)}</div>}
    <details className="workspace-details"><summary>Create measurable goal draft</summary><form className="stack-form goal-form" onSubmit={saveGoal}>
      <label>Functional limitation<textarea rows={2} value={draft.functionalLimitation} onChange={(event) => setDraft({ ...draft, functionalLimitation: event.target.value })} required /></label>
      <label>Functional task<input value={draft.functionalTask} onChange={(event) => setDraft({ ...draft, functionalTask: event.target.value })} required /></label>
      <div className="field-grid"><label>Baseline value<input type="number" step="0.01" value={draft.baselineValue} onChange={(event) => setDraft({ ...draft, baselineValue: event.target.value })} required /></label><label>Target value<input type="number" step="0.01" value={draft.targetValue} onChange={(event) => setDraft({ ...draft, targetValue: event.target.value })} required /></label><label>Current value (optional)<input type="number" step="0.01" value={draft.currentValue} onChange={(event) => setDraft({ ...draft, currentValue: event.target.value })} /></label><label>Unit<input value={draft.unit} onChange={(event) => setDraft({ ...draft, unit: event.target.value })} placeholder="minutes, points, assistance level" required /></label></div>
      <div className="field-grid"><label>Measurement method<input value={draft.measurementMethod} onChange={(event) => setDraft({ ...draft, measurementMethod: event.target.value })} required /></label><label>Target date<input type="date" value={draft.targetDate} onChange={(event) => setDraft({ ...draft, targetDate: event.target.value })} required /></label></div>
      <label>Suggested wording<textarea rows={3} value={draft.suggestedWording} onChange={(event) => setDraft({ ...draft, suggestedWording: event.target.value })} required /></label>
      <button className="primary-button" type="submit" disabled={busy === "save"}>{busy === "save" ? "Saving..." : "Save goal draft"}</button>
    </form></details>
    {error && <p className="form-error" role="alert">{error}</p>}
    {goals.length ? <ul className="record-list">{goals.map((goal) => <li key={goal.id}><span><strong>{goal.functionalTask}</strong><small>{goal.functionalLimitation || "Functional limitation"} · {goal.currentValue ?? goal.baselineValue} to {goal.targetValue} {goal.unit} by {formatDate(goal.targetDate)}</small></span>{canSign && goal.status === "draft" ? <button className="secondary-button" disabled={Boolean(busy)} onClick={() => void approve(goal.id)}>{busy === goal.id ? "Approving..." : "Approve goal"}</button> : <span className={`status-pill ${goal.status}`}>{goal.statusLabel}</span>}</li>)}</ul> : <p className="empty-copy">No measurable goals are in this chart.</p>}
  </article>;
}

function OutcomePanel({ outcomes, patientId, refresh, report }: { outcomes: NonNullable<PatientWorkspaceData["clinical"]>["outcomes"]; patientId: string; refresh: () => Promise<void>; report: (message: string) => void }) {
  const [measure, setMeasure] = useState("lefs");
  const [measuredOn, setMeasuredOn] = useState(dateInputValue());
  const [score, setScore] = useState("");
  const [maximumScore, setMaximumScore] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try { await api.recordOutcome(patientId, { measure, measuredOn, score, maximumScore, notes }); setScore(""); setMaximumScore(""); setNotes(""); await refresh(); report("Outcome total saved and its deterministic trend was refreshed."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to record the outcome score.")); }
    finally { setBusy(false); }
  }
  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Outcome measures</p><h3>Score & trend tracking</h3><p className="muted">Enter reviewed total scores. Instrument question-level scoring is not calculated in the browser.</p></div></header>
    <form className="stack-form" onSubmit={save}><label>Measure<select value={measure} onChange={(event) => setMeasure(event.target.value)}>{outcomeMeasures.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><div className="field-grid"><label>Date measured<input type="date" value={measuredOn} onChange={(event) => setMeasuredOn(event.target.value)} required /></label><label>Score<input type="number" step="0.01" min="0" value={score} onChange={(event) => setScore(event.target.value)} required /></label><label>Maximum (optional)<input type="number" step="0.01" min="0" value={maximumScore} onChange={(event) => setMaximumScore(event.target.value)} /></label></div><label>Clinical note (optional)<textarea rows={2} value={notes} onChange={(event) => setNotes(event.target.value)} /></label><button className="primary-button" type="submit" disabled={busy}>{busy ? "Recording..." : "Record outcome score"}</button></form>
    {error && <p className="form-error" role="alert">{error}</p>}
    {outcomes.length ? <ul className="record-list">{outcomes.map((outcome) => <li key={outcome.measure}><span><strong>{outcome.label}: {outcome.latest}{outcome.maximum !== null ? ` / ${outcome.maximum}` : ""}</strong><small>{outcome.trend} · change {outcome.delta} {outcome.unit} · {outcome.points.length} recorded point{outcome.points.length === 1 ? "" : "s"}</small></span><span className={`status-pill ${outcome.trend.toLowerCase()}`}>{outcome.trend}</span></li>)}</ul> : <p className="empty-copy">No outcome scores recorded.</p>}
  </article>;
}

function HomeProgramPanel({ programs, patientId, canSign, refresh, report }: { programs: NonNullable<PatientWorkspaceData["clinical"]>["homePrograms"]; patientId: string; canSign: boolean; refresh: () => Promise<void>; report: (message: string) => void }) {
  const [suggestions, setSuggestions] = useState<HomeProgramSuggestion[]>([]);
  const [title, setTitle] = useState("");
  const [patientInstructions, setPatientInstructions] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  async function getSuggestions() {
    setBusy("suggest"); setError("");
    try { const payload = await api.homeProgramSuggestions(patientId); setSuggestions(payload.suggestions); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to load home-program suggestions.")); }
    finally { setBusy(""); }
  }
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("save"); setError("");
    try { await api.createHomeProgram(patientId, { title, patientInstructions }); setTitle(""); setPatientInstructions(""); await refresh(); report("Home program saved as a therapist-review draft."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to save the home program.")); }
    finally { setBusy(""); }
  }
  async function approve(id: string) {
    setBusy(id); setError("");
    try { await api.approveHomeProgram(id); await refresh(); report("Home program activated by an authorized therapist."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to activate the home program.")); }
    finally { setBusy(""); }
  }
  return <article className="surface-card workspace-wide-card">
    <header className="card-heading"><div><p className="eyebrow">Home program</p><h3>Patient instructions & conservative suggestions</h3><p className="muted">Suggestions are a review aid. They do not autonomously prescribe exercise dosage or progression.</p></div><button className="secondary-button" disabled={busy === "suggest"} onClick={() => void getSuggestions()}>{busy === "suggest" ? "Loading..." : "Review suggestions"}</button></header>
    {suggestions.map((suggestion, index) => <div className="suggestion-grid" key={index}>{suggestion.warnings.map((warning) => <p className="safety-copy" key={warning}>{warning}</p>)}{suggestion.exercises.map((exercise) => <article key={exercise.name}><strong>{exercise.name}</strong><small>{exercise.dosage}</small><p>{exercise.reason}</p></article>)}</div>)}
    <details className="workspace-details"><summary>Create home-program draft</summary><form className="stack-form" onSubmit={create}><label>Title<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Home program - week 1" required /></label><label>Patient-friendly instructions<textarea rows={5} value={patientInstructions} onChange={(event) => setPatientInstructions(event.target.value)} placeholder="Write clear, reviewed instructions and precautions." required /></label><button className="primary-button" type="submit" disabled={busy === "save"}>{busy === "save" ? "Saving..." : "Save program draft"}</button></form></details>
    {error && <p className="form-error" role="alert">{error}</p>}
    {programs.length ? <div className="artifact-list">{programs.map((program) => <article className="workflow-record" key={program.id}><header><span><strong>{program.title}</strong><small>{program.prescribedBy} · {formatDate(program.createdAt)}</small></span><span className={`status-pill ${program.status}`}>{program.statusLabel}</span></header><p>{program.patientInstructions}</p>{program.precautions && <p className="safety-copy">Precautions: {program.precautions}</p>}{canSign && program.status === "draft" && <button className="secondary-button" disabled={Boolean(busy)} onClick={() => void approve(program.id)}>{busy === program.id ? "Activating..." : "Therapist activate"}</button>}</article>)}</div> : <p className="empty-copy">No home programs are in this chart.</p>}
  </article>;
}

function OperationsPanel({ workspace, patientId, refresh, report }: { workspace: PatientWorkspaceData; patientId: string; refresh: () => Promise<void>; report: (message: string) => void }) {
  const operations = workspace.operations!;
  return <div className="workspace-panel-grid">
    {operations.canManageSchedule && <ScheduleCreatePanel patientId={patientId} staff={operations.schedulingStaff || []} appointments={operations.appointments || []} refresh={refresh} report={report} />}
    {operations.canManageSchedule && <IntakeConsentPanel patientId={patientId} consents={operations.consents} intakes={operations.intakes} refresh={refresh} report={report} />}
    {operations.canManageSchedule && <ReferralsPanel patientId={patientId} referrals={operations.referrals || []} refresh={refresh} report={report} />}
    <MessagePanel patientId={patientId} recipients={operations.recipients} messages={operations.messages} refresh={refresh} report={report} />
    {(operations.canManageBilling || operations.canCollectPayments) && <BillingPanel patientId={patientId} canManageBilling={operations.canManageBilling} superbills={operations.superbills || []} payments={operations.payments || []} refresh={refresh} report={report} />}
  </div>;
}

function ScheduleCreatePanel({ patientId, staff, appointments, refresh, report }: { patientId: string; staff: NonNullable<NonNullable<PatientWorkspaceData["operations"]>["schedulingStaff"]>; appointments: NonNullable<NonNullable<PatientWorkspaceData["operations"]>["appointments"]>; refresh: () => Promise<void>; report: (message: string) => void }) {
  const defaultStart = useMemo(() => `${dateInputValue()}T09:00`, []);
  const defaultEnd = useMemo(() => `${dateInputValue()}T10:00`, []);
  const [therapistId, setTherapistId] = useState("");
  const [startsAt, setStartsAt] = useState(defaultStart);
  const [endsAt, setEndsAt] = useState(defaultEnd);
  const [kind, setKind] = useState("follow_up");
  const [location, setLocation] = useState("");
  const [isHomeVisit, setIsHomeVisit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (!therapistId && staff.length) setTherapistId(staff[0].id); }, [staff, therapistId]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await api.createAppointment(patientId, { therapistId, startsAt: new Date(startsAt).toISOString(), endsAt: new Date(endsAt).toISOString(), kind, location, isHomeVisit });
      await refresh(); report("Appointment scheduled with a server-side clinician-overlap check.");
    } catch (requestError) { setError(requestMessage(requestError, "Unable to schedule the appointment.")); }
    finally { setBusy(false); }
  }
  return <article className="surface-card workspace-wide-card">
    <header className="card-heading"><div><p className="eyebrow">Scheduling</p><h3>Schedule a patient visit</h3><p className="muted">Existing calendar moves remain locked when a visit is documented, non-scheduled, or conflicts with the clinician calendar.</p></div></header>
    <details className="workspace-details"><summary>Create appointment</summary><form className="stack-form" onSubmit={create}><label>Clinician<select value={therapistId} onChange={(event) => setTherapistId(event.target.value)} required><option value="" disabled>Select clinician</option>{staff.map((user) => <option value={user.id} key={user.id}>{user.displayName} · {user.roleLabel}</option>)}</select></label><div className="field-grid"><label>Start<input type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} required /></label><label>End<input type="datetime-local" value={endsAt} onChange={(event) => setEndsAt(event.target.value)} required /></label><label>Visit type<select value={kind} onChange={(event) => setKind(event.target.value)}><option value="evaluation">Initial evaluation</option><option value="follow_up">Follow-up visit</option><option value="progress">Progress visit</option><option value="discharge">Discharge visit</option><option value="telehealth">Telehealth</option></select></label><label>Location<input value={location} onChange={(event) => setLocation(event.target.value)} placeholder="Clinic, home, or telehealth" /></label></div><label className="check-label"><input type="checkbox" checked={isHomeVisit} onChange={(event) => setIsHomeVisit(event.target.checked)} /> Home visit</label><button className="primary-button" type="submit" disabled={busy}>{busy ? "Scheduling..." : "Schedule visit"}</button></form></details>
    {error && <p className="form-error" role="alert">{error}</p>}
    {appointments.length ? <ul className="record-list">{appointments.slice(0, 8).map((appointment) => <li key={appointment.id}><span><strong>{formatDate(appointment.date)} · {formatTime(appointment.startsAt)}</strong><small>{appointment.kindLabel} · {appointment.therapist.displayName} · {appointment.isHomeVisit ? "Home visit" : appointment.location || "Location pending"}</small></span><span className={`status-pill ${appointment.status}`}>{appointment.statusLabel}</span></li>)}</ul> : <p className="empty-copy">No visits are scheduled for this patient.</p>}
  </article>;
}

function IntakeConsentPanel({ patientId, consents, intakes, refresh, report }: { patientId: string; consents: NonNullable<PatientWorkspaceData["operations"]>["consents"]; intakes: NonNullable<PatientWorkspaceData["operations"]>["intakes"]; refresh: () => Promise<void>; report: (message: string) => void }) {
  const [intake, setIntake] = useState({ chiefComplaint: "", functionalGoals: "", relevantHistory: "" });
  const [consent, setConsent] = useState({ kind: "treatment", documentVersion: "v1", signatureName: "" });
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  async function saveIntake(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("intake"); setError("");
    try { await api.createIntake(patientId, intake); setIntake({ chiefComplaint: "", functionalGoals: "", relevantHistory: "" }); await refresh(); report("Intake submission saved for clinical review."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to save intake.")); }
    finally { setBusy(""); }
  }
  async function saveConsent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("consent"); setError("");
    try { await api.createConsent(patientId, consent); setConsent({ ...consent, signatureName: "" }); await refresh(); report("Versioned consent record saved."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to save consent.")); }
    finally { setBusy(""); }
  }
  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Intake & consent</p><h3>Administrative intake</h3><p className="muted">These operational records are role-scoped. Capture only through your approved clinic process.</p></div></header>
    <details className="workspace-details"><summary>Record intake submission</summary><form className="stack-form" onSubmit={saveIntake}><label>Chief complaint<textarea rows={3} value={intake.chiefComplaint} onChange={(event) => setIntake({ ...intake, chiefComplaint: event.target.value })} required /></label><label>Functional goals<textarea rows={3} value={intake.functionalGoals} onChange={(event) => setIntake({ ...intake, functionalGoals: event.target.value })} required /></label><label>Relevant history (optional)<textarea rows={3} value={intake.relevantHistory} onChange={(event) => setIntake({ ...intake, relevantHistory: event.target.value })} /></label><button className="primary-button" type="submit" disabled={busy === "intake"}>{busy === "intake" ? "Saving..." : "Save intake"}</button></form></details>
    <details className="workspace-details"><summary>Record signed consent</summary><form className="stack-form" onSubmit={saveConsent}><label>Consent type<select value={consent.kind} onChange={(event) => setConsent({ ...consent, kind: event.target.value })}><option value="treatment">Consent to treatment</option><option value="telehealth">Telehealth consent</option><option value="financial">Financial policy</option><option value="voice">Voice documentation consent</option><option value="privacy">Privacy notice acknowledgement</option></select></label><div className="field-grid"><label>Document version<input value={consent.documentVersion} onChange={(event) => setConsent({ ...consent, documentVersion: event.target.value })} required /></label><label>Signature name (if obtained)<input value={consent.signatureName} onChange={(event) => setConsent({ ...consent, signatureName: event.target.value })} /></label></div><button className="primary-button" type="submit" disabled={busy === "consent"}>{busy === "consent" ? "Saving..." : "Save consent"}</button></form></details>
    {error && <p className="form-error" role="alert">{error}</p>}
    <div className="summary-split"><div><strong>Recent intake records</strong>{intakes.length ? <ul className="summary-list">{intakes.map((item) => <li key={item.id}><strong>{item.formVersion}</strong><small>{item.statusLabel} · {item.submittedAt ? formatDate(item.submittedAt) : "Not submitted"}</small></li>)}</ul> : <p className="empty-copy">No intake records.</p>}</div><div><strong>Consent records</strong>{consents.length ? <ul className="summary-list">{consents.map((item) => <li key={item.id}><strong>{item.kindLabel}</strong><small>{item.documentVersion} · {item.statusLabel} · {item.signedAt ? formatDate(item.signedAt) : "Pending"}</small></li>)}</ul> : <p className="empty-copy">No consents recorded.</p>}</div></div>
  </article>;
}

function ReferralsPanel({ patientId, referrals, refresh, report }: { patientId: string; referrals: Referral[]; refresh: () => Promise<void>; report: (message: string) => void }) {
  const [form, setForm] = useState({ direction: "incoming", providerName: "", providerContact: "", reason: "" });
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("create"); setError("");
    try {
      await api.createReferral(patientId, form);
      setForm({ direction: "incoming", providerName: "", providerContact: "", reason: "" });
      await refresh();
      report("Referral recorded.");
    } catch (requestError) { setError(requestMessage(requestError, "Unable to save this referral.")); }
    finally { setBusy(""); }
  }

  async function updateStatus(referralId: string, status: string) {
    setBusy(referralId); setError("");
    try { await api.updateReferralStatus(referralId, status); await refresh(); report("Referral status updated."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to update this referral.")); }
    finally { setBusy(""); }
  }

  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Front desk</p><h3>Referrals</h3><p className="muted">Track referrals to and from outside providers for this patient.</p></div></header>
    <details className="workspace-details"><summary>Record referral</summary><form className="stack-form" onSubmit={create}>
      <label>Direction<select value={form.direction} onChange={(event) => setForm({ ...form, direction: event.target.value })}><option value="incoming">Incoming — from a referring provider</option><option value="outgoing">Outgoing — to a specialist or provider</option></select></label>
      <div className="field-grid">
        <label>Provider name<input value={form.providerName} onChange={(event) => setForm({ ...form, providerName: event.target.value })} required /></label>
        <label>Provider contact<input value={form.providerContact} onChange={(event) => setForm({ ...form, providerContact: event.target.value })} /></label>
      </div>
      <label>Reason<textarea rows={2} value={form.reason} onChange={(event) => setForm({ ...form, reason: event.target.value })} /></label>
      <button className="primary-button" type="submit" disabled={busy === "create"}>{busy === "create" ? "Saving..." : "Save referral"}</button>
    </form></details>
    {error && <p className="form-error" role="alert">{error}</p>}
    {referrals.length ? (
      <ul className="record-list">
        {referrals.map((referral) => (
          <li key={referral.id}>
            <span><strong>{referral.providerName}</strong><small>{referral.directionLabel} · {referral.reason || "No reason recorded"} · {formatDate(referral.createdAt)}</small></span>
            <span className="button-row">
              <span className={`status-pill ${referral.status}`}>{referral.statusLabel}</span>
              {referral.status === "pending" && <button className="text-action" disabled={Boolean(busy)} onClick={() => void updateStatus(referral.id, "scheduled")}>Mark scheduled</button>}
              {(referral.status === "pending" || referral.status === "scheduled") && <button className="text-action" disabled={Boolean(busy)} onClick={() => void updateStatus(referral.id, "completed")}>Mark completed</button>}
            </span>
          </li>
        ))}
      </ul>
    ) : <p className="empty-copy">No referrals recorded for this patient.</p>}
  </article>;
}

function MessagePanel({ patientId, recipients, messages, refresh, report }: { patientId: string; recipients: NonNullable<PatientWorkspaceData["operations"]>["recipients"]; messages: NonNullable<PatientWorkspaceData["operations"]>["messages"]; refresh: () => Promise<void>; report: (message: string) => void }) {
  const [recipientId, setRecipientId] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (!recipientId && recipients.length) setRecipientId(recipients[0].id); }, [recipientId, recipients]);
  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try { await api.sendSecureMessage(patientId, { recipientId, subject, body }); setSubject(""); setBody(""); await refresh(); report("Secure internal message sent. External notification content remains outside this workflow."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to send secure message.")); }
    finally { setBusy(false); }
  }
  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Secure messaging</p><h3>Internal patient thread</h3><p className="muted">Only messages involving your account are returned in this workspace.</p></div></header>
    <details className="workspace-details"><summary>Compose secure message</summary><form className="stack-form" onSubmit={send}><label>Recipient<select value={recipientId} onChange={(event) => setRecipientId(event.target.value)} required><option value="" disabled>Select recipient</option>{recipients.map((recipient) => <option key={recipient.id} value={recipient.id}>{recipient.displayName} · {recipient.roleLabel}</option>)}</select></label><label>Subject<input value={subject} onChange={(event) => setSubject(event.target.value)} required /></label><label>Message<textarea rows={4} value={body} onChange={(event) => setBody(event.target.value)} required /></label><button className="primary-button" type="submit" disabled={busy}>{busy ? "Sending..." : "Send secure message"}</button></form></details>
    {error && <p className="form-error" role="alert">{error}</p>}
    {messages.length ? <ul className="message-list">{messages.map((message) => <li key={message.id} className={message.direction}><strong>{message.subject}</strong><small>{message.direction === "outbound" ? `To ${message.recipient}` : `From ${message.sender}`} · {formatDate(message.createdAt)}</small><p>{message.body}</p></li>)}</ul> : <p className="empty-copy">No messages involving your account.</p>}
  </article>;
}

function BillingPanel({ patientId, canManageBilling, superbills, payments, refresh, report }: { patientId: string; canManageBilling: boolean; superbills: NonNullable<NonNullable<PatientWorkspaceData["operations"]>["superbills"]>; payments: NonNullable<NonNullable<PatientWorkspaceData["operations"]>["payments"]>; refresh: () => Promise<void>; report: (message: string) => void }) {
  const [superbill, setSuperbill] = useState({ serviceDate: dateInputValue(), codes: "", amount: "", status: "draft", paymentProcessorReference: "" });
  const [payment, setPayment] = useState({ superbillId: "", amount: "", receivedOn: dateInputValue(), status: "pending", paymentProcessorReference: "" });
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  async function saveSuperbill(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("superbill"); setError("");
    try { await api.createSuperbill(patientId, { ...superbill, codes: superbill.codes.split(",").map((code) => code.trim()).filter(Boolean) }); setSuperbill({ ...superbill, codes: "", amount: "", paymentProcessorReference: "" }); await refresh(); report("Superbill saved. Verify payer-specific coding before submission."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to save superbill.")); }
    finally { setBusy(""); }
  }
  async function savePayment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("payment"); setError("");
    try { await api.createPayment(patientId, payment); setPayment({ ...payment, amount: "", paymentProcessorReference: "" }); await refresh(); report("Payment reference status saved. No cardholder data is stored in this workspace."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to save payment status.")); }
    finally { setBusy(""); }
  }
  return <article className="surface-card workspace-wide-card">
    <header className="card-heading"><div><p className="eyebrow">Billing</p><h3>{canManageBilling ? "Superbills & payment references" : "Payment references"}</h3><p className="muted">Use only an approved processor reference; never enter cardholder data.</p></div></header>
    <div className="summary-split">
      {canManageBilling && <details className="workspace-details"><summary>Create superbill</summary><form className="stack-form" onSubmit={saveSuperbill}><div className="field-grid"><label>Service date<input type="date" value={superbill.serviceDate} onChange={(event) => setSuperbill({ ...superbill, serviceDate: event.target.value })} required /></label><label>Amount<input type="number" step="0.01" min="0" value={superbill.amount} onChange={(event) => setSuperbill({ ...superbill, amount: event.target.value })} required /></label></div><label>CPT / service codes<input value={superbill.codes} onChange={(event) => setSuperbill({ ...superbill, codes: event.target.value })} placeholder="97110, 97140" required /></label><label>Status<select value={superbill.status} onChange={(event) => setSuperbill({ ...superbill, status: event.target.value })}><option value="draft">Draft</option><option value="ready">Ready for billing</option><option value="submitted">Submitted</option><option value="paid">Paid</option></select></label><label>Approved processor reference (optional)<input value={superbill.paymentProcessorReference} onChange={(event) => setSuperbill({ ...superbill, paymentProcessorReference: event.target.value })} /></label><button className="primary-button" type="submit" disabled={busy === "superbill"}>{busy === "superbill" ? "Saving..." : "Save superbill"}</button></form></details>}
      <details className="workspace-details"><summary>Record payment status</summary><form className="stack-form" onSubmit={savePayment}><label>Related superbill (optional)<select value={payment.superbillId} onChange={(event) => setPayment({ ...payment, superbillId: event.target.value })}><option value="">Not linked</option>{superbills.map((item) => <option key={item.id} value={item.id}>{formatDate(item.serviceDate)} · ${item.amount.toFixed(2)}</option>)}</select></label><div className="field-grid"><label>Amount<input type="number" step="0.01" min="0" value={payment.amount} onChange={(event) => setPayment({ ...payment, amount: event.target.value })} required /></label><label>Received on<input type="date" value={payment.receivedOn} onChange={(event) => setPayment({ ...payment, receivedOn: event.target.value })} required /></label></div><label>Status<select value={payment.status} onChange={(event) => setPayment({ ...payment, status: event.target.value })}><option value="pending">Pending</option><option value="received">Received</option><option value="refunded">Refunded</option><option value="void">Void</option></select></label><label>Approved processor reference<input value={payment.paymentProcessorReference} onChange={(event) => setPayment({ ...payment, paymentProcessorReference: event.target.value })} required /></label><button className="primary-button" type="submit" disabled={busy === "payment"}>{busy === "payment" ? "Saving..." : "Record payment"}</button></form></details>
    </div>
    {error && <p className="form-error" role="alert">{error}</p>}
    <div className="summary-split">
      {canManageBilling && <div><strong>Superbills</strong>{superbills.length ? <ul className="summary-list">{superbills.map((item) => <li key={item.id}><strong>{formatDate(item.serviceDate)} · ${item.amount.toFixed(2)}</strong><small>{item.codes.join(", ")} · {item.statusLabel}</small></li>)}</ul> : <p className="empty-copy">No superbills.</p>}</div>}
      <div><strong>Payment records</strong>{payments.length ? <ul className="summary-list">{payments.map((item) => <li key={item.id}><strong>{formatDate(item.receivedOn)} · ${item.amount.toFixed(2)}</strong><small>{item.statusLabel} · recorded by {item.recordedBy}</small></li>)}</ul> : <p className="empty-copy">No payment records.</p>}</div>
    </div>
  </article>;
}

function SafetyPanel({ workspace }: { workspace: PatientWorkspaceData }) {
  const events = workspace.safety!.recentAuditEvents;
  return <div className="workspace-panel-grid">
    <article className="surface-card workspace-wide-card">
      <header className="card-heading"><div><p className="eyebrow">Safety controls</p><h3>Therapist approval, access boundaries & audit history</h3><p className="muted">This is a HIPAA-oriented application foundation, not a certification of HIPAA compliance.</p></div></header>
      <div className="safety-grid"><article><strong>Therapist approval</strong><small>Drafts, goals, and home programs require authorized clinician review before activation or application.</small></article><article><strong>Signed-note protection</strong><small>Server-side attestation and compliance blockers protect finalization; signed notes stay locked and use addenda.</small></article><article><strong>Role-based access</strong><small>Each API request is scoped to the signed-in organization, role, and patient boundary.</small></article><article><strong>Deployment readiness</strong><small>Production still requires HIPAA-eligible hosting, BAAs, encryption, backups, MFA/SSO enforcement, retention controls, and disaster-recovery testing.</small></article></div>
    </article>
    <article className="surface-card workspace-wide-card">
      <header className="card-heading"><div><p className="eyebrow">Audit history</p><h3>Recent patient events</h3><p className="muted">Audit metadata is designed to exclude clinical narrative.</p></div></header>
      {events.length ? <ul className="timeline-list">{events.map((event) => <li key={event.id}><time>{formatDate(event.createdAt)}</time><span><strong>{event.action.replaceAll("_", " ").replaceAll(".", " · ")}</strong><small>{event.actor} · {event.objectType}</small></span></li>)}</ul> : <p className="empty-copy">No audit events are available for this patient.</p>}
    </article>
  </div>;
}
