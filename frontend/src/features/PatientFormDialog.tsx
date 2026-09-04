import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { Patient, StaffOption } from "../api/types";

interface PatientFormDialogProps {
  /** When set, the dialog fetches this patient's full editable fields (including
   * contact info) itself — the caller never needs to pre-load that data, since
   * the clinical workspace and patient list deliberately don't carry it. */
  patientId?: string;
  canEditClinicalFields: boolean;
  onClose: () => void;
  onSave: (body: Record<string, unknown>) => Promise<unknown>;
  onSaved: () => Promise<void>;
}

const STATUSES = [
  ["active", "Active"],
  ["inactive", "Inactive"],
  ["discharged", "Discharged"],
] as const;

const emptyForm = {
  firstName: "",
  lastName: "",
  dateOfBirth: "",
  phone: "",
  email: "",
  address: "",
  emergencyContact: "",
  status: "active",
  assignedTherapistId: "",
  diagnoses: "",
  precautions: "",
};

export function PatientFormDialog({ patientId, canEditClinicalFields, onClose, onSave, onSaved }: PatientFormDialogProps) {
  const isEdit = Boolean(patientId);
  const [patientName, setPatientName] = useState("");
  const [form, setForm] = useState(emptyForm);
  const [staff, setStaff] = useState<StaffOption[]>([]);
  const [loading, setLoading] = useState(isEdit);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.staffOptions().then((result) => setStaff(result.staff)).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!patientId) return;
    let active = true;
    api
      .patientForEdit(patientId)
      .then((result) => {
        if (!active) return;
        const p = result.patient;
        setPatientName(p.fullName);
        setForm({
          firstName: p.firstName,
          lastName: p.lastName,
          dateOfBirth: p.dateOfBirth,
          phone: p.phone || "",
          email: p.email || "",
          address: p.address || "",
          emergencyContact: p.emergencyContact || "",
          status: p.status,
          assignedTherapistId: p.assignedTherapist?.id || "",
          diagnoses: (p as Patient & { diagnoses?: string }).diagnoses || "",
          precautions: (p as Patient & { precautions?: string }).precautions || "",
        });
      })
      .catch((requestError) => active && setError(requestError instanceof ApiError ? requestError.message : "Unable to load this patient."))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [patientId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      await onSave(form);
      await onSaved();
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        setError(requestError.message);
        setFieldErrors(requestError.fields);
      } else {
        setError("Unable to save this patient.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="move-dialog client-dialog" role="dialog" aria-modal="true" aria-labelledby="patient-form-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">&times;</button>
        <p className="eyebrow">{isEdit ? "Edit patient" : "New patient"}</p>
        <h2 id="patient-form-title">{isEdit ? patientName || "Loading..." : "Add a patient"}</h2>
        {error && <p className="form-error" role="alert">{error}</p>}
        {loading ? <p className="muted">Loading patient...</p> : (
          <form className="stack-form" onSubmit={submit}>
            <div className="field-grid">
              <label>First name<input required value={form.firstName} onChange={(event) => setForm({ ...form, firstName: event.target.value })} />{fieldErrors.firstName && <small className="field-error">{fieldErrors.firstName}</small>}</label>
              <label>Last name<input required value={form.lastName} onChange={(event) => setForm({ ...form, lastName: event.target.value })} />{fieldErrors.lastName && <small className="field-error">{fieldErrors.lastName}</small>}</label>
              <label>Date of birth<input required type="date" value={form.dateOfBirth} onChange={(event) => setForm({ ...form, dateOfBirth: event.target.value })} />{fieldErrors.dateOfBirth && <small className="field-error">{fieldErrors.dateOfBirth}</small>}</label>
              <label>Phone<input value={form.phone} onChange={(event) => setForm({ ...form, phone: event.target.value })} /></label>
              <label>Email<input type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} />{fieldErrors.email && <small className="field-error">{fieldErrors.email}</small>}</label>
              <label>Emergency contact<input value={form.emergencyContact} onChange={(event) => setForm({ ...form, emergencyContact: event.target.value })} /></label>
              <label>Status<select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}>{STATUSES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>{fieldErrors.status && <small className="field-error">{fieldErrors.status}</small>}</label>
              <label>Assigned therapist
                <select value={form.assignedTherapistId} onChange={(event) => setForm({ ...form, assignedTherapistId: event.target.value })}>
                  <option value="">Unassigned</option>
                  {staff.map((member) => <option key={member.id} value={member.id}>{member.displayName} ({member.roleLabel})</option>)}
                </select>
                {fieldErrors.assignedTherapistId && <small className="field-error">{fieldErrors.assignedTherapistId}</small>}
              </label>
            </div>
            <label>Address<textarea rows={2} value={form.address} onChange={(event) => setForm({ ...form, address: event.target.value })} /></label>
            {canEditClinicalFields ? (
              <>
                <label>Diagnoses<textarea rows={3} value={form.diagnoses} onChange={(event) => setForm({ ...form, diagnoses: event.target.value })} /></label>
                <label>Precautions<textarea rows={3} value={form.precautions} onChange={(event) => setForm({ ...form, precautions: event.target.value })} /></label>
              </>
            ) : (
              <small className="muted">Only clinical roles can view or edit diagnosis and precaution details.</small>
            )}
            <div className="button-row">
              <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
              <button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving..." : isEdit ? "Save changes" : "Create patient"}</button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
