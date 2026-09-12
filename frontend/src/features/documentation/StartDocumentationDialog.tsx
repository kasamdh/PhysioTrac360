import { useEffect, useState } from "react";

import { ApiError, api } from "@/api/client";
import type { EpisodeOfCare, NoteDetail, Patient } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter, FormRow } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

const NOTE_TYPES: { value: string; label: string }[] = [
  { value: "evaluation", label: "Initial Evaluation" },
  { value: "daily", label: "Daily Treatment Note" },
  { value: "soap", label: "SOAP Note" },
  { value: "home_visit", label: "Home Visit Note" },
  { value: "progress", label: "Progress Note" },
  { value: "re_evaluation", label: "Re-evaluation" },
  { value: "discharge", label: "Discharge Summary" },
  { value: "handoff", label: "Handoff Summary" },
];

interface StartDocumentationDialogProps {
  initialPatient?: { id: string; fullName: string } | null;
  appointmentId?: string;
  defaultNoteType?: string;
  onClose: () => void;
  onCreated: (note: NoteDetail) => void;
}

export function StartDocumentationDialog({ initialPatient, appointmentId, defaultNoteType, onClose, onCreated }: StartDocumentationDialogProps) {
  const [patient, setPatient] = useState<{ id: string; fullName: string } | null>(initialPatient ?? null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Patient[]>([]);
  const [searching, setSearching] = useState(false);
  const [noteType, setNoteType] = useState(defaultNoteType || "evaluation");
  const [episodes, setEpisodes] = useState<EpisodeOfCare[]>([]);
  const [episodeOfCareId, setEpisodeOfCareId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setEpisodeOfCareId("");
    if (!patient) {
      setEpisodes([]);
      return;
    }
    let active = true;
    api
      .patientEpisodesOfCare(patient.id)
      .then((result) => active && setEpisodes(result.episodesOfCare))
      .catch(() => active && setEpisodes([]));
    return () => {
      active = false;
    };
  }, [patient]);

  async function search(value: string) {
    setQuery(value);
    if (value.trim().length < 2) {
      setResults([]);
      return;
    }
    setSearching(true);
    try {
      const result = await api.patients(value);
      setResults(result.patients);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }

  async function confirm() {
    if (!patient) return;
    setBusy(true);
    setError("");
    try {
      const body: Record<string, unknown> = { noteType };
      if (appointmentId) body.appointmentId = appointmentId;
      if (episodeOfCareId) body.episodeOfCareId = episodeOfCareId;
      const result = await api.createNote(patient.id, body);
      onCreated(result.note);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to start documentation.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog titleId="start-documentation-title" eyebrow="Documentation" title="Start Documentation" onClose={onClose} busy={busy} maxWidth="max-w-lg">
      {!initialPatient && (
        <FormRow label="Patient" htmlFor="start-doc-patient">
          {patient ? (
            <div className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm">
              <span className="font-medium text-foreground">{patient.fullName}</span>
              <button type="button" onClick={() => setPatient(null)} className="border-0 bg-transparent p-0 text-xs font-semibold text-primary-deep hover:underline">
                Change
              </button>
            </div>
          ) : (
            <div>
              <Input id="start-doc-patient" placeholder="Search by name or MRN" value={query} onChange={(e) => void search(e.target.value)} />
              {searching && <p className="mt-1 text-xs text-muted-foreground">Searching…</p>}
              {results.length > 0 && (
                <div className="mt-1 max-h-40 overflow-y-auto rounded-md border border-border">
                  {results.map((candidate) => (
                    <button
                      key={candidate.id}
                      type="button"
                      onClick={() => { setPatient({ id: candidate.id, fullName: candidate.fullName }); setResults([]); setQuery(""); }}
                      className="block w-full border-0 bg-transparent px-3 py-2 text-left text-sm hover:bg-muted/50"
                    >
                      {candidate.fullName} <span className="text-muted-foreground">· MRN {candidate.medicalRecordNumber}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </FormRow>
      )}

      <FormRow label="Note Type" htmlFor="start-doc-type">
        <Select id="start-doc-type" value={noteType} onChange={(e) => setNoteType(e.target.value)}>
          {NOTE_TYPES.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </Select>
      </FormRow>

      {episodes.length > 0 && (
        <FormRow label="Episode of Care (optional)" htmlFor="start-doc-episode">
          <Select id="start-doc-episode" value={episodeOfCareId} onChange={(e) => setEpisodeOfCareId(e.target.value)}>
            <option value="">Not linked</option>
            {episodes.map((episode) => (
              <option key={episode.id} value={episode.id}>{episode.diagnosis || "Episode of care"} · {episode.statusLabel}</option>
            ))}
          </Select>
        </FormRow>
      )}

      {error && (
        <p role="alert" className="mt-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {error}
        </p>
      )}

      <DialogFooter>
        <Button type="button" variant="secondary" disabled={busy} onClick={onClose}>Cancel</Button>
        <Button type="button" disabled={busy || !patient} onClick={() => void confirm()}>
          {busy ? "Starting..." : "Start Documentation"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
