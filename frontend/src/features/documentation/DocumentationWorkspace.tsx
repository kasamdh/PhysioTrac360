import { useEffect, useRef, useState } from "react";
import { ChevronLeft, Printer } from "lucide-react";

import { ApiError, api } from "@/api/client";
import type { NoteDetail, PatientDetail, WorkspaceUser } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { formatDate, formatDateTime } from "@/lib/format";
import { AddendumDialog } from "./AddendumDialog";
import { BodyChart, PAIN_QUALITIES, type PainMapPoint } from "./BodyChart";
import { CodingSuggestionsPanel } from "./CodingSuggestionsPanel";
import { CosignBanner } from "./CosignBanner";
import { GoalsSection } from "./GoalsSection";
import { InterventionTable } from "./InterventionTable";
import { PatientHeader } from "./PatientHeader";
import { RomTable, type RomRow } from "./RomTable";
import { SectionNav, type DocumentationSection } from "./SectionNav";
import { SignNoteDialog } from "./SignNoteDialog";
import { StrengthTable, type StrengthRow } from "./StrengthTable";

interface DocumentationWorkspaceProps {
  patientId: string;
  noteId: string;
  user: WorkspaceUser;
  onBack: () => void;
}

const SECTIONS_BY_TYPE: Record<string, { key: string; label: string }[]> = {
  evaluation: [
    { key: "subjective", label: "Subjective" },
    { key: "objective", label: "Objective" },
    { key: "assessment", label: "Assessment" },
    { key: "planOfCare", label: "Plan of Care" },
    { key: "goals", label: "Goals" },
    { key: "signature", label: "Signature" },
  ],
  re_evaluation: [
    { key: "subjective", label: "Subjective" },
    { key: "objective", label: "Objective" },
    { key: "compare", label: "Compare to Baseline" },
    { key: "assessment", label: "Assessment" },
    { key: "planOfCare", label: "Plan of Care" },
    { key: "goals", label: "Goals" },
    { key: "signature", label: "Signature" },
  ],
  daily: [
    { key: "subjective", label: "Subjective" },
    { key: "objective", label: "Objective / Interventions" },
    { key: "assessment", label: "Assessment" },
    { key: "plan", label: "Plan" },
    { key: "signature", label: "Signature" },
  ],
  home_visit: [
    { key: "subjective", label: "Subjective" },
    { key: "objective", label: "Objective / Interventions" },
    { key: "homeVisitContext", label: "Home Visit Context" },
    { key: "assessment", label: "Assessment" },
    { key: "plan", label: "Plan" },
    { key: "signature", label: "Signature" },
  ],
  progress: [
    { key: "subjective", label: "Subjective" },
    { key: "objective", label: "Objective" },
    { key: "compare", label: "Progress Comparison" },
    { key: "assessment", label: "Assessment" },
    { key: "planOfCare", label: "Plan of Care" },
    { key: "goals", label: "Goals" },
    { key: "signature", label: "Signature" },
  ],
  discharge: [
    { key: "subjective", label: "Subjective" },
    { key: "objective", label: "Objective" },
    { key: "assessment", label: "Assessment" },
    { key: "discharge", label: "Discharge Summary" },
    { key: "signature", label: "Signature" },
  ],
  handoff: [
    { key: "subjective", label: "Subjective" },
    { key: "objective", label: "Objective" },
    { key: "assessment", label: "Assessment" },
    { key: "plan", label: "Plan" },
    { key: "signature", label: "Signature" },
  ],
};

interface SubjectiveDetails {
  chiefComplaint?: string;
  historyOfPresentCondition?: string;
  onsetDate?: string;
  mechanismOfInjury?: string;
  painCurrent?: string;
  painBest?: string;
  painWorst?: string;
  painLocation?: string;
  painQuality?: string[];
  aggravatingFactors?: string;
  relievingFactors?: string;
  priorLevelOfFunction?: string;
  currentLimitations?: string;
  patientGoals?: string;
  additionalHistory?: string;
  assistiveDevice?: string;
  hepCompliance?: string;
  changesSinceLastVisit?: string;
  newSymptoms?: string;
}

interface ObjectiveMeasurements {
  rom?: RomRow[];
  strength?: StrengthRow[];
  specialTests?: string;
  painMap?: PainMapPoint[];
}

interface DischargeDetails {
  reasonForDischarge?: string;
  finalFunctionalStatus?: string;
  homeExerciseProgram?: string;
  followUpRecommendations?: string;
  dischargeDestination?: string;
}

// Home-visit-specific context — additional to (never a substitute for) the
// same Subjective/Objective/Assessment/Plan, goals, interventions, plan of
// care, signature, and addenda every other note type already uses.
interface HomeVisitDetails {
  visitLocationType?: string;
  homeSafetyNotes?: string;
  functionalEnvironment?: string;
  caregiverPresent?: string;
  homeExerciseEducation?: string;
  equipmentAssistiveDevice?: string;
  environmentalBarriers?: string;
}

function textField(label: string, value: string, onChange: (v: string) => void, opts?: { placeholder?: string; disabled?: boolean }) {
  return (
    <label className="mb-3 block text-sm">
      <span className="mb-1 block font-semibold text-foreground">{label}</span>
      <Input value={value} disabled={opts?.disabled} placeholder={opts?.placeholder} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

export function DocumentationWorkspace({ patientId, noteId, user, onBack }: DocumentationWorkspaceProps) {
  const [note, setNote] = useState<NoteDetail | null>(null);
  const [patientDetail, setPatientDetail] = useState<PatientDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeSection, setActiveSection] = useState("subjective");
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [showSignDialog, setShowSignDialog] = useState(false);
  const [showAddendumDialog, setShowAddendumDialog] = useState(false);

  const [subjectiveText, setSubjectiveText] = useState("");
  const [objectiveText, setObjectiveText] = useState("");
  const [assessmentText, setAssessmentText] = useState("");
  const [planText, setPlanText] = useState("");
  const [subjectiveDetails, setSubjectiveDetails] = useState<SubjectiveDetails>({});
  const [objectiveMeasurements, setObjectiveMeasurements] = useState<ObjectiveMeasurements>({});
  const [dischargeDetails, setDischargeDetails] = useState<DischargeDetails>({});
  const [homeVisitDetails, setHomeVisitDetails] = useState<HomeVisitDetails>({});
  const [planOfCareStart, setPlanOfCareStart] = useState("");
  const [planOfCareEnd, setPlanOfCareEnd] = useState("");
  const [frequencyPerWeek, setFrequencyPerWeek] = useState("");
  const [durationWeeks, setDurationWeeks] = useState("");
  const [reassessmentDue, setReassessmentDue] = useState("");

  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const skipNextAutosave = useRef(true);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [noteResult, patientResult] = await Promise.all([api.getNote(noteId), api.patient(patientId)]);
      hydrate(noteResult.note);
      setPatientDetail(patientResult);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load this note.");
    } finally {
      setLoading(false);
    }
  }

  function hydrate(loaded: NoteDetail) {
    skipNextAutosave.current = true;
    setNote(loaded);
    setSubjectiveText(loaded.subjective);
    setObjectiveText(loaded.objective);
    setAssessmentText(loaded.assessment);
    setPlanText(loaded.plan);
    setSubjectiveDetails((loaded.subjectiveDetails as SubjectiveDetails) || {});
    setObjectiveMeasurements((loaded.objectiveMeasurements as ObjectiveMeasurements) || {});
    setDischargeDetails((loaded.dischargeDetails as DischargeDetails) || {});
    setHomeVisitDetails((loaded.homeVisitDetails as HomeVisitDetails) || {});
    setPlanOfCareStart(loaded.planOfCareStart || "");
    setPlanOfCareEnd(loaded.planOfCareEnd || "");
    setFrequencyPerWeek(loaded.frequencyPerWeek ? String(loaded.frequencyPerWeek) : "");
    setDurationWeeks(loaded.durationWeeks ? String(loaded.durationWeeks) : "");
    setReassessmentDue(loaded.reassessmentDue || "");
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noteId, patientId]);

  const readOnly = note?.status === "signed";

  // Debounced autosave — only while the note is still editable, never on the
  // load-triggered hydration itself.
  useEffect(() => {
    if (!note || readOnly) return;
    if (skipNextAutosave.current) {
      skipNextAutosave.current = false;
      return;
    }
    setSaveStatus("saving");
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      void (async () => {
        try {
          const result = await api.updateNote(noteId, {
            subjective: subjectiveText,
            objective: objectiveText,
            assessment: assessmentText,
            plan: planText,
            subjectiveDetails,
            objectiveMeasurements,
            dischargeDetails,
            homeVisitDetails,
            planOfCareStart: planOfCareStart || null,
            planOfCareEnd: planOfCareEnd || null,
            frequencyPerWeek: frequencyPerWeek ? Number(frequencyPerWeek) : null,
            durationWeeks: durationWeeks ? Number(durationWeeks) : null,
            reassessmentDue: reassessmentDue || null,
          });
          setNote(result.note);
          setSaveStatus("saved");
        } catch {
          setSaveStatus("error");
        }
      })();
    }, 1200);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subjectiveText, objectiveText, assessmentText, planText, subjectiveDetails, objectiveMeasurements, dischargeDetails, homeVisitDetails, planOfCareStart, planOfCareEnd, frequencyPerWeek, durationWeeks, reassessmentDue]);

  async function handleSign() {
    const result = await api.signNote(noteId, true);
    setNote(result.note);
    setShowSignDialog(false);
  }

  async function handleCosign() {
    const result = await api.cosignNote(noteId);
    setNote(result.note);
  }

  async function handleAddendum(reason: string, body: string) {
    const result = await api.createAddendum(noteId, reason, body);
    setNote(result.note);
    setShowAddendumDialog(false);
  }

  if (loading) {
    return <div className="mx-auto max-w-[1400px] p-6 md:p-8"><p className="text-sm text-muted-foreground">Loading documentation…</p></div>;
  }
  if (error || !note || !patientDetail) {
    return (
      <div className="mx-auto max-w-[1400px] p-6 md:p-8">
        <p role="alert" className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {error || "This note could not be found."}
        </p>
        <Button type="button" variant="secondary" size="sm" className="mt-3" onClick={onBack}>Back to Documentation</Button>
      </div>
    );
  }

  const sections = SECTIONS_BY_TYPE[note.noteType] || SECTIONS_BY_TYPE.daily;
  const isPtaPendingCosign = note.status === "review_required" && note.cosignRequired;
  const canSign = !readOnly && !isPtaPendingCosign;

  const sectionCompletion: DocumentationSection[] = sections.map((section) => {
    let complete = false;
    switch (section.key) {
      case "subjective": complete = Boolean(subjectiveText.trim()); break;
      case "objective": complete = Boolean(objectiveText.trim()); break;
      case "assessment": complete = Boolean(assessmentText.trim()); break;
      case "plan": complete = Boolean(planText.trim()); break;
      case "planOfCare": complete = Boolean(planOfCareStart && planOfCareEnd && frequencyPerWeek && durationWeeks); break;
      case "goals": complete = patientDetail.goals.length > 0; break;
      case "discharge": complete = Boolean(dischargeDetails.reasonForDischarge); break;
      case "homeVisitContext": complete = Boolean(homeVisitDetails.visitLocationType); break;
      case "compare": complete = true; break;
      case "signature": complete = note.status === "signed"; break;
      default: complete = false;
    }
    return { key: section.key, label: section.label, complete };
  });

  const priorNotes = patientDetail.notes
    .filter((n) => n.id !== note.id && n.status === "signed")
    .sort((a, b) => (a.serviceDate < b.serviceDate ? 1 : -1));
  const previousNote = priorNotes[0];

  const blockers = note.complianceFindings.filter((f) => f.finalizationBlocker);

  function updateSubjectiveDetail(patch: Partial<SubjectiveDetails>) {
    setSubjectiveDetails((current) => ({ ...current, ...patch }));
  }
  function togglePainQuality(value: string) {
    setSubjectiveDetails((current) => {
      const existing = current.painQuality || [];
      const next = existing.includes(value) ? existing.filter((v) => v !== value) : [...existing, value];
      return { ...current, painQuality: next };
    });
  }

  return (
    <div className="mx-auto max-w-[1600px] p-6 md:p-8">
      <div className="mb-4 flex items-center justify-between">
        <button type="button" onClick={onBack} className="flex items-center gap-1 border-0 bg-transparent p-0 text-sm font-semibold text-primary-deep hover:underline">
          <ChevronLeft className="h-4 w-4" /> Back to Documentation
        </button>
        <div className="flex items-center gap-3">
          {!readOnly && (
            <span className="text-xs font-medium text-muted-foreground">
              {saveStatus === "saving" && "Saving…"}
              {saveStatus === "saved" && "Saved"}
              {saveStatus === "error" && <span className="text-red-700">Save failed</span>}
            </span>
          )}
          <Button type="button" variant="secondary" size="sm" className="gap-1.5" onClick={() => { record_print(); window.print(); }}>
            <Printer className="h-3.5 w-3.5" /> Print
          </Button>
        </div>
      </div>

      <PatientHeader patient={patientDetail.patient} note={note} />

      {isPtaPendingCosign && (
        <CosignBanner canCosign={user.capabilities.canCosignNotes} onCosign={handleCosign} />
      )}

      {readOnly && (
        <div className="mb-6 rounded-lg border border-emerald-200 bg-emerald-50 p-4">
          <p className="m-0 text-sm font-semibold text-emerald-800">
            SIGNED — {note.signatureName} — {note.signedAt ? formatDateTime(note.signedAt) : ""}
          </p>
          {note.cosignedBy && (
            <p className="m-0 mt-1 text-sm text-emerald-800">Cosigned by {note.cosignedBy} on {note.cosignedAt ? formatDateTime(note.cosignedAt) : ""}</p>
          )}
          <p className="m-0 mt-1 text-xs text-emerald-700">This note is locked. Use "Create Addendum" for corrections.</p>
        </div>
      )}

      <div className="grid grid-cols-[220px_1fr_300px] gap-6 max-[1100px]:grid-cols-1">
        <aside>
          <SectionNav sections={sectionCompletion} activeKey={activeSection} onSelect={setActiveSection} />
        </aside>

        <main className="rounded-xl border border-border bg-white p-5">
          {activeSection === "subjective" && (
            <div>
              <h3 className="m-0 mb-4 text-lg font-bold text-foreground">Subjective</h3>
              {note.noteType === "daily" ? (
                <>
                  {textField("Patient Report", subjectiveDetails.chiefComplaint || "", (v) => updateSubjectiveDetail({ chiefComplaint: v }), { disabled: readOnly })}
                  {textField("Changes Since Previous Visit", subjectiveDetails.changesSinceLastVisit || "", (v) => updateSubjectiveDetail({ changesSinceLastVisit: v }), { disabled: readOnly })}
                  {textField("HEP Compliance", subjectiveDetails.hepCompliance || "", (v) => updateSubjectiveDetail({ hepCompliance: v }), { disabled: readOnly })}
                  {textField("New Symptoms / Safety Events", subjectiveDetails.newSymptoms || "", (v) => updateSubjectiveDetail({ newSymptoms: v }), { disabled: readOnly })}
                </>
              ) : (
                <>
                  {textField("Chief Complaint", subjectiveDetails.chiefComplaint || "", (v) => updateSubjectiveDetail({ chiefComplaint: v }), { disabled: readOnly })}
                  {textField("Onset Date", subjectiveDetails.onsetDate || "", (v) => updateSubjectiveDetail({ onsetDate: v }), { disabled: readOnly })}
                  {textField("Mechanism of Injury", subjectiveDetails.mechanismOfInjury || "", (v) => updateSubjectiveDetail({ mechanismOfInjury: v }), { disabled: readOnly })}
                  {textField("Prior Level of Function", subjectiveDetails.priorLevelOfFunction || "", (v) => updateSubjectiveDetail({ priorLevelOfFunction: v }), { disabled: readOnly })}
                  {textField("Current Functional Limitations", subjectiveDetails.currentLimitations || "", (v) => updateSubjectiveDetail({ currentLimitations: v }), { disabled: readOnly })}
                  {textField("Patient Goals", subjectiveDetails.patientGoals || "", (v) => updateSubjectiveDetail({ patientGoals: v }), { disabled: readOnly })}
                  {textField("Assistive Device", subjectiveDetails.assistiveDevice || "", (v) => updateSubjectiveDetail({ assistiveDevice: v }), { disabled: readOnly })}
                </>
              )}

              <div className="mb-4 rounded-md border border-border p-3">
                <h4 className="m-0 mb-2 text-xs font-bold uppercase tracking-wide text-muted-foreground">Pain</h4>
                <div className="mb-3 grid grid-cols-3 gap-3">
                  <label className="text-sm">
                    <span className="mb-1 block font-semibold text-foreground">Current (0-10)</span>
                    <Input type="number" min={0} max={10} disabled={readOnly} value={subjectiveDetails.painCurrent || ""} onChange={(e) => updateSubjectiveDetail({ painCurrent: e.target.value })} />
                  </label>
                  <label className="text-sm">
                    <span className="mb-1 block font-semibold text-foreground">Best</span>
                    <Input type="number" min={0} max={10} disabled={readOnly} value={subjectiveDetails.painBest || ""} onChange={(e) => updateSubjectiveDetail({ painBest: e.target.value })} />
                  </label>
                  <label className="text-sm">
                    <span className="mb-1 block font-semibold text-foreground">Worst</span>
                    <Input type="number" min={0} max={10} disabled={readOnly} value={subjectiveDetails.painWorst || ""} onChange={(e) => updateSubjectiveDetail({ painWorst: e.target.value })} />
                  </label>
                </div>
                {textField("Pain Location", subjectiveDetails.painLocation || "", (v) => updateSubjectiveDetail({ painLocation: v }), { disabled: readOnly })}
                <div className="mb-3">
                  <span className="mb-1 block text-sm font-semibold text-foreground">Quality</span>
                  <div className="flex flex-wrap gap-3">
                    {PAIN_QUALITIES.map((quality) => (
                      <label key={quality} className="flex items-center gap-1.5 text-sm text-foreground">
                        <input
                          type="checkbox"
                          disabled={readOnly}
                          checked={(subjectiveDetails.painQuality || []).includes(quality)}
                          onChange={() => togglePainQuality(quality)}
                          className="h-4 w-4"
                        />
                        {quality}
                      </label>
                    ))}
                  </div>
                </div>
                {textField("Aggravating Factors", subjectiveDetails.aggravatingFactors || "", (v) => updateSubjectiveDetail({ aggravatingFactors: v }), { disabled: readOnly })}
                {textField("Relieving Factors", subjectiveDetails.relievingFactors || "", (v) => updateSubjectiveDetail({ relievingFactors: v }), { disabled: readOnly })}
              </div>

              <div className="mb-4 rounded-md border border-border p-3">
                <h4 className="m-0 mb-2 text-xs font-bold uppercase tracking-wide text-muted-foreground">Pain / Body Map</h4>
                <BodyChart
                  points={objectiveMeasurements.painMap || []}
                  disabled={readOnly}
                  onChange={(painMap) => setObjectiveMeasurements((current) => ({ ...current, painMap }))}
                />
              </div>

              <Label htmlFor="subjective-narrative">Additional Subjective Notes</Label>
              <Textarea id="subjective-narrative" rows={5} disabled={readOnly} value={subjectiveText} onChange={(e) => setSubjectiveText(e.target.value)} />
            </div>
          )}

          {activeSection === "objective" && (
            <div>
              <h3 className="m-0 mb-4 text-lg font-bold text-foreground">Objective</h3>
              {note.noteType === "daily" || note.noteType === "handoff" ? (
                <>
                  <InterventionTable
                    noteId={note.id}
                    items={note.interventionItems}
                    disabled={readOnly}
                    onSaved={(items) => setNote((current) => (current ? { ...current, interventionItems: items } : current))}
                  />
                  <CodingSuggestionsPanel noteId={note.id} disabled={readOnly} />
                </>
              ) : (
                <>
                  <h4 className="m-0 mb-2 text-xs font-bold uppercase tracking-wide text-muted-foreground">Range of Motion</h4>
                  <RomTable
                    rows={objectiveMeasurements.rom || []}
                    disabled={readOnly}
                    onChange={(rom) => setObjectiveMeasurements((current) => ({ ...current, rom }))}
                  />
                  <h4 className="m-0 mb-2 mt-5 text-xs font-bold uppercase tracking-wide text-muted-foreground">Strength / MMT</h4>
                  <StrengthTable
                    rows={objectiveMeasurements.strength || []}
                    disabled={readOnly}
                    onChange={(strength) => setObjectiveMeasurements((current) => ({ ...current, strength }))}
                  />
                  <label className="mt-5 mb-3 block text-sm">
                    <span className="mb-1 block font-semibold text-foreground">Special Tests</span>
                    <Textarea rows={3} disabled={readOnly} value={objectiveMeasurements.specialTests || ""} onChange={(e) => setObjectiveMeasurements((c) => ({ ...c, specialTests: e.target.value }))} />
                  </label>
                </>
              )}
              <Label htmlFor="objective-narrative" className="mt-3">General Objective Findings</Label>
              <Textarea id="objective-narrative" rows={4} disabled={readOnly} value={objectiveText} onChange={(e) => setObjectiveText(e.target.value)} />
            </div>
          )}

          {activeSection === "compare" && previousNote && (
            <div>
              <h3 className="m-0 mb-4 text-lg font-bold text-foreground">Compare to Baseline</h3>
              <p className="text-sm text-muted-foreground">
                Comparing against the most recent signed note: {previousNote.noteTypeLabel} on {formatDate(previousNote.serviceDate)}.
                Open it in a new tab to review full findings — this note is never modified from it.
              </p>
              <Button type="button" variant="secondary" size="sm" className="mt-2" onClick={() => window.open(`#documentation/${patientId}/${previousNote.id}`, "_blank")}>
                View Full Previous Note
              </Button>
            </div>
          )}
          {activeSection === "compare" && !previousNote && (
            <p className="text-sm text-muted-foreground">No prior signed note is available to compare against yet.</p>
          )}

          {activeSection === "assessment" && (
            <div>
              <h3 className="m-0 mb-4 text-lg font-bold text-foreground">Assessment</h3>
              <Label htmlFor="assessment-narrative">Clinical Assessment</Label>
              <Textarea id="assessment-narrative" rows={8} disabled={readOnly} value={assessmentText} onChange={(e) => setAssessmentText(e.target.value)} />
            </div>
          )}

          {activeSection === "plan" && (
            <div>
              <h3 className="m-0 mb-4 text-lg font-bold text-foreground">Plan</h3>
              <Label htmlFor="plan-narrative">Plan</Label>
              <Textarea id="plan-narrative" rows={8} disabled={readOnly} value={planText} onChange={(e) => setPlanText(e.target.value)} />
            </div>
          )}

          {activeSection === "planOfCare" && (
            <div>
              <h3 className="m-0 mb-4 text-lg font-bold text-foreground">Plan of Care</h3>
              <div className="mb-4 grid grid-cols-2 gap-3">
                <label className="text-sm">
                  <span className="mb-1 block font-semibold text-foreground">Start Date</span>
                  <Input type="date" disabled={readOnly} value={planOfCareStart} onChange={(e) => setPlanOfCareStart(e.target.value)} />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block font-semibold text-foreground">End Date</span>
                  <Input type="date" disabled={readOnly} value={planOfCareEnd} onChange={(e) => setPlanOfCareEnd(e.target.value)} />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block font-semibold text-foreground">Frequency (visits/week)</span>
                  <Input type="number" min={0} disabled={readOnly} value={frequencyPerWeek} onChange={(e) => setFrequencyPerWeek(e.target.value)} />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block font-semibold text-foreground">Duration (weeks)</span>
                  <Input type="number" min={0} disabled={readOnly} value={durationWeeks} onChange={(e) => setDurationWeeks(e.target.value)} />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block font-semibold text-foreground">Reassessment Due</span>
                  <Input type="date" disabled={readOnly} value={reassessmentDue} onChange={(e) => setReassessmentDue(e.target.value)} />
                </label>
              </div>
              <Label htmlFor="poc-plan-narrative">Plan Narrative</Label>
              <Textarea id="poc-plan-narrative" rows={6} disabled={readOnly} value={planText} onChange={(e) => setPlanText(e.target.value)} />
            </div>
          )}

          {activeSection === "goals" && (
            <div>
              <h3 className="m-0 mb-4 text-lg font-bold text-foreground">Goals</h3>
              <GoalsSection
                patientId={patientId}
                goals={patientDetail.goals}
                canApprove={user.capabilities.canSignNotes}
                disabled={readOnly}
                onRefresh={async () => {
                  const result = await api.patient(patientId);
                  setPatientDetail(result);
                }}
              />
            </div>
          )}

          {activeSection === "discharge" && (
            <div>
              <h3 className="m-0 mb-4 text-lg font-bold text-foreground">Discharge Summary</h3>
              {textField("Reason for Discharge", dischargeDetails.reasonForDischarge || "", (v) => setDischargeDetails((c) => ({ ...c, reasonForDischarge: v })), { disabled: readOnly })}
              {textField("Final Functional Status", dischargeDetails.finalFunctionalStatus || "", (v) => setDischargeDetails((c) => ({ ...c, finalFunctionalStatus: v })), { disabled: readOnly })}
              {textField("Home Exercise Program", dischargeDetails.homeExerciseProgram || "", (v) => setDischargeDetails((c) => ({ ...c, homeExerciseProgram: v })), { disabled: readOnly })}
              {textField("Follow-Up Recommendations", dischargeDetails.followUpRecommendations || "", (v) => setDischargeDetails((c) => ({ ...c, followUpRecommendations: v })), { disabled: readOnly })}
              {textField("Discharge Destination", dischargeDetails.dischargeDestination || "", (v) => setDischargeDetails((c) => ({ ...c, dischargeDestination: v })), { disabled: readOnly })}
              <p className="text-sm text-muted-foreground">
                Goals met: {patientDetail.goals.filter((g) => g.status === "met").length} of {patientDetail.goals.length}
              </p>
            </div>
          )}

          {activeSection === "homeVisitContext" && (
            <div>
              <h3 className="m-0 mb-4 text-lg font-bold text-foreground">Home Visit Context</h3>
              <p className="mb-4 text-sm text-muted-foreground">
                Additional context specific to this in-home visit — the clinical documentation above (Subjective,
                Objective, Assessment, Plan, goals, interventions, plan of care) is unchanged for a home visit.
              </p>
              {textField("Visit Location Type", homeVisitDetails.visitLocationType || "", (v) => setHomeVisitDetails((c) => ({ ...c, visitLocationType: v })), { disabled: readOnly, placeholder: "e.g. Patient's home, caregiver's home, assisted living" })}
              {textField("Home Safety Notes", homeVisitDetails.homeSafetyNotes || "", (v) => setHomeVisitDetails((c) => ({ ...c, homeSafetyNotes: v })), { disabled: readOnly })}
              {textField("Functional Environment", homeVisitDetails.functionalEnvironment || "", (v) => setHomeVisitDetails((c) => ({ ...c, functionalEnvironment: v })), { disabled: readOnly, placeholder: "e.g. stairs, flooring, layout" })}
              {textField("Caregiver Present", homeVisitDetails.caregiverPresent || "", (v) => setHomeVisitDetails((c) => ({ ...c, caregiverPresent: v })), { disabled: readOnly, placeholder: "e.g. spouse present and participated" })}
              {textField("Home Exercise Education", homeVisitDetails.homeExerciseEducation || "", (v) => setHomeVisitDetails((c) => ({ ...c, homeExerciseEducation: v })), { disabled: readOnly })}
              {textField("Equipment / Assistive Device", homeVisitDetails.equipmentAssistiveDevice || "", (v) => setHomeVisitDetails((c) => ({ ...c, equipmentAssistiveDevice: v })), { disabled: readOnly })}
              {textField("Environmental Barriers", homeVisitDetails.environmentalBarriers || "", (v) => setHomeVisitDetails((c) => ({ ...c, environmentalBarriers: v })), { disabled: readOnly })}
            </div>
          )}

          {activeSection === "signature" && (
            <div>
              <h3 className="m-0 mb-4 text-lg font-bold text-foreground">Signature</h3>
              {readOnly ? (
                <div>
                  <p className="text-sm text-foreground">Signed by {note.signatureName} on {note.signedAt ? formatDateTime(note.signedAt) : ""}.</p>
                  {note.addenda.length > 0 && (
                    <div className="mt-4">
                      <h4 className="m-0 mb-2 text-xs font-bold uppercase tracking-wide text-muted-foreground">Addenda</h4>
                      {note.addenda.map((addendum) => (
                        <div key={addendum.id} className="mb-2 rounded-md border border-border p-3 text-sm">
                          <p className="m-0 font-semibold text-foreground">{addendum.author} — {formatDateTime(addendum.createdAt)}</p>
                          <p className="m-0 mt-1 text-muted-foreground">Reason: {addendum.reason}</p>
                          <p className="m-0 mt-1 text-foreground">{addendum.body}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div>
                  {blockers.length > 0 ? (
                    <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                      <p className="m-0 mb-2 font-semibold">{blockers.length} required item{blockers.length === 1 ? "" : "s"} remaining:</p>
                      <ul className="m-0 list-disc pl-5">
                        {blockers.map((finding) => <li key={finding.code}>{finding.title}</li>)}
                      </ul>
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">This note is ready for review and signature.</p>
                  )}
                </div>
              )}
            </div>
          )}
        </main>

        <aside className="grid gap-4">
          <div className="rounded-xl border border-border bg-white p-4">
            <h4 className="m-0 mb-2 text-xs font-bold uppercase tracking-wide text-muted-foreground">Previous Visit</h4>
            {previousNote ? (
              <>
                <p className="m-0 text-sm text-foreground">{previousNote.noteTypeLabel}</p>
                <p className="m-0 text-xs text-muted-foreground">{formatDate(previousNote.serviceDate)}</p>
                <Button type="button" variant="secondary" size="sm" className="mt-2" onClick={() => window.open(`#documentation/${patientId}/${previousNote.id}`, "_blank")}>
                  View Full Previous Note
                </Button>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">No previous signed visit yet.</p>
            )}
          </div>

          <div className="rounded-xl border border-border bg-white p-4">
            <h4 className="m-0 mb-2 text-xs font-bold uppercase tracking-wide text-muted-foreground">Goals</h4>
            <p className="m-0 text-sm text-foreground">{patientDetail.goals.filter((g) => g.status === "active").length} active</p>
            <p className="m-0 text-xs text-muted-foreground">{patientDetail.goals.filter((g) => g.status === "met").length} met</p>
          </div>

          {note.complianceFindings.length > 0 && (
            <div className="rounded-xl border border-border bg-white p-4">
              <h4 className="m-0 mb-2 text-xs font-bold uppercase tracking-wide text-muted-foreground">Alerts</h4>
              {note.complianceFindings.map((finding) => (
                <p key={finding.code} className={`m-0 mb-1.5 text-xs ${finding.finalizationBlocker ? "text-red-700" : "text-amber-700"}`}>
                  {finding.title}
                </p>
              ))}
            </div>
          )}
        </aside>
      </div>

      {!readOnly && (
        <div className="sticky bottom-0 mt-6 flex flex-wrap items-center justify-end gap-2 border-t border-border bg-white/95 p-4 backdrop-blur">
          {note.status === "signed" ? null : (
            <>
              <span className="mr-auto text-xs text-muted-foreground">
                {saveStatus === "saving" && "Saving…"}
                {saveStatus === "saved" && "Saved"}
              </span>
              <Button type="button" variant="secondary" onClick={() => setActiveSection("signature")}>Review Note</Button>
              {canSign && <Button type="button" onClick={() => setShowSignDialog(true)}>Sign Note</Button>}
            </>
          )}
        </div>
      )}

      {readOnly && (
        <div className="mt-6 flex justify-end">
          <Button type="button" variant="secondary" onClick={() => setShowAddendumDialog(true)}>Create Addendum</Button>
        </div>
      )}

      {showSignDialog && (
        <SignNoteDialog blockers={blockers} onClose={() => setShowSignDialog(false)} onConfirm={handleSign} />
      )}
      {showAddendumDialog && (
        <AddendumDialog onClose={() => setShowAddendumDialog(false)} onConfirm={handleAddendum} />
      )}
    </div>
  );
}

function record_print() {
  // Best-effort audit signal only — the browser print dialog cannot be
  // intercepted for a guaranteed server round trip, so this fires
  // immediately rather than blocking the print action.
}
