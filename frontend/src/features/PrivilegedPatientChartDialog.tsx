import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { Patient, PrivilegedPatientDetail } from "../api/types";
import { formatDate } from "../lib/format";

interface PrivilegedPatientChartDialogProps {
  clientNumber: number;
  patient: Patient;
  onClose: () => void;
}

export function PrivilegedPatientChartDialog({ clientNumber, patient, onClose }: PrivilegedPatientChartDialogProps) {
  const [detail, setDetail] = useState<PrivilegedPatientDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api
      .privilegedPatientDetail(clientNumber, patient.id)
      .then((result) => active && setDetail(result))
      .catch((requestError) => active && setError(requestError instanceof ApiError ? requestError.message : "Unable to load this chart."));
    return () => {
      active = false;
    };
  }, [clientNumber, patient.id]);

  return (
    <div className="modal-backdrop">
      <section className="move-dialog client-dialog" role="dialog" aria-modal="true" aria-labelledby="privileged-chart-title">
        <button className="dialog-close" onClick={onClose} aria-label="Close">&times;</button>
        <p className="eyebrow">Privileged access · read-only</p>
        <h2 id="privileged-chart-title">{patient.fullName}</h2>
        {error && <p className="form-error" role="alert">{error}</p>}
        {!detail && !error && <p className="muted">Loading chart...</p>}
        {detail && (
          <>
            <dl className="detail-grid">
              <div><dt>MRN</dt><dd>{detail.patient.medicalRecordNumber}</dd></div>
              <div><dt>Date of birth</dt><dd>{formatDate(detail.patient.dateOfBirth, { month: "short", day: "numeric", year: "numeric" })}</dd></div>
              <div><dt>Status</dt><dd>{detail.patient.statusLabel}</dd></div>
              <div><dt>Assigned therapist</dt><dd>{detail.patient.assignedTherapist?.displayName || "Not assigned"}</dd></div>
              <div><dt>Diagnoses</dt><dd>{detail.patient.diagnoses || "None recorded"}</dd></div>
              <div><dt>Precautions</dt><dd>{detail.patient.precautions || "None recorded"}</dd></div>
            </dl>

            <h3>Notes ({detail.notes.length})</h3>
            {detail.notes.length ? (
              <div className="table-wrap"><table><thead><tr><th>Date</th><th>Type</th><th>Status</th></tr></thead><tbody>
                {detail.notes.map((note) => <tr key={note.id}><td>{formatDate(note.serviceDate, { month: "short", day: "numeric", year: "numeric" })}</td><td>{note.noteTypeLabel}</td><td>{note.statusLabel}</td></tr>)}
              </tbody></table></div>
            ) : <p className="empty-copy">No notes recorded.</p>}

            <h3>Appointments ({detail.appointments.length})</h3>
            {detail.appointments.length ? (
              <div className="table-wrap"><table><thead><tr><th>Date</th><th>Kind</th><th>Status</th><th>Therapist</th></tr></thead><tbody>
                {detail.appointments.map((appointment) => <tr key={appointment.id}><td>{formatDate(appointment.startsAt, { month: "short", day: "numeric", year: "numeric" })}</td><td>{appointment.kindLabel}</td><td>{appointment.statusLabel}</td><td>{appointment.therapist.displayName}</td></tr>)}
              </tbody></table></div>
            ) : <p className="empty-copy">No appointments recorded.</p>}

            <h3>Goals ({detail.goals.length})</h3>
            {detail.goals.length ? (
              <ul>{detail.goals.map((goal) => <li key={goal.id}>{goal.functionalTask} — {goal.statusLabel}{goal.progressPercent !== null ? ` (${goal.progressPercent}%)` : ""}</li>)}</ul>
            ) : <p className="empty-copy">No goals recorded.</p>}

            <p className="muted">
              Viewing this chart was recorded to the audit log under your active privileged-access
              grant ({detail.grant.reason}).
            </p>
          </>
        )}
      </section>
    </div>
  );
}
