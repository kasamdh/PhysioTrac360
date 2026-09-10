import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, api } from "../api/client";
import type {
  Artifact,
  ArtifactSection,
  CashPackage,
  Charge,
  Claim,
  ClaimTransaction,
  ClaimValidationFinding,
  ClinicLocation,
  Cms1500Data,
  DiagnosisCode,
  FormSubmissionDetail,
  FormSubmissionSummary,
  GoalSuggestion,
  HomeExercise,
  HomeProgramSuggestion,
  PatientDocumentSummary,
  PatientInsurancePolicy,
  PatientStatement,
  PatientStatementData,
  PatientSuperbillData,
  PatientWorkspace as PatientWorkspaceData,
  Payer,
  PortalOutcomeAssignment,
  Referral,
  StaffOption,
  TimelineEvent,
  WorkspaceUser,
} from "../api/types";
import { LicenseBadge } from "@/components/ui/license-banner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter } from "@/components/ui/dialog";
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
  const [showPortalInvite, setShowPortalInvite] = useState(false);

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
          {workspace.permissions.canManagePortalAccess && (
            <button className="secondary-button" onClick={() => setShowPortalInvite(true)}>
              {patient.portalStatus === "active" ? "Portal active" : patient.portalStatus === "invited" ? "Resend portal invite" : "Invite to portal"}
            </button>
          )}
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
      {showPortalInvite && (
        <PortalInviteDialog
          patientId={patientId}
          defaultEmail={patient.email || ""}
          alreadyInvited={patient.portalStatus === "invited" || patient.portalStatus === "active"}
          onClose={() => setShowPortalInvite(false)}
          onInvited={async (message) => { setShowPortalInvite(false); report(message); await loadWorkspace(); }}
        />
      )}
    </section>
  );
}

function PortalInviteDialog({ patientId, defaultEmail, alreadyInvited, onClose, onInvited }: { patientId: string; defaultEmail: string; alreadyInvited: boolean; onClose: () => void; onInvited: (message: string) => Promise<void> }) {
  const [email, setEmail] = useState(defaultEmail);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [invitationUrl, setInvitationUrl] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSaving(true);
    try {
      const result = await api.invitePatientToPortal(patientId, email);
      setInvitationUrl(result.invitationUrl);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to send the portal invitation."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      titleId="portal-invite-title"
      eyebrow="Patient portal"
      title={alreadyInvited ? "Resend portal invitation" : "Invite patient to the portal"}
      onClose={onClose}
      busy={saving}
      maxWidth="max-w-md"
    >
      {invitationUrl ? (
        <>
          <p className="m-0 text-[0.9375rem] leading-relaxed text-foreground">
            Send this activation link to the patient (email delivery may not be configured in this environment):
          </p>
          <p className="mt-3 break-all rounded-md border border-border bg-muted px-4 py-3 text-sm">{invitationUrl}</p>
          <DialogFooter>
            <Button type="button" onClick={() => void onInvited("Portal invitation created.")}>Done</Button>
          </DialogFooter>
        </>
      ) : (
        <form onSubmit={submit}>
          <label className="block text-[0.9375rem] font-semibold text-foreground">
            Patient email
            <input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="mt-1.5 block w-full rounded-md border border-border px-3 py-2.5 text-base font-normal"
            />
          </label>
          {error && (
            <p role="alert" className="mt-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="secondary" disabled={saving} onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={saving}>{saving ? "Sending..." : alreadyInvited ? "Resend invitation" : "Send invitation"}</Button>
          </DialogFooter>
        </form>
      )}
    </Dialog>
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
    <ClinicalNotesPanel notes={clinical.notes} patientId={patientId} />
    <DraftPanel artifacts={clinical.artifacts} patientId={patientId} canSign={workspace.permissions.canSignNotes} refresh={refresh} report={report} />
    <VoicePanel captures={clinical.voiceCaptures} patientId={patientId} refresh={refresh} report={report} />
    <DocumentsPanel patientId={patientId} report={report} />
  </div>;
}

function ClinicalNotesPanel({ notes, patientId }: { notes: NonNullable<PatientWorkspaceData["clinical"]>["notes"]; patientId: string }) {
  return <article className="surface-card">
    <header className="card-heading">
      <div><p className="eyebrow">Documentation</p><h3>Clinical notes</h3></div>
      <a className="secondary-button" href="#documentation">Open Documentation</a>
    </header>
    {notes.length ? <ul className="agenda-list">
      {notes.map((note) => (
        <li key={note.id}>
          <time><strong>{formatDate(note.serviceDate, { month: "short", day: "numeric" })}</strong></time>
          <span><strong>{note.noteTypeLabel}</strong><small>{note.therapistName}</small></span>
          <a className="status-pill" href={`#documentation/${patientId}/${note.id}`}>{note.statusLabel}</a>
        </li>
      ))}
    </ul> : <p className="empty-copy">No clinical notes have been started for this patient yet.</p>}
  </article>;
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
  const [visibleToPatient, setVisibleToPatient] = useState(false);
  const [busy, setBusy] = useState<string>("");
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
    setBusy("upload");
    setError("");
    try {
      await api.uploadPatientDocument(patientId, file, title || file.name, description, visibleToPatient);
      setTitle("");
      setDescription("");
      setFile(null);
      setVisibleToPatient(false);
      (event.target as HTMLFormElement).reset();
      await loadDocuments();
      report("Document uploaded to this patient's chart.");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to upload this document."));
    } finally {
      setBusy("");
    }
  }

  async function toggleVisibility(document: PatientDocumentSummary) {
    setBusy(document.id);
    setError("");
    try {
      await api.updatePatientDocumentVisibility(patientId, document.id, !document.visibleToPatient);
      await loadDocuments();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to update this document's visibility."));
    } finally {
      setBusy("");
    }
  }

  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Chart attachments</p><h3>Documents</h3><p className="muted">Reference files such as outside imaging or referral paperwork. PDF, PNG, JPG, DOC, or DOCX up to 15 MB.</p></div></header>
    <form className="stack-form" onSubmit={upload}>
      <label>File<input type="file" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx" onChange={(event) => setFile(event.target.files?.[0] || null)} required /></label>
      <label>Title<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Outside imaging report" /></label>
      <label>Description<textarea rows={2} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
      <label style={{ display: "flex", alignItems: "center", gap: ".5rem" }}><input type="checkbox" checked={visibleToPatient} onChange={(event) => setVisibleToPatient(event.target.checked)} style={{ width: "auto" }} /> Share with patient portal</label>
      {error && <p className="form-error" role="alert">{error}</p>}
      <button className="primary-button" type="submit" disabled={busy === "upload"}>{busy === "upload" ? "Uploading..." : "Upload document"}</button>
    </form>
    {documents.length ? (
      <ul className="record-list">
        {documents.map((document) => (
          <li key={document.id}>
            <span>
              <strong>{document.title}</strong>
              <small>
                {document.originalFilename} · {formatFileSize(document.sizeBytes)} · {document.uploadedBy} · {formatDate(document.uploadedAt)}
                {document.uploadedByPatient ? " · Uploaded by patient" : ""}
              </small>
            </span>
            <span className="button-row">
              <span className={`status-pill ${document.visibleToPatient ? "active" : "inactive"}`}>{document.visibleToPatient ? "Shared" : "Internal only"}</span>
              <button className="text-action" disabled={busy === document.id} onClick={() => void toggleVisibility(document)}>
                {document.visibleToPatient ? "Hide from patient" : "Share with patient"}
              </button>
              <a className="secondary-button" href={api.patientDocumentDownloadUrl(patientId, document.id)} target="_blank" rel="noreferrer">Download</a>
            </span>
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
  async function reviewSection(artifactId: string, sectionKey: string, status: "accepted" | "edited" | "rejected", reviewedText?: string) {
    setBusy(`${artifactId}-${sectionKey}`); setError("");
    try { await api.reviewDraftSection(artifactId, sectionKey, status, reviewedText); await refresh(); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to update this section.")); }
    finally { setBusy(""); }
  }
  return <article className="surface-card workspace-wide-card">
    <header className="card-heading"><div><p className="eyebrow">AI-assisted documentation</p><h3>Source-backed draft queue</h3><p className="muted">Only prior signed visits, active goals, and outcome trends are used. No generated content is a final note.</p></div></header>
    <div className="button-row">{[["progress", "Draft progress note"], ["discharge", "Draft discharge summary"], ["handoff", "Draft handoff"], ["patient_summary", "Draft patient visit summary"]].map(([kind, label]) => <button className="secondary-button" key={kind} disabled={Boolean(busy)} onClick={() => void create(kind)}>{busy === kind ? "Creating..." : label}</button>)}</div>
    {error && <p className="form-error" role="alert">{error}</p>}
    {artifacts.length ? <div className="artifact-list">{artifacts.map((artifact) => {
      const hasSections = artifact.sections.length > 0;
      const sectionsPending = hasSections && artifact.sections.some((section) => section.status === "pending");
      return (
        <article key={artifact.id} className="workflow-record">
          <header><span><strong>{artifact.kindLabel}</strong><small>{artifact.statusLabel} · {artifact.sourceNoteCount} signed source note{artifact.sourceNoteCount === 1 ? "" : "s"}</small></span><span className={`status-pill ${artifact.status}`}>{artifact.statusLabel}</span></header>
          <p className="safety-copy">{artifact.safetyNotice}</p>
          {hasSections ? (
            <ArtifactSectionList artifact={artifact} busy={busy} onReview={reviewSection} />
          ) : (
            <details><summary>View draft and provenance</summary><pre>{artifact.draftText || "Draft content is available in the protected chart."}</pre><small>Provider: {artifact.provider} · {artifact.modelVersion}</small></details>
          )}
          {canSign && artifact.status === "draft" && <div className="button-row"><button className="secondary-button" disabled={Boolean(busy)} onClick={() => void review(artifact.id, "approve")}>{busy === `${artifact.id}-approve` ? "Approving..." : "Therapist approve"}</button><button className="text-action" disabled={Boolean(busy)} onClick={() => void review(artifact.id, "reject")}>Reject draft</button></div>}
          {canSign && artifact.status === "approved" && ["progress", "discharge", "handoff"].includes(artifact.kind) && (
            <>
              <button className="secondary-button" disabled={Boolean(busy) || sectionsPending} onClick={() => void review(artifact.id, "apply")}>{busy === `${artifact.id}-apply` ? "Applying..." : "Apply to editable note"}</button>
              {sectionsPending && <small className="muted">Accept, edit, or reject every section before applying.</small>}
            </>
          )}
        </article>
      );
    })}</div> : <p className="empty-copy">No AI drafts are in this chart.</p>}
  </article>;
}

function ArtifactSectionList({ artifact, busy, onReview }: { artifact: Artifact; busy: string; onReview: (artifactId: string, sectionKey: string, status: "accepted" | "edited" | "rejected", reviewedText?: string) => Promise<void> }) {
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [draftValue, setDraftValue] = useState("");

  function startEditing(section: ArtifactSection) {
    setEditingKey(section.key);
    setDraftValue(section.reviewedText || section.draftText);
  }

  return (
    <div className="record-list">
      {artifact.sections.map((section) => {
        const rowBusy = busy === `${artifact.id}-${section.key}`;
        const isEditing = editingKey === section.key;
        return (
          <div key={section.key} className="workflow-record" style={{ marginTop: ".6rem" }}>
            <header><span><strong>{section.label}</strong></span><span className={`status-pill ${section.status}`}>{section.status}</span></header>
            {isEditing ? (
              <div className="stack-form">
                <label>
                  Edited text
                  <textarea value={draftValue} onChange={(event) => setDraftValue(event.target.value)} rows={4} />
                </label>
                <div className="button-row">
                  <button
                    className="secondary-button"
                    disabled={rowBusy || !draftValue.trim()}
                    onClick={() => { void onReview(artifact.id, section.key, "edited", draftValue).then(() => setEditingKey(null)); }}
                  >
                    {rowBusy ? "Saving..." : "Save edit"}
                  </button>
                  <button className="text-action" disabled={rowBusy} onClick={() => setEditingKey(null)}>Cancel</button>
                </div>
              </div>
            ) : (
              <>
                <pre>{section.reviewedText || section.draftText}</pre>
                <div className="button-row">
                  <button className="secondary-button" disabled={rowBusy} onClick={() => void onReview(artifact.id, section.key, "accepted")}>{rowBusy ? "Saving..." : "Accept"}</button>
                  <button className="text-action" disabled={rowBusy} onClick={() => startEditing(section)}>Edit</button>
                  <button className="text-action" disabled={rowBusy} onClick={() => void onReview(artifact.id, section.key, "rejected")}>Reject</button>
                </div>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
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
    <EpisodeOfCarePanel episodes={clinical.episodesOfCare} patientId={patientId} refresh={refresh} report={report} />
    <GoalPanel goals={clinical.goals} patientId={patientId} canSign={workspace.permissions.canSignNotes} refresh={refresh} report={report} />
    <OutcomePanel outcomes={clinical.outcomes} assignments={clinical.outcomeAssignments || []} hasPortalAccount={workspace.patient.portalStatus === "active"} patientId={patientId} refresh={refresh} report={report} />
    <HomeProgramPanel programs={clinical.homePrograms} patientId={patientId} canSign={workspace.permissions.canSignNotes} refresh={refresh} report={report} />
  </div>;
}

interface EpisodeDraft {
  diagnosis: string;
  status: string;
  startDate: string;
  notes: string;
}

const blankEpisodeDraft = (): EpisodeDraft => ({ diagnosis: "", status: "active", startDate: dateInputValue(), notes: "" });

function EpisodeOfCarePanel({ episodes, patientId, refresh, report }: { episodes: NonNullable<PatientWorkspaceData["clinical"]>["episodesOfCare"]; patientId: string; refresh: () => Promise<void>; report: (message: string) => void }) {
  const [draft, setDraft] = useState<EpisodeDraft>(blankEpisodeDraft);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await api.createEpisodeOfCare(patientId, { ...draft });
      setDraft(blankEpisodeDraft());
      await refresh();
      report("Episode of care created.");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to create the episode of care."));
    } finally {
      setBusy(false);
    }
  }
  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Episode of care</p><h3>Course-of-treatment tracking</h3><p className="muted">Groups appointments and notes under one diagnosis and plan of care. A patient may have more than one over time.</p></div></header>
    <details className="workspace-details"><summary>Start new episode of care</summary><form className="stack-form" onSubmit={create}>
      <label>Diagnosis<input value={draft.diagnosis} onChange={(event) => setDraft({ ...draft, diagnosis: event.target.value })} placeholder="e.g. Right knee ACL repair" /></label>
      <div className="field-grid">
        <label>Status<select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}><option value="active">Active</option><option value="on_hold">On hold</option><option value="discharged">Discharged</option><option value="cancelled">Cancelled</option></select></label>
        <label>Start date<input type="date" value={draft.startDate} onChange={(event) => setDraft({ ...draft, startDate: event.target.value })} required /></label>
      </div>
      <label>Notes (optional)<textarea rows={2} value={draft.notes} onChange={(event) => setDraft({ ...draft, notes: event.target.value })} /></label>
      <button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving..." : "Save episode"}</button>
    </form></details>
    {error && <p className="form-error" role="alert">{error}</p>}
    {episodes.length ? <ul className="record-list">{episodes.map((episode) => <li key={episode.id}><span><strong>{episode.diagnosis || "Episode of care"}</strong><small>Started {formatDate(episode.startDate)}{episode.primaryTherapistName ? ` · ${episode.primaryTherapistName}` : ""}</small></span><span className={`status-pill ${episode.status}`}>{episode.statusLabel}</span></li>)}</ul> : <p className="empty-copy">No episodes of care recorded yet.</p>}
  </article>;
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

const SELF_REPORT_MEASURES: [string, string][] = [
  ["lefs", "LEFS"],
  ["odi", "ODI"],
  ["ndi", "NDI"],
  ["quickdash", "QuickDASH"],
  ["psfs", "Patient-Specific Functional Scale"],
];

function OutcomePanel({ outcomes, assignments, hasPortalAccount, patientId, refresh, report }: { outcomes: NonNullable<PatientWorkspaceData["clinical"]>["outcomes"]; assignments: PortalOutcomeAssignment[]; hasPortalAccount: boolean; patientId: string; refresh: () => Promise<void>; report: (message: string) => void }) {
  const [measure, setMeasure] = useState("lefs");
  const [measuredOn, setMeasuredOn] = useState(dateInputValue());
  const [score, setScore] = useState("");
  const [maximumScore, setMaximumScore] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [assignMeasure, setAssignMeasure] = useState("lefs");
  const [assigning, setAssigning] = useState(false);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try { await api.recordOutcome(patientId, { measure, measuredOn, score, maximumScore, notes }); setScore(""); setMaximumScore(""); setNotes(""); await refresh(); report("Outcome total saved and its deterministic trend was refreshed."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to record the outcome score.")); }
    finally { setBusy(false); }
  }
  async function assignToPatient() {
    setAssigning(true); setError("");
    try { await api.assignOutcomeMeasure(patientId, assignMeasure); await refresh(); report("Outcome measure assigned — the patient can complete it through the portal."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to assign this outcome measure.")); }
    finally { setAssigning(false); }
  }
  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Outcome measures</p><h3>Score & trend tracking</h3><p className="muted">Enter reviewed total scores. Instrument question-level scoring is not calculated in the browser.</p></div></header>
    {hasPortalAccount && (
      <div className="compact-subsection">
        <strong>Assign to patient portal</strong>
        <p className="muted" style={{ margin: ".25rem 0 .5rem" }}>The patient answers question-by-question and the score is calculated automatically.</p>
        <div className="inline-form">
          <select value={assignMeasure} onChange={(event) => setAssignMeasure(event.target.value)}>
            {SELF_REPORT_MEASURES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <button className="secondary-button" type="button" disabled={assigning} onClick={() => void assignToPatient()}>
            {assigning ? "Assigning..." : "Assign"}
          </button>
        </div>
        {assignments.length > 0 && (
          <ul className="summary-list">
            {assignments.map((assignment) => (
              <li key={assignment.id}>
                <span><strong>{assignment.measureLabel}</strong><small>Assigned {formatDate(assignment.assignedAt)}</small></span>
                <span className={`status-pill ${assignment.status}`}>{assignment.status === "completed" ? "Completed" : "Pending"}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    )}
    <form className="stack-form" onSubmit={save}><label>Measure<select value={measure} onChange={(event) => setMeasure(event.target.value)}>{outcomeMeasures.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><div className="field-grid"><label>Date measured<input type="date" value={measuredOn} onChange={(event) => setMeasuredOn(event.target.value)} required /></label><label>Score<input type="number" step="0.01" min="0" value={score} onChange={(event) => setScore(event.target.value)} required /></label><label>Maximum (optional)<input type="number" step="0.01" min="0" value={maximumScore} onChange={(event) => setMaximumScore(event.target.value)} /></label></div><label>Clinical note (optional)<textarea rows={2} value={notes} onChange={(event) => setNotes(event.target.value)} /></label><button className="primary-button" type="submit" disabled={busy}>{busy ? "Recording..." : "Record outcome score"}</button></form>
    {error && <p className="form-error" role="alert">{error}</p>}
    {outcomes.length ? <ul className="record-list">{outcomes.map((outcome) => <li key={outcome.measure}><span><strong>{outcome.label}: {outcome.latest}{outcome.maximum !== null ? ` / ${outcome.maximum}` : ""}</strong><small>{outcome.trend} · change {outcome.delta} {outcome.unit} · {outcome.points.length} recorded point{outcome.points.length === 1 ? "" : "s"}</small></span><span className={`status-pill ${outcome.trend.toLowerCase()}`}>{outcome.trend}</span></li>)}</ul> : <p className="empty-copy">No outcome scores recorded.</p>}
  </article>;
}

function ExerciseEditForm({ programId, exercise, onSaved }: { programId: string; exercise: HomeExercise; onSaved: () => Promise<void> }) {
  const [dosage, setDosage] = useState(exercise.dosage);
  const [instructions, setInstructions] = useState(exercise.instructions);
  const [videoUrl, setVideoUrl] = useState(exercise.videoUrl);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      await api.updateHomeExercise(programId, exercise.id, { dosage, instructions, videoUrl });
      await onSaved();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to update this exercise."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="stack-form" onSubmit={save}>
      <label>Dosage<input value={dosage} onChange={(event) => setDosage(event.target.value)} required /></label>
      <label>Instructions<textarea rows={2} value={instructions} onChange={(event) => setInstructions(event.target.value)} required /></label>
      <label>Video URL (optional)<input value={videoUrl} onChange={(event) => setVideoUrl(event.target.value)} /></label>
      {error && <p className="form-error" role="alert">{error}</p>}
      <button className="secondary-button" type="submit" disabled={busy}>{busy ? "Saving..." : "Save changes"}</button>
    </form>
  );
}

function AddExerciseForm({ programId, onAdded }: { programId: string; onAdded: () => Promise<void> }) {
  const [name, setName] = useState("");
  const [instructions, setInstructions] = useState("");
  const [dosage, setDosage] = useState("");
  const [videoUrl, setVideoUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      await api.createHomeExercise(programId, { name, instructions, dosage, videoUrl });
      setName(""); setInstructions(""); setDosage(""); setVideoUrl("");
      await onAdded();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to add this exercise."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="workspace-details">
      <summary>Add exercise</summary>
      <form className="stack-form" onSubmit={add}>
        <label>Exercise name<input value={name} onChange={(event) => setName(event.target.value)} required /></label>
        <label>Instructions<textarea rows={2} value={instructions} onChange={(event) => setInstructions(event.target.value)} required /></label>
        <label>Dosage (e.g. 3x10)<input value={dosage} onChange={(event) => setDosage(event.target.value)} required /></label>
        <label>Video URL (optional)<input value={videoUrl} onChange={(event) => setVideoUrl(event.target.value)} placeholder="https://..." /></label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary-button" type="submit" disabled={busy}>{busy ? "Adding..." : "Add exercise"}</button>
      </form>
    </details>
  );
}

function ProgramExercises({ programId, exercises, refresh }: { programId: string; exercises: HomeExercise[]; refresh: () => Promise<void> }) {
  const [editingId, setEditingId] = useState<string | null>(null);
  return (
    <div className="compact-subsection">
      {exercises.length ? (
        <ul className="summary-list">
          {exercises.map((exercise) => (
            <li key={exercise.id}>
              <span>
                <strong>{exercise.name}</strong>
                <small>{exercise.dosage} · {exercise.instructions}{exercise.videoUrl ? " · has video" : ""}</small>
              </span>
              <button className="text-action" onClick={() => setEditingId(editingId === exercise.id ? null : exercise.id)}>
                {editingId === exercise.id ? "Close" : "Edit"}
              </button>
              {editingId === exercise.id && (
                <ExerciseEditForm programId={programId} exercise={exercise} onSaved={async () => { setEditingId(null); await refresh(); }} />
              )}
            </li>
          ))}
        </ul>
      ) : <p className="empty-copy">No exercises added yet.</p>}
      <AddExerciseForm programId={programId} onAdded={refresh} />
    </div>
  );
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
    {programs.length ? <div className="artifact-list">{programs.map((program) => <article className="workflow-record" key={program.id}><header><span><strong>{program.title}</strong><small>{program.prescribedBy} · {formatDate(program.createdAt)}</small></span><span className={`status-pill ${program.status}`}>{program.statusLabel}</span></header><p>{program.patientInstructions}</p>{program.precautions && <p className="safety-copy">Precautions: {program.precautions}</p>}{canSign && program.status === "draft" && <button className="secondary-button" disabled={Boolean(busy)} onClick={() => void approve(program.id)}>{busy === program.id ? "Activating..." : "Therapist activate"}</button>}<ProgramExercises programId={program.id} exercises={program.exercises} refresh={refresh} /></article>)}</div> : <p className="empty-copy">No home programs are in this chart.</p>}
  </article>;
}

function OperationsPanel({ workspace, patientId, refresh, report }: { workspace: PatientWorkspaceData; patientId: string; refresh: () => Promise<void>; report: (message: string) => void }) {
  const operations = workspace.operations!;
  return <div className="workspace-panel-grid">
    {operations.canManageSchedule && (
      <ScheduleCreatePanel
        patientId={patientId}
        staff={operations.schedulingStaff || []}
        appointments={operations.appointments || []}
        episodes={workspace.clinical?.episodesOfCare || []}
        authorizations={operations.authorizations || []}
        refresh={refresh}
        report={report}
      />
    )}
    {operations.canManageSchedule && <IntakeConsentPanel patientId={patientId} consents={operations.consents} intakes={operations.intakes} formSubmissions={operations.formSubmissions || []} refresh={refresh} report={report} />}
    {operations.canManageSchedule && <ReferralsPanel patientId={patientId} referrals={operations.referrals || []} refresh={refresh} report={report} />}
    <MessagePanel patientId={patientId} recipients={operations.recipients} messages={operations.messages} refresh={refresh} report={report} />
    {(operations.canManageBilling || operations.canCollectPayments) && <BillingPanel patientId={patientId} canManageBilling={operations.canManageBilling} superbills={operations.superbills || []} payments={operations.payments || []} refresh={refresh} report={report} />}
    {operations.canManageBilling && <AuthorizationPanel patientId={patientId} authorizations={operations.authorizations || []} refresh={refresh} report={report} />}
    {(operations.canManageBilling || operations.canCollectPayments) && <InsurancePanel patientId={patientId} canManageBilling={operations.canManageBilling} report={report} />}
    {(operations.canManageBilling || operations.canCollectPayments) && <ChargesPanel patientId={patientId} canManageBilling={operations.canManageBilling} report={report} />}
    {(operations.canManageBilling || operations.canCollectPayments) && <ClaimsPanel patientId={patientId} canManageBilling={operations.canManageBilling} report={report} />}
    {(operations.canManageBilling || operations.canCollectPayments) && <TransactionsPanel patientId={patientId} canManageBilling={operations.canManageBilling} report={report} />}
    {(operations.canManageBilling || operations.canCollectPayments) && <StatementsPanel patientId={patientId} canManageBilling={operations.canManageBilling} report={report} />}
    {(operations.canManageBilling || operations.canCollectPayments) && <CashPackagesPanel patientId={patientId} canManageBilling={operations.canManageBilling} report={report} />}
  </div>;
}

interface AuthorizationDraft {
  insuranceName: string;
  authorizationNumber: string;
  visitsApproved: string;
  startDate: string;
  expiresAt: string;
}

const blankAuthorizationDraft = (): AuthorizationDraft => ({ insuranceName: "", authorizationNumber: "", visitsApproved: "", startDate: dateInputValue(), expiresAt: dateInputValue(60) });

function AuthorizationPanel({ authorizations, patientId, refresh, report }: { authorizations: NonNullable<NonNullable<PatientWorkspaceData["operations"]>["authorizations"]>; patientId: string; refresh: () => Promise<void>; report: (message: string) => void }) {
  const [draft, setDraft] = useState<AuthorizationDraft>(blankAuthorizationDraft);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await api.createAuthorization(patientId, { ...draft, status: "active" });
      setDraft(blankAuthorizationDraft());
      await refresh();
      report("Authorization saved.");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to save the authorization."));
    } finally {
      setBusy(false);
    }
  }
  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Insurance authorization</p><h3>Approved visits & expiration</h3><p className="muted">Visits used update automatically when a visit's note is signed. This does not block scheduling on its own.</p></div></header>
    <details className="workspace-details"><summary>Add authorization</summary><form className="stack-form" onSubmit={create}>
      <div className="field-grid">
        <label>Insurance<input value={draft.insuranceName} onChange={(event) => setDraft({ ...draft, insuranceName: event.target.value })} placeholder="Payer name" /></label>
        <label>Authorization number<input value={draft.authorizationNumber} onChange={(event) => setDraft({ ...draft, authorizationNumber: event.target.value })} /></label>
      </div>
      <div className="field-grid">
        <label>Visits approved<input type="number" min="1" value={draft.visitsApproved} onChange={(event) => setDraft({ ...draft, visitsApproved: event.target.value })} required /></label>
        <label>Start date<input type="date" value={draft.startDate} onChange={(event) => setDraft({ ...draft, startDate: event.target.value })} required /></label>
        <label>Expires<input type="date" value={draft.expiresAt} onChange={(event) => setDraft({ ...draft, expiresAt: event.target.value })} required /></label>
      </div>
      <button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving..." : "Save authorization"}</button>
    </form></details>
    {error && <p className="form-error" role="alert">{error}</p>}
    {authorizations.length ? <ul className="record-list">{authorizations.map((authorization) => <li key={authorization.id}><span><strong>{authorization.insuranceName || "Authorization"} {authorization.authorizationNumber && `· ${authorization.authorizationNumber}`}</strong><small>{authorization.visitsUsed} of {authorization.visitsApproved} visits used · {authorization.visitsRemaining} remaining · expires {formatDate(authorization.expiresAt)}</small></span><LicenseBadge status={authorization.colorBucket} /></li>)}</ul> : <p className="empty-copy">No authorizations on file for this patient.</p>}
  </article>;
}

const blankInsuranceDraft = () => ({
  payerId: "", rank: "primary", planName: "", memberId: "", groupNumber: "",
  subscriberName: "", relationshipToSubscriber: "self", effectiveDate: "",
  copay: "", coinsurancePercent: "", deductible: "", authorizationRequired: false,
});

function InsurancePanel({ patientId, canManageBilling, report }: { patientId: string; canManageBilling: boolean; report: (message: string) => void }) {
  const [policies, setPolicies] = useState<PatientInsurancePolicy[]>([]);
  const [payerOptions, setPayerOptions] = useState<Payer[]>([]);
  const [draft, setDraft] = useState(blankInsuranceDraft);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);

  async function load() {
    try {
      const [policyResult, payerResult] = await Promise.all([
        api.patientInsurancePolicies(patientId),
        canManageBilling ? api.payers(true) : Promise.resolve({ payers: [] }),
      ]);
      setPolicies(policyResult.policies);
      setPayerOptions(payerResult.payers);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load insurance."));
    }
  }
  useEffect(() => { void load(); }, [patientId]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("create"); setError("");
    try {
      await api.createPatientInsurancePolicy(patientId, draft);
      setDraft(blankInsuranceDraft());
      setOpen(false);
      await load();
      report("Insurance policy saved.");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to save this insurance policy."));
    } finally {
      setBusy("");
    }
  }

  async function terminate(policyId: string) {
    setBusy(`terminate-${policyId}`); setError("");
    try {
      await api.terminatePatientInsurancePolicy(patientId, policyId);
      await load();
      report("Insurance policy terminated as of today.");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to terminate this policy."));
    } finally {
      setBusy("");
    }
  }

  async function verifyEligibility(policyId: string) {
    setBusy(`eligibility-${policyId}`); setError("");
    try {
      const result = await api.verifyPatientInsuranceEligibility(patientId, policyId);
      report(result.message);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to verify eligibility."));
    } finally {
      setBusy("");
    }
  }

  async function uploadCard(policyId: string, side: "front" | "back", file: File) {
    setBusy(`card-${policyId}-${side}`); setError("");
    try {
      await api.uploadPatientInsuranceCard(patientId, policyId, side, file);
      await load();
      report(`Insurance card (${side}) uploaded.`);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to upload this card image."));
    } finally {
      setBusy("");
    }
  }

  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Insurance</p><h3>Patient insurance policies</h3><p className="muted">Terminating a policy keeps it on file for billing history — it is never deleted.</p></div></header>
    {canManageBilling && (
      <details className="workspace-details" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary>Add insurance policy</summary>
        <form className="stack-form" onSubmit={create}>
          <div className="field-grid">
            <label>Payer
              <select value={draft.payerId} onChange={(event) => setDraft({ ...draft, payerId: event.target.value })} required>
                <option value="">Select a payer</option>
                {payerOptions.map((payer) => <option key={payer.id} value={payer.id}>{payer.name}</option>)}
              </select>
            </label>
            <label>Rank
              <select value={draft.rank} onChange={(event) => setDraft({ ...draft, rank: event.target.value })}>
                <option value="primary">Primary</option>
                <option value="secondary">Secondary</option>
                <option value="tertiary">Tertiary</option>
              </select>
            </label>
            <label>Plan name<input value={draft.planName} onChange={(event) => setDraft({ ...draft, planName: event.target.value })} /></label>
            <label>Member ID<input value={draft.memberId} onChange={(event) => setDraft({ ...draft, memberId: event.target.value })} required /></label>
            <label>Group number<input value={draft.groupNumber} onChange={(event) => setDraft({ ...draft, groupNumber: event.target.value })} /></label>
            <label>Relationship to subscriber
              <select value={draft.relationshipToSubscriber} onChange={(event) => setDraft({ ...draft, relationshipToSubscriber: event.target.value })}>
                <option value="self">Self</option>
                <option value="spouse">Spouse</option>
                <option value="child">Child</option>
                <option value="other">Other</option>
              </select>
            </label>
            <label>Subscriber name<input value={draft.subscriberName} onChange={(event) => setDraft({ ...draft, subscriberName: event.target.value })} /></label>
            <label>Effective date<input type="date" value={draft.effectiveDate} onChange={(event) => setDraft({ ...draft, effectiveDate: event.target.value })} required /></label>
            <label>Copay<input type="number" step="0.01" min="0" value={draft.copay} onChange={(event) => setDraft({ ...draft, copay: event.target.value })} /></label>
            <label>Coinsurance %<input type="number" step="0.01" min="0" max="100" value={draft.coinsurancePercent} onChange={(event) => setDraft({ ...draft, coinsurancePercent: event.target.value })} /></label>
            <label>Deductible<input type="number" step="0.01" min="0" value={draft.deductible} onChange={(event) => setDraft({ ...draft, deductible: event.target.value })} /></label>
          </div>
          <label className="check-label"><input type="checkbox" checked={draft.authorizationRequired} onChange={(event) => setDraft({ ...draft, authorizationRequired: event.target.checked })} /> Authorization required for this policy</label>
          <button className="primary-button" type="submit" disabled={busy === "create"}>{busy === "create" ? "Saving..." : "Save insurance policy"}</button>
        </form>
      </details>
    )}
    {error && <p className="form-error" role="alert">{error}</p>}
    {policies.length ? (
      <ul className="record-list">
        {policies.map((policy) => (
          <li key={policy.id}>
            <span>
              <strong>{policy.payerName} · {policy.rankLabel}</strong>
              <small>
                Member ID {policy.memberId}{policy.groupNumber && ` · Group ${policy.groupNumber}`} · effective {formatDate(policy.effectiveDate)}
                {policy.terminationDate && ` · terminated ${formatDate(policy.terminationDate)}`}
                {policy.copay && ` · Copay $${policy.copay}`}
                {policy.coinsurancePercent && ` · Coinsurance ${policy.coinsurancePercent}%`}
              </small>
              {canManageBilling && (
                <div className="button-row" style={{ marginTop: ".4rem" }}>
                  <label className="text-action" style={{ cursor: "pointer" }}>
                    {busy === `card-${policy.id}-front` ? "Uploading..." : policy.hasCardFront ? "Replace card (front)" : "Upload card (front)"}
                    <input type="file" accept="image/png,image/jpeg" style={{ display: "none" }} onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadCard(policy.id, "front", file); event.target.value = ""; }} />
                  </label>
                  <label className="text-action" style={{ cursor: "pointer" }}>
                    {busy === `card-${policy.id}-back` ? "Uploading..." : policy.hasCardBack ? "Replace card (back)" : "Upload card (back)"}
                    <input type="file" accept="image/png,image/jpeg" style={{ display: "none" }} onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadCard(policy.id, "back", file); event.target.value = ""; }} />
                  </label>
                  {policy.hasCardFront && <a className="text-action" href={api.patientInsuranceCardUrl(patientId, policy.id, "front")} target="_blank" rel="noreferrer">View front</a>}
                  {policy.hasCardBack && <a className="text-action" href={api.patientInsuranceCardUrl(patientId, policy.id, "back")} target="_blank" rel="noreferrer">View back</a>}
                  <button className="text-action" type="button" disabled={busy === `eligibility-${policy.id}`} onClick={() => void verifyEligibility(policy.id)}>{busy === `eligibility-${policy.id}` ? "Checking..." : "Verify eligibility"}</button>
                  {policy.isActive && <button className="text-action" type="button" disabled={busy === `terminate-${policy.id}`} onClick={() => void terminate(policy.id)}>{busy === `terminate-${policy.id}` ? "Terminating..." : "Terminate"}</button>}
                </div>
              )}
            </span>
            <span className={`status-pill ${policy.isActive ? "active" : "inactive"}`}>{policy.isActive ? "Active" : "Terminated"}</span>
          </li>
        ))}
      </ul>
    ) : <p className="empty-copy">No insurance policies on file for this patient.</p>}
  </article>;
}

const blankChargeDraft = () => ({
  serviceDate: dateInputValue(), providerId: "", locationId: "", cptCode: "", modifiers: "",
  units: "1", minutes: "", chargeAmount: "", unitsOverrideReason: "",
});

function ChargesPanel({ patientId, canManageBilling, report }: { patientId: string; canManageBilling: boolean; report: (message: string) => void }) {
  const [charges, setCharges] = useState<Charge[]>([]);
  const [draft, setDraft] = useState(blankChargeDraft);
  const [diagnosisQuery, setDiagnosisQuery] = useState("");
  const [diagnosisResults, setDiagnosisResults] = useState<DiagnosisCode[]>([]);
  const [selectedDiagnoses, setSelectedDiagnoses] = useState<DiagnosisCode[]>([]);
  const [locations, setLocations] = useState<ClinicLocation[]>([]);
  const [staff, setStaff] = useState<StaffOption[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);

  async function load() {
    try {
      const [chargeResult, locationResult, staffResult] = await Promise.all([
        api.patientCharges(patientId),
        canManageBilling ? api.locations() : Promise.resolve({ locations: [] }),
        canManageBilling ? api.staffOptions() : Promise.resolve({ staff: [] }),
      ]);
      setCharges(chargeResult.charges);
      setLocations(locationResult.locations);
      setStaff(staffResult.staff);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load charges."));
    }
  }
  useEffect(() => { void load(); }, [patientId]);

  async function searchDiagnoses(query: string) {
    setDiagnosisQuery(query);
    if (query.trim().length < 2) {
      setDiagnosisResults([]);
      return;
    }
    try {
      setDiagnosisResults((await api.diagnosisCodes(query)).diagnosisCodes);
    } catch {
      setDiagnosisResults([]);
    }
  }

  function toggleDiagnosis(code: DiagnosisCode) {
    setSelectedDiagnoses((current) =>
      current.some((c) => c.code === code.code) ? current.filter((c) => c.code !== code.code) : [...current, code],
    );
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("create"); setError("");
    try {
      const body: Record<string, unknown> = {
        serviceDate: draft.serviceDate, providerId: draft.providerId, chargeAmount: draft.chargeAmount,
        cptCode: draft.cptCode, units: Number(draft.units) || 1,
        modifiers: draft.modifiers.split(",").map((m) => m.trim()).filter(Boolean),
        diagnosisCodeIds: selectedDiagnoses.map((code) => code.code),
      };
      if (draft.locationId) body.locationId = draft.locationId;
      if (draft.minutes) body.minutes = Number(draft.minutes);
      if (draft.unitsOverrideReason) body.unitsOverrideReason = draft.unitsOverrideReason;
      await api.createPatientCharge(patientId, body);
      setDraft(blankChargeDraft());
      setSelectedDiagnoses([]);
      setOpen(false);
      await load();
      report("Charge saved.");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to save this charge."));
    } finally {
      setBusy("");
    }
  }

  async function voidCharge(chargeId: string) {
    setBusy(`void-${chargeId}`); setError("");
    try {
      await api.updatePatientCharge(patientId, chargeId, { status: "void" });
      await load();
      report("Charge voided.");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to void this charge."));
    } finally {
      setBusy("");
    }
  }

  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Charges</p><h3>Charge entry</h3><p className="muted">Recommended units come from documented timed minutes (8-minute rule) — entering a different value never rewrites the note, it just requires a reason.</p></div></header>
    {canManageBilling && (
      <details className="workspace-details" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary>Add charge</summary>
        <form className="stack-form" onSubmit={create}>
          <div className="field-grid">
            <label>Service date<input type="date" value={draft.serviceDate} onChange={(event) => setDraft({ ...draft, serviceDate: event.target.value })} required /></label>
            <label>Provider
              <select value={draft.providerId} onChange={(event) => setDraft({ ...draft, providerId: event.target.value })} required>
                <option value="">Select a provider</option>
                {staff.map((member) => <option key={member.id} value={member.id}>{member.displayName}</option>)}
              </select>
            </label>
            <label>Location (optional)
              <select value={draft.locationId} onChange={(event) => setDraft({ ...draft, locationId: event.target.value })}>
                <option value="">Not specified</option>
                {locations.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}
              </select>
            </label>
            <label>CPT / HCPCS code<input value={draft.cptCode} onChange={(event) => setDraft({ ...draft, cptCode: event.target.value.toUpperCase() })} placeholder="97110" required /></label>
            <label>Modifiers (comma-separated)<input value={draft.modifiers} onChange={(event) => setDraft({ ...draft, modifiers: event.target.value })} placeholder="GP, 59" /></label>
            <label>Units<input type="number" min={1} value={draft.units} onChange={(event) => setDraft({ ...draft, units: event.target.value })} required /></label>
            <label>Timed minutes (optional)<input type="number" min={0} value={draft.minutes} onChange={(event) => setDraft({ ...draft, minutes: event.target.value })} /></label>
            <label>Charge amount<input type="number" step="0.01" min="0" value={draft.chargeAmount} onChange={(event) => setDraft({ ...draft, chargeAmount: event.target.value })} required /></label>
          </div>
          <label>Diagnosis codes
            <input value={diagnosisQuery} onChange={(event) => void searchDiagnoses(event.target.value)} placeholder="Search ICD-10 (e.g. low back pain, M54)" />
          </label>
          {diagnosisResults.length > 0 && (
            <ul className="record-list">
              {diagnosisResults.map((code) => (
                <li key={code.code}>
                  <span><strong>{code.code}</strong><small>{code.description}</small></span>
                  <button type="button" className="text-action" onClick={() => toggleDiagnosis(code)}>
                    {selectedDiagnoses.some((c) => c.code === code.code) ? "Remove" : "Add"}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {selectedDiagnoses.length > 0 && <p className="muted">Selected: {selectedDiagnoses.map((c) => c.code).join(", ")}</p>}
          <label>Units override reason (only needed if it differs from the recommendation)
            <input value={draft.unitsOverrideReason} onChange={(event) => setDraft({ ...draft, unitsOverrideReason: event.target.value })} />
          </label>
          <button className="primary-button" type="submit" disabled={busy === "create"}>{busy === "create" ? "Saving..." : "Save charge"}</button>
        </form>
      </details>
    )}
    {error && <p className="form-error" role="alert">{error}</p>}
    {charges.length ? (
      <ul className="record-list">
        {charges.map((charge) => (
          <li key={charge.id}>
            <span>
              <strong>{charge.cptCode}{charge.modifiers.length > 0 && ` (${charge.modifiers.join(", ")})`} · {formatDate(charge.serviceDate)}</strong>
              <small>
                {charge.providerName}{charge.locationName && ` · ${charge.locationName}`} · {charge.units} unit{charge.units === 1 ? "" : "s"}
                {charge.recommendedUnits !== null && ` (recommended ${charge.recommendedUnits}${charge.unitsDifference ? `, diff ${charge.unitsDifference > 0 ? "+" : ""}${charge.unitsDifference}` : ""})`}
                {" "}· ${charge.chargeAmount}
                {charge.diagnosisCodes.length > 0 && ` · ${charge.diagnosisCodes.map((d) => d.code).join(", ")}`}
              </small>
              {charge.unitsOverrideReason && <small className="muted">Override reason: {charge.unitsOverrideReason}</small>}
            </span>
            <span className={`status-pill ${charge.status}`}>{charge.statusLabel}</span>
            {canManageBilling && charge.status !== "void" && (
              <button className="text-action" disabled={busy === `void-${charge.id}`} onClick={() => void voidCharge(charge.id)}>
                {busy === `void-${charge.id}` ? "Voiding..." : "Void"}
              </button>
            )}
          </li>
        ))}
      </ul>
    ) : <p className="empty-copy">No charges on file for this patient.</p>}
  </article>;
}

const CLAIM_STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "accepted", label: "Accepted" },
  { value: "rejected", label: "Rejected" },
  { value: "processing", label: "Processing" },
  { value: "denied", label: "Denied" },
  { value: "partial_payment", label: "Partial Payment" },
  { value: "paid", label: "Paid" },
  { value: "appealed", label: "Appealed" },
  { value: "corrected", label: "Corrected" },
  { value: "closed", label: "Closed" },
];
const CLAIM_PRE_SUBMISSION_STATUSES = new Set(["draft", "ready", "validation_error"]);

function ClaimsPanel({ patientId, canManageBilling, report }: { patientId: string; canManageBilling: boolean; report: (message: string) => void }) {
  const [claims, setClaims] = useState<Claim[]>([]);
  const [unclaimedCharges, setUnclaimedCharges] = useState<Charge[]>([]);
  const [policies, setPolicies] = useState<PatientInsurancePolicy[]>([]);
  const [policyId, setPolicyId] = useState("");
  const [selectedChargeIds, setSelectedChargeIds] = useState<string[]>([]);
  const [findingsByClaim, setFindingsByClaim] = useState<Record<string, ClaimValidationFinding[]>>({});
  const [cms1500ByClaim, setCms1500ByClaim] = useState<Record<string, Cms1500Data>>({});
  const [statusChoice, setStatusChoice] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);

  async function load() {
    try {
      const [claimResult, chargeResult, policyResult] = await Promise.all([
        api.patientClaims(patientId),
        canManageBilling ? api.patientCharges(patientId) : Promise.resolve({ charges: [] }),
        canManageBilling ? api.patientInsurancePolicies(patientId) : Promise.resolve({ policies: [] }),
      ]);
      setClaims(claimResult.claims);
      setUnclaimedCharges(chargeResult.charges.filter((charge) => !charge.claimId && charge.status !== "void"));
      setPolicies(policyResult.policies);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load claims."));
    }
  }
  useEffect(() => { void load(); }, [patientId]);

  function toggleCharge(chargeId: string) {
    setSelectedChargeIds((current) => (current.includes(chargeId) ? current.filter((id) => id !== chargeId) : [...current, chargeId]));
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("create"); setError("");
    try {
      await api.createPatientClaim(patientId, { patientInsuranceId: policyId, chargeIds: selectedChargeIds });
      setPolicyId(""); setSelectedChargeIds([]); setOpen(false);
      await load();
      report("Claim created from the selected charges.");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to create this claim."));
    } finally {
      setBusy("");
    }
  }

  async function validate(claimId: string) {
    setBusy(`validate-${claimId}`); setError("");
    try {
      const result = await api.validateClaim(patientId, claimId);
      setFindingsByClaim((current) => ({ ...current, [claimId]: result.findings }));
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to validate this claim."));
    } finally {
      setBusy("");
    }
  }

  async function submit(claimId: string) {
    setBusy(`submit-${claimId}`); setError("");
    try {
      await api.submitClaim(patientId, claimId);
      await load();
      report("Claim submitted (internal tracking — no clearinghouse is connected yet).");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to submit this claim."));
    } finally {
      setBusy("");
    }
  }

  async function checkStatus(claimId: string) {
    setBusy(`check-${claimId}`); setError("");
    try {
      const result = await api.checkClaimStatus(patientId, claimId);
      report(result.clearinghouseMessage);
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to check this claim's status."));
    } finally {
      setBusy("");
    }
  }

  async function updateStatus(claimId: string) {
    const status = statusChoice[claimId];
    if (!status) return;
    setBusy(`status-${claimId}`); setError("");
    try {
      await api.updateClaimStatus(patientId, claimId, status);
      await load();
      report("Claim status updated.");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to update this claim's status."));
    } finally {
      setBusy("");
    }
  }

  async function loadCms1500(claimId: string) {
    setBusy(`cms1500-${claimId}`); setError("");
    try {
      const result = await api.claimCms1500(patientId, claimId);
      setCms1500ByClaim((current) => ({ ...current, [claimId]: result.cms1500 }));
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load CMS-1500 data."));
    } finally {
      setBusy("");
    }
  }

  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Claims</p><h3>Insurance claims</h3><p className="muted">Validate before submitting — a claim can only be submitted once it has zero blocking errors. No clearinghouse is connected yet, so submission records the claim internally only.</p></div></header>
    {canManageBilling && (
      <details className="workspace-details" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary>Create claim from charges</summary>
        <form className="stack-form" onSubmit={create}>
          <label>Insurance policy
            <select value={policyId} onChange={(event) => setPolicyId(event.target.value)} required>
              <option value="">Select a policy</option>
              {policies.map((policy) => <option key={policy.id} value={policy.id}>{policy.payerName} · {policy.rankLabel} · {policy.memberId}</option>)}
            </select>
          </label>
          {unclaimedCharges.length > 0 ? (
            <ul className="record-list">
              {unclaimedCharges.map((charge) => (
                <li key={charge.id}>
                  <span><strong>{charge.cptCode} · {formatDate(charge.serviceDate)}</strong><small>{charge.units} unit{charge.units === 1 ? "" : "s"} · ${charge.chargeAmount}</small></span>
                  <button type="button" className="text-action" onClick={() => toggleCharge(charge.id)}>
                    {selectedChargeIds.includes(charge.id) ? "Remove" : "Add"}
                  </button>
                </li>
              ))}
            </ul>
          ) : <p className="empty-copy">No unclaimed charges are available.</p>}
          <button className="primary-button" type="submit" disabled={busy === "create" || !policyId || selectedChargeIds.length === 0}>
            {busy === "create" ? "Creating..." : "Create claim"}
          </button>
        </form>
      </details>
    )}
    {error && <p className="form-error" role="alert">{error}</p>}
    {claims.length ? (
      <ul className="record-list">
        {claims.map((claim) => {
          const findings = findingsByClaim[claim.id];
          const cms1500 = cms1500ByClaim[claim.id];
          const preSubmission = CLAIM_PRE_SUBMISSION_STATUSES.has(claim.status);
          return (
            <li key={claim.id} style={{ flexDirection: "column", alignItems: "stretch" }}>
              <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
                <span>
                  <strong>{claim.payerName} · {claim.chargeIds.length} charge{claim.chargeIds.length === 1 ? "" : "s"}</strong>
                  <small>${claim.totalChargeAmount} · Diagnoses: {claim.diagnosisCodeList.join(", ") || "None"}{claim.submittedAt && ` · Submitted ${formatDate(claim.submittedAt)}`}</small>
                </span>
                <span className={`status-pill ${claim.status}`}>{claim.statusLabel}</span>
              </div>
              {canManageBilling && (
                <div className="button-row" style={{ marginTop: ".5rem" }}>
                  {preSubmission && (
                    <button className="secondary-button" disabled={busy === `validate-${claim.id}`} onClick={() => void validate(claim.id)}>
                      {busy === `validate-${claim.id}` ? "Validating..." : "Validate"}
                    </button>
                  )}
                  {claim.status === "ready" && (
                    <button className="secondary-button" disabled={busy === `submit-${claim.id}`} onClick={() => void submit(claim.id)}>
                      {busy === `submit-${claim.id}` ? "Submitting..." : "Submit claim"}
                    </button>
                  )}
                  {!preSubmission && (
                    <>
                      <button className="text-action" disabled={busy === `check-${claim.id}`} onClick={() => void checkStatus(claim.id)}>
                        {busy === `check-${claim.id}` ? "Checking..." : "Check status"}
                      </button>
                      <select value={statusChoice[claim.id] || ""} onChange={(event) => setStatusChoice((current) => ({ ...current, [claim.id]: event.target.value }))}>
                        <option value="">Update status to...</option>
                        {CLAIM_STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                      </select>
                      <button className="text-action" disabled={busy === `status-${claim.id}` || !statusChoice[claim.id]} onClick={() => void updateStatus(claim.id)}>
                        {busy === `status-${claim.id}` ? "Updating..." : "Apply"}
                      </button>
                    </>
                  )}
                  <button className="text-action" disabled={busy === `cms1500-${claim.id}`} onClick={() => void loadCms1500(claim.id)}>
                    {busy === `cms1500-${claim.id}` ? "Loading..." : "View CMS-1500 data"}
                  </button>
                </div>
              )}
              {findings && findings.length > 0 && (
                <ul className="record-list" style={{ marginTop: ".5rem" }}>
                  {findings.map((finding, index) => (
                    <li key={`${claim.id}-${finding.code}-${index}`}>
                      <span><strong>{finding.severity === "error" ? "Blocks submission" : "Warning"}</strong><small>{finding.message}</small></span>
                    </li>
                  ))}
                </ul>
              )}
              {findings && findings.length === 0 && <p className="empty-copy positive">No validation issues found.</p>}
              {cms1500 && (
                <div className="table-wrap" style={{ marginTop: ".5rem" }}>
                  <table>
                    <thead><tr><th>Line</th><th>DOS</th><th>CPT</th><th>Modifiers</th><th>Dx Pointers</th><th>Units</th><th>Amount</th><th>Rendering NPI</th></tr></thead>
                    <tbody>
                      {cms1500.serviceLines.map((line) => (
                        <tr key={line.lineNumber}>
                          <td>{line.lineNumber}</td><td>{formatDate(line.serviceDate)}</td><td>{line.cptCode}</td>
                          <td>{line.modifiers.join(", ") || "—"}</td><td>{line.diagnosisPointers.join(", ") || "—"}</td>
                          <td>{line.units}</td><td>${line.chargeAmount}</td><td>{line.renderingProviderNpi || "Missing"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    ) : <p className="empty-copy">No claims on file for this patient.</p>}
  </article>;
}

const TRANSACTION_KIND_OPTIONS: { value: string; label: string }[] = [
  { value: "insurance_payment", label: "Insurance Payment" },
  { value: "patient_payment", label: "Patient Payment" },
  { value: "adjustment", label: "Contractual Adjustment" },
  { value: "write_off", label: "Write-off" },
  { value: "refund", label: "Refund" },
  { value: "transfer", label: "Transfer" },
];
const TRANSACTION_METHOD_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Not specified" },
  { value: "check", label: "Check" },
  { value: "eft", label: "EFT" },
  { value: "credit_card", label: "Credit Card" },
  { value: "cash", label: "Cash" },
  { value: "era", label: "ERA (Electronic)" },
  { value: "other", label: "Other" },
];
const blankTransactionDraft = () => ({
  kind: "insurance_payment", method: "", amount: "", paymentDate: dateInputValue(), claimId: "",
  transferredToClaimId: "", reference: "", denialCode: "", denialReason: "", notes: "",
});

function TransactionsPanel({ patientId, canManageBilling, report }: { patientId: string; canManageBilling: boolean; report: (message: string) => void }) {
  const [transactions, setTransactions] = useState<ClaimTransaction[]>([]);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [draft, setDraft] = useState(blankTransactionDraft);
  const [matchChoice, setMatchChoice] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);

  async function load() {
    try {
      const [transactionResult, claimResult] = await Promise.all([
        api.patientTransactions(patientId),
        canManageBilling ? api.patientClaims(patientId) : Promise.resolve({ claims: [] }),
      ]);
      setTransactions(transactionResult.transactions);
      setClaims(claimResult.claims);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load transactions."));
    }
  }
  useEffect(() => { void load(); }, [patientId]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("create"); setError("");
    try {
      const body: Record<string, unknown> = {
        kind: draft.kind, amount: draft.amount, paymentDate: draft.paymentDate,
        reference: draft.reference, denialCode: draft.denialCode, denialReason: draft.denialReason, notes: draft.notes,
      };
      if (draft.method) body.method = draft.method;
      if (draft.claimId) body.claimId = draft.claimId;
      if (draft.transferredToClaimId) body.transferredToClaimId = draft.transferredToClaimId;
      await api.createPatientTransaction(patientId, body);
      setDraft(blankTransactionDraft());
      setOpen(false);
      await load();
      report("Transaction posted.");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to post this transaction."));
    } finally {
      setBusy("");
    }
  }

  async function match(transactionId: string) {
    const claimId = matchChoice[transactionId];
    if (!claimId) return;
    setBusy(`match-${transactionId}`); setError("");
    try {
      await api.matchTransaction(patientId, transactionId, claimId);
      await load();
      report("Transaction matched to the claim.");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to match this transaction."));
    } finally {
      setBusy("");
    }
  }

  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Payments</p><h3>Payment posting</h3><p className="muted">Insurance/patient payments, adjustments, write-offs, refunds, and transfers. An ERA line that can't be matched yet can be posted with no claim and matched later.</p></div></header>
    {canManageBilling && (
      <details className="workspace-details" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary>Post transaction</summary>
        <form className="stack-form" onSubmit={create}>
          <div className="field-grid">
            <label>Type
              <select value={draft.kind} onChange={(event) => setDraft({ ...draft, kind: event.target.value })}>
                {TRANSACTION_KIND_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label>Method
              <select value={draft.method} onChange={(event) => setDraft({ ...draft, method: event.target.value })}>
                {TRANSACTION_METHOD_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label>Amount<input type="number" step="0.01" min="0.01" value={draft.amount} onChange={(event) => setDraft({ ...draft, amount: event.target.value })} required /></label>
            <label>Payment date<input type="date" value={draft.paymentDate} onChange={(event) => setDraft({ ...draft, paymentDate: event.target.value })} /></label>
            <label>Claim (optional — leave blank if unmatched)
              <select value={draft.claimId} onChange={(event) => setDraft({ ...draft, claimId: event.target.value })}>
                <option value="">Unmatched</option>
                {claims.map((claim) => <option key={claim.id} value={claim.id}>{claim.payerName} · ${claim.balance} balance</option>)}
              </select>
            </label>
            <label>Reference (check #, EFT trace, ERA ref)<input value={draft.reference} onChange={(event) => setDraft({ ...draft, reference: event.target.value })} /></label>
            {draft.kind === "transfer" && (
              <label>Transfer to claim
                <select value={draft.transferredToClaimId} onChange={(event) => setDraft({ ...draft, transferredToClaimId: event.target.value })} required>
                  <option value="">Select destination claim</option>
                  {claims.filter((claim) => claim.id !== draft.claimId).map((claim) => <option key={claim.id} value={claim.id}>{claim.payerName}</option>)}
                </select>
              </label>
            )}
            {draft.kind === "adjustment" && (
              <>
                <label>Denial code<input value={draft.denialCode} onChange={(event) => setDraft({ ...draft, denialCode: event.target.value })} /></label>
                <label>Denial reason<input value={draft.denialReason} onChange={(event) => setDraft({ ...draft, denialReason: event.target.value })} /></label>
              </>
            )}
          </div>
          <label>Notes<textarea value={draft.notes} onChange={(event) => setDraft({ ...draft, notes: event.target.value })} /></label>
          <button className="primary-button" type="submit" disabled={busy === "create"}>{busy === "create" ? "Posting..." : "Post transaction"}</button>
        </form>
      </details>
    )}
    {error && <p className="form-error" role="alert">{error}</p>}
    {transactions.length ? (
      <ul className="record-list">
        {transactions.map((transaction) => (
          <li key={transaction.id}>
            <span>
              <strong>{transaction.kindLabel} · ${transaction.amount}</strong>
              <small>{formatDate(transaction.paymentDate)}{transaction.methodLabel && ` · ${transaction.methodLabel}`}{transaction.reference && ` · Ref ${transaction.reference}`} · {transaction.recordedBy || "System"}</small>
              {!transaction.isMatched && canManageBilling && (
                <div className="button-row" style={{ marginTop: ".3rem" }}>
                  <select value={matchChoice[transaction.id] || ""} onChange={(event) => setMatchChoice((current) => ({ ...current, [transaction.id]: event.target.value }))}>
                    <option value="">Match to claim...</option>
                    {claims.map((claim) => <option key={claim.id} value={claim.id}>{claim.payerName}</option>)}
                  </select>
                  <button className="text-action" disabled={busy === `match-${transaction.id}` || !matchChoice[transaction.id]} onClick={() => void match(transaction.id)}>
                    {busy === `match-${transaction.id}` ? "Matching..." : "Match"}
                  </button>
                </div>
              )}
            </span>
            <span className={`status-pill ${transaction.isMatched ? "active" : "inactive"}`}>{transaction.isMatched ? "Matched" : "Unmatched"}</span>
          </li>
        ))}
      </ul>
    ) : <p className="empty-copy">No transactions posted for this patient.</p>}
  </article>;
}

function StatementsPanel({ patientId, canManageBilling, report }: { patientId: string; canManageBilling: boolean; report: (message: string) => void }) {
  const [statements, setStatements] = useState<PatientStatement[]>([]);
  const [viewing, setViewing] = useState<PatientStatementData | null>(null);
  const [dueDate, setDueDate] = useState(dateInputValue(30));
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);

  async function load() {
    try {
      setStatements((await api.patientStatements(patientId)).statements);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load statements."));
    }
  }
  useEffect(() => { void load(); }, [patientId]);

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("create"); setError("");
    try {
      const result = await api.generatePatientStatement(patientId, { dueDate });
      setViewing(result.data);
      setOpen(false);
      await load();
      report("Statement generated.");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to generate this statement."));
    } finally {
      setBusy("");
    }
  }

  async function view(statementId: string) {
    setBusy(`view-${statementId}`); setError("");
    try {
      const result = await api.patientStatementDetail(patientId, statementId);
      setViewing(result.data);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load this statement."));
    } finally {
      setBusy("");
    }
  }

  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Statements</p><h3>Patient statements</h3><p className="muted">Combines outstanding insurance-claim balance and cash-pay balance as of the statement date.</p></div></header>
    {canManageBilling && (
      <details className="workspace-details" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary>Generate statement</summary>
        <form className="stack-form" onSubmit={generate}>
          <label>Due date<input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} required /></label>
          <button className="primary-button" type="submit" disabled={busy === "create"}>{busy === "create" ? "Generating..." : "Generate statement"}</button>
        </form>
      </details>
    )}
    {error && <p className="form-error" role="alert">{error}</p>}
    {statements.length ? (
      <ul className="record-list">
        {statements.map((statement) => (
          <li key={statement.id}>
            <span><strong>{formatDate(statement.statementDate)}</strong><small>Balance ${statement.balanceAtGeneration} · Due {formatDate(statement.dueDate)}</small></span>
            <button className="text-action" disabled={busy === `view-${statement.id}`} onClick={() => void view(statement.id)}>
              {busy === `view-${statement.id}` ? "Loading..." : "View"}
            </button>
          </li>
        ))}
      </ul>
    ) : <p className="empty-copy">No statements generated for this patient.</p>}
    {viewing && (
      <div className="modal-backdrop" onClick={() => setViewing(null)}>
        <section className="move-dialog client-dialog" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
          <button className="dialog-close" onClick={() => setViewing(null)} aria-label="Close">&times;</button>
          <p className="eyebrow">{viewing.practice.name}</p>
          <h2>Statement — {formatDate(viewing.statementDate)}</h2>
          <p className="muted">{viewing.patient.fullName} · {viewing.patient.address}</p>
          {viewing.insuranceClaims.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Payer</th><th>Status</th><th>Charges</th><th>Paid</th><th>Adjusted</th><th>Balance</th></tr></thead>
                <tbody>
                  {viewing.insuranceClaims.map((row) => (
                    <tr key={row.claimId}><td>{row.payerName}</td><td>{row.statusLabel}</td><td>${row.chargeTotal}</td><td>${row.paid}</td><td>${row.adjusted}</td><td>${row.balance}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {viewing.cashCharges.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Date</th><th>Amount</th><th>Paid</th><th>Balance</th></tr></thead>
                <tbody>
                  {viewing.cashCharges.map((row) => (
                    <tr key={row.superbillId}><td>{formatDate(row.serviceDate)}</td><td>${row.amount}</td><td>${row.paid}</td><td>${row.balance}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p><strong>Total balance due: ${viewing.totalBalance}</strong> (by {formatDate(viewing.dueDate)})</p>
          <p className="muted">{viewing.paymentInstructions}</p>
        </section>
      </div>
    )}
  </article>;
}

function CashPackagesPanel({ patientId, canManageBilling, report }: { patientId: string; canManageBilling: boolean; report: (message: string) => void }) {
  const [packages, setPackages] = useState<CashPackage[]>([]);
  const [draft, setDraft] = useState({ kind: "package", name: "", price: "", visitsIncluded: "", discountPercent: "", expiresAt: "" });
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);

  async function load() {
    try {
      setPackages((await api.patientCashPackages(patientId)).cashPackages);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load cash packages."));
    }
  }
  useEffect(() => { void load(); }, [patientId]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("create"); setError("");
    try {
      const body: Record<string, unknown> = { kind: draft.kind, name: draft.name, price: draft.price };
      if (draft.kind === "package" && draft.visitsIncluded) body.visitsIncluded = Number(draft.visitsIncluded);
      if (draft.discountPercent) body.discountPercent = draft.discountPercent;
      if (draft.expiresAt) body.expiresAt = draft.expiresAt;
      await api.createCashPackage(patientId, body);
      setDraft({ kind: "package", name: "", price: "", visitsIncluded: "", discountPercent: "", expiresAt: "" });
      setOpen(false);
      await load();
      report("Package saved.");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to save this package."));
    } finally {
      setBusy("");
    }
  }

  async function recordVisit(packageId: string) {
    setBusy(`visit-${packageId}`); setError("");
    try {
      await api.updateCashPackage(patientId, packageId, { action: "record_visit" });
      await load();
      report("Visit recorded.");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to record this visit."));
    } finally {
      setBusy("");
    }
  }

  async function cancel(packageId: string) {
    setBusy(`cancel-${packageId}`); setError("");
    try {
      await api.updateCashPackage(patientId, packageId, { action: "cancel" });
      await load();
      report("Package cancelled.");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to cancel this package."));
    } finally {
      setBusy("");
    }
  }

  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Cash-pay</p><h3>Packages & memberships</h3><p className="muted">No insurance claim required — visits are tracked directly against the purchased package.</p></div></header>
    {canManageBilling && (
      <details className="workspace-details" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary>Sell package or membership</summary>
        <form className="stack-form" onSubmit={create}>
          <div className="field-grid">
            <label>Type
              <select value={draft.kind} onChange={(event) => setDraft({ ...draft, kind: event.target.value })}>
                <option value="package">Visit Package</option>
                <option value="membership">Membership</option>
              </select>
            </label>
            <label>Name<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} required /></label>
            <label>Price<input type="number" step="0.01" min="0.01" value={draft.price} onChange={(event) => setDraft({ ...draft, price: event.target.value })} required /></label>
            {draft.kind === "package" && <label>Visits included<input type="number" min="1" value={draft.visitsIncluded} onChange={(event) => setDraft({ ...draft, visitsIncluded: event.target.value })} required /></label>}
            <label>Discount % (optional)<input type="number" step="0.01" min="0" max="100" value={draft.discountPercent} onChange={(event) => setDraft({ ...draft, discountPercent: event.target.value })} /></label>
            <label>Expires (optional)<input type="date" value={draft.expiresAt} onChange={(event) => setDraft({ ...draft, expiresAt: event.target.value })} /></label>
          </div>
          <button className="primary-button" type="submit" disabled={busy === "create"}>{busy === "create" ? "Saving..." : "Sell package"}</button>
        </form>
      </details>
    )}
    {error && <p className="form-error" role="alert">{error}</p>}
    {packages.length ? (
      <ul className="record-list">
        {packages.map((cashPackage) => (
          <li key={cashPackage.id}>
            <span>
              <strong>{cashPackage.name} · {cashPackage.kindLabel}</strong>
              <small>
                ${cashPackage.price}{cashPackage.visitsIncluded !== null ? ` · ${cashPackage.visitsRemaining} of ${cashPackage.visitsIncluded} visits remaining` : " · Unlimited visits"}
                {" "}· Purchased {formatDate(cashPackage.purchasedOn)}{cashPackage.expiresAt && ` · Expires ${formatDate(cashPackage.expiresAt)}`}
              </small>
              {canManageBilling && cashPackage.status === "active" && (
                <div className="button-row" style={{ marginTop: ".3rem" }}>
                  {cashPackage.visitsIncluded !== null && (
                    <button className="text-action" disabled={busy === `visit-${cashPackage.id}` || cashPackage.visitsRemaining === 0} onClick={() => void recordVisit(cashPackage.id)}>
                      {busy === `visit-${cashPackage.id}` ? "Recording..." : "Record visit"}
                    </button>
                  )}
                  <button className="text-action" disabled={busy === `cancel-${cashPackage.id}`} onClick={() => void cancel(cashPackage.id)}>
                    {busy === `cancel-${cashPackage.id}` ? "Cancelling..." : "Cancel"}
                  </button>
                </div>
              )}
            </span>
            <span className={`status-pill ${cashPackage.isActive ? "active" : "inactive"}`}>{cashPackage.statusLabel}</span>
          </li>
        ))}
      </ul>
    ) : <p className="empty-copy">No packages or memberships sold to this patient.</p>}
  </article>;
}

function ScheduleCreatePanel({ patientId, staff, appointments, episodes, authorizations, refresh, report }: { patientId: string; staff: NonNullable<NonNullable<PatientWorkspaceData["operations"]>["schedulingStaff"]>; appointments: NonNullable<NonNullable<PatientWorkspaceData["operations"]>["appointments"]>; episodes: NonNullable<PatientWorkspaceData["clinical"]>["episodesOfCare"]; authorizations: NonNullable<NonNullable<PatientWorkspaceData["operations"]>["authorizations"]>; refresh: () => Promise<void>; report: (message: string) => void }) {
  const defaultStart = useMemo(() => `${dateInputValue()}T09:00`, []);
  const defaultEnd = useMemo(() => `${dateInputValue()}T10:00`, []);
  const [therapistId, setTherapistId] = useState("");
  const [startsAt, setStartsAt] = useState(defaultStart);
  const [endsAt, setEndsAt] = useState(defaultEnd);
  const [kind, setKind] = useState("follow_up");
  const [location, setLocation] = useState("");
  const [isHomeVisit, setIsHomeVisit] = useState(false);
  const [episodeOfCareId, setEpisodeOfCareId] = useState("");
  const [authorizationId, setAuthorizationId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (!therapistId && staff.length) setTherapistId(staff[0].id); }, [staff, therapistId]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const body: Record<string, unknown> = { therapistId, startsAt: new Date(startsAt).toISOString(), endsAt: new Date(endsAt).toISOString(), kind, location, isHomeVisit };
      if (episodeOfCareId) body.episodeOfCareId = episodeOfCareId;
      if (authorizationId) body.authorizationId = authorizationId;
      await api.createAppointment(patientId, body);
      await refresh(); report("Appointment scheduled with a server-side clinician-overlap check.");
    } catch (requestError) { setError(requestMessage(requestError, "Unable to schedule the appointment.")); }
    finally { setBusy(false); }
  }
  return <article className="surface-card workspace-wide-card">
    <header className="card-heading"><div><p className="eyebrow">Scheduling</p><h3>Schedule a patient visit</h3><p className="muted">Existing calendar moves remain locked when a visit is documented, non-scheduled, or conflicts with the clinician calendar.</p></div></header>
    <details className="workspace-details"><summary>Create appointment</summary><form className="stack-form" onSubmit={create}><label>Clinician<select value={therapistId} onChange={(event) => setTherapistId(event.target.value)} required><option value="" disabled>Select clinician</option>{staff.map((user) => <option value={user.id} key={user.id}>{user.displayName} · {user.roleLabel}</option>)}</select></label><div className="field-grid"><label>Start<input type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} required /></label><label>End<input type="datetime-local" value={endsAt} onChange={(event) => setEndsAt(event.target.value)} required /></label><label>Visit type<select value={kind} onChange={(event) => setKind(event.target.value)}><option value="evaluation">Initial evaluation</option><option value="follow_up">Follow-up visit</option><option value="progress">Progress visit</option><option value="discharge">Discharge visit</option><option value="telehealth">Telehealth</option></select></label><label>Location<input value={location} onChange={(event) => setLocation(event.target.value)} placeholder="Clinic, home, or telehealth" /></label></div>
      {(episodes.length > 0 || authorizations.length > 0) && (
        <div className="field-grid">
          {episodes.length > 0 && <label>Episode of care (optional)<select value={episodeOfCareId} onChange={(event) => setEpisodeOfCareId(event.target.value)}><option value="">Not linked</option>{episodes.map((episode) => <option value={episode.id} key={episode.id}>{episode.diagnosis || "Episode of care"} · {episode.statusLabel}</option>)}</select></label>}
          {authorizations.length > 0 && <label>Authorization (optional)<select value={authorizationId} onChange={(event) => setAuthorizationId(event.target.value)}><option value="">Not linked</option>{authorizations.map((authorization) => <option value={authorization.id} key={authorization.id}>{authorization.insuranceName || "Authorization"} · {authorization.visitsRemaining} remaining</option>)}</select></label>}
        </div>
      )}
      <label className="check-label"><input type="checkbox" checked={isHomeVisit} onChange={(event) => setIsHomeVisit(event.target.checked)} /> Home visit</label><button className="primary-button" type="submit" disabled={busy}>{busy ? "Scheduling..." : "Schedule visit"}</button></form></details>
    {error && <p className="form-error" role="alert">{error}</p>}
    {appointments.length ? <ul className="record-list">{appointments.slice(0, 8).map((appointment) => <li key={appointment.id}><span><strong>{formatDate(appointment.date)} · {formatTime(appointment.startsAt)}</strong><small>{appointment.kindLabel} · {appointment.therapist.displayName} · {appointment.isHomeVisit ? "Home visit" : appointment.location || "Location pending"}</small></span><span className={`status-pill ${appointment.status}`}>{appointment.statusLabel}</span></li>)}</ul> : <p className="empty-copy">No visits are scheduled for this patient.</p>}
  </article>;
}

function FormSubmissionAnswers({ patientId, submissionId }: { patientId: string; submissionId: string }) {
  const [detail, setDetail] = useState<FormSubmissionDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api.formSubmissionDetail(patientId, submissionId)
      .then((result) => active && setDetail(result.submission))
      .catch((requestError) => active && setError(requestMessage(requestError, "Unable to load this submission.")));
    return () => { active = false; };
  }, [patientId, submissionId]);

  if (error) return <p className="form-error" role="alert">{error}</p>;
  if (!detail) return <p className="empty-copy">Loading...</p>;

  return (
    <div className="compact-subsection">
      {detail.signatureName && <p><strong>Signed by:</strong> {detail.signatureName}{detail.signedAt ? ` on ${formatDate(detail.signedAt)}` : ""}</p>}
      {detail.schema.map((section) => (
        <div key={section.key} style={{ marginBottom: ".75rem" }}>
          <strong>{section.label}</strong>
          <ul className="summary-list">
            {section.fields.map((field) => {
              const value = detail.data[field.key];
              const display = field.type === "checkbox" ? (value ? "Yes" : "No") : value ? String(value) : "—";
              return <li key={field.key}><small>{field.label}</small>{display}</li>;
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

function IntakeConsentPanel({ patientId, consents, intakes, formSubmissions, refresh, report }: { patientId: string; consents: NonNullable<PatientWorkspaceData["operations"]>["consents"]; intakes: NonNullable<PatientWorkspaceData["operations"]>["intakes"]; formSubmissions: FormSubmissionSummary[]; refresh: () => Promise<void>; report: (message: string) => void }) {
  const [expandedFormId, setExpandedFormId] = useState<string | null>(null);
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
    <div className="compact-subsection">
      <strong>Patient-submitted digital forms</strong>
      {formSubmissions.length ? (
        <ul className="summary-list">
          {formSubmissions.map((submission) => (
            <li key={submission.id}>
              <span>
                <strong>{submission.templateName}</strong>
                <small>{submission.statusLabel} · {submission.submittedAt ? formatDate(submission.submittedAt) : "Not submitted"}</small>
              </span>
              {submission.status === "completed" && (
                <button className="text-action" onClick={() => setExpandedFormId(expandedFormId === submission.id ? null : submission.id)}>
                  {expandedFormId === submission.id ? "Hide" : "View answers"}
                </button>
              )}
              {expandedFormId === submission.id && <FormSubmissionAnswers patientId={patientId} submissionId={submission.id} />}
            </li>
          ))}
        </ul>
      ) : <p className="empty-copy">No digital forms submitted through the portal yet.</p>}
    </div>
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

const MESSAGE_CATEGORIES: [string, string][] = [
  ["general", "General"],
  ["appointment", "Appointment"],
  ["hep", "Home exercise program"],
  ["billing", "Billing"],
  ["clinical", "Clinical"],
];

function MessagePanel({ patientId, recipients, messages, refresh, report }: { patientId: string; recipients: NonNullable<PatientWorkspaceData["operations"]>["recipients"]; messages: NonNullable<PatientWorkspaceData["operations"]>["messages"]; refresh: () => Promise<void>; report: (message: string) => void }) {
  const [recipientId, setRecipientId] = useState("");
  const [category, setCategory] = useState("general");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (!recipientId && recipients.length) setRecipientId(recipients[0].id); }, [recipientId, recipients]);
  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try { await api.sendSecureMessage(patientId, { recipientId, category, subject, body }); setSubject(""); setBody(""); await refresh(); report("Secure message sent. The recipient was notified by email (no message content was included)."); }
    catch (requestError) { setError(requestMessage(requestError, "Unable to send secure message.")); }
    finally { setBusy(false); }
  }
  return <article className="surface-card">
    <header className="card-heading"><div><p className="eyebrow">Secure messaging</p><h3>Internal patient thread</h3><p className="muted">Only messages involving your account are returned in this workspace.</p></div></header>
    <details className="workspace-details"><summary>Compose secure message</summary><form className="stack-form" onSubmit={send}><label>Recipient<select value={recipientId} onChange={(event) => setRecipientId(event.target.value)} required><option value="" disabled>Select recipient</option>{recipients.map((recipient) => <option key={recipient.id} value={recipient.id}>{recipient.displayName} · {recipient.roleLabel}</option>)}</select></label><label>Category<select value={category} onChange={(event) => setCategory(event.target.value)}>{MESSAGE_CATEGORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>Subject<input value={subject} onChange={(event) => setSubject(event.target.value)} required /></label><label>Message<textarea rows={4} value={body} onChange={(event) => setBody(event.target.value)} required /></label><button className="primary-button" type="submit" disabled={busy}>{busy ? "Sending..." : "Send secure message"}</button></form></details>
    {error && <p className="form-error" role="alert">{error}</p>}
    {messages.length ? <ul className="message-list">{messages.map((message) => <li key={message.id} className={message.direction}><strong>{message.subject}</strong><small>{message.direction === "outbound" ? `To ${message.recipient}` : `From ${message.sender}`} · {message.categoryLabel} · {formatDate(message.createdAt)}</small><p>{message.body}</p></li>)}</ul> : <p className="empty-copy">No messages involving your account.</p>}
  </article>;
}

function BillingPanel({ patientId, canManageBilling, superbills, payments, refresh, report }: { patientId: string; canManageBilling: boolean; superbills: NonNullable<NonNullable<PatientWorkspaceData["operations"]>["superbills"]>; payments: NonNullable<NonNullable<PatientWorkspaceData["operations"]>["payments"]>; refresh: () => Promise<void>; report: (message: string) => void }) {
  const [superbill, setSuperbill] = useState({ serviceDate: dateInputValue(), codes: "", amount: "", status: "draft", paymentProcessorReference: "" });
  const [payment, setPayment] = useState({ superbillId: "", amount: "", receivedOn: dateInputValue(), status: "pending", paymentProcessorReference: "" });
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [viewingSuperbill, setViewingSuperbill] = useState<PatientSuperbillData | null>(null);
  async function viewSuperbill(superbillId: string) {
    setBusy(`view-${superbillId}`); setError("");
    try {
      const result = await api.superbillData(patientId, superbillId);
      setViewingSuperbill(result.superbill);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load this superbill."));
    } finally {
      setBusy("");
    }
  }
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
      {canManageBilling && <div><strong>Superbills</strong>{superbills.length ? <ul className="summary-list">{superbills.map((item) => <li key={item.id}><strong>{formatDate(item.serviceDate)} · ${item.amount.toFixed(2)}</strong><small>{item.codes.join(", ")} · {item.statusLabel}</small> <button className="text-action" disabled={busy === `view-${item.id}`} onClick={() => void viewSuperbill(item.id)}>{busy === `view-${item.id}` ? "Loading..." : "View"}</button></li>)}</ul> : <p className="empty-copy">No superbills.</p>}</div>}
      <div><strong>Payment records</strong>{payments.length ? <ul className="summary-list">{payments.map((item) => <li key={item.id}><strong>{formatDate(item.receivedOn)} · ${item.amount.toFixed(2)}</strong><small>{item.statusLabel} · recorded by {item.recordedBy}</small></li>)}</ul> : <p className="empty-copy">No payment records.</p>}</div>
    </div>
    {viewingSuperbill && (
      <div className="modal-backdrop" onClick={() => setViewingSuperbill(null)}>
        <section className="move-dialog client-dialog" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
          <button className="dialog-close" onClick={() => setViewingSuperbill(null)} aria-label="Close">&times;</button>
          <p className="eyebrow">{viewingSuperbill.practice.name}</p>
          <h2>Superbill — {formatDate(viewingSuperbill.serviceDate)}</h2>
          <p className="muted">{viewingSuperbill.patient.fullName} · Provider: {viewingSuperbill.provider.name}</p>
          <p className="muted">Diagnosis: {viewingSuperbill.diagnosisCodes.length ? viewingSuperbill.diagnosisCodes.join(", ") : viewingSuperbill.diagnosisText || "Not documented"}</p>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Date</th><th>CPT</th><th>Units</th><th>Diagnosis</th><th>Amount</th></tr></thead>
              <tbody>
                {viewingSuperbill.lines.map((line, index) => (
                  <tr key={index}><td>{formatDate(line.serviceDate)}</td><td>{line.cptCode}</td><td>{line.units ?? "—"}</td><td>{line.diagnosisCodes.join(", ") || "—"}</td><td>{line.chargeAmount ? `$${line.chargeAmount}` : "—"}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p><strong>Total: ${viewingSuperbill.totalAmount}</strong></p>
        </section>
      </div>
    )}
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
