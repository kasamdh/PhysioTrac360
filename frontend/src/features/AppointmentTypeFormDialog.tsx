import { FormEvent, useState } from "react";

import { ApiError, api } from "../api/client";
import type { AppointmentType } from "../api/types";

interface AppointmentTypeFormDialogProps {
  appointmentType?: AppointmentType;
  onClose: () => void;
  onSaved: () => Promise<void>;
}

export function AppointmentTypeFormDialog({ appointmentType, onClose, onSaved }: AppointmentTypeFormDialogProps) {
  const isEdit = Boolean(appointmentType);
  const [form, setForm] = useState({
    name: appointmentType?.name || "",
    defaultDurationMinutes: appointmentType?.defaultDurationMinutes ?? 30,
    color: appointmentType?.color || "",
  });
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      if (isEdit) {
        await api.updateAppointmentType(appointmentType!.id, form);
      } else {
        await api.createAppointmentType(form);
      }
      await onSaved();
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        setError(requestError.message);
        setFieldErrors(requestError.fields);
      } else {
        setError("Unable to save this appointment type.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="move-dialog client-dialog" role="dialog" aria-modal="true" aria-labelledby="appointment-type-form-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">&times;</button>
        <p className="eyebrow">Clinic settings · Appointment types</p>
        <h2 id="appointment-type-form-title">{isEdit ? `Edit ${appointmentType!.name}` : "Add an appointment type"}</h2>
        {error && <p className="form-error" role="alert">{error}</p>}
        <form className="stack-form" onSubmit={submit}>
          <div className="field-grid">
            <label>Name<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />{fieldErrors.name && <small className="field-error">{fieldErrors.name}</small>}</label>
            <label>Default duration (minutes)<input required type="number" min={1} max={480} value={form.defaultDurationMinutes} onChange={(event) => setForm({ ...form, defaultDurationMinutes: Number(event.target.value) })} />{fieldErrors.defaultDurationMinutes && <small className="field-error">{fieldErrors.defaultDurationMinutes}</small>}</label>
            <label>Color tag (optional)<input value={form.color} onChange={(event) => setForm({ ...form, color: event.target.value })} placeholder="e.g. #4380b8" /></label>
          </div>
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
            <button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving..." : isEdit ? "Save changes" : "Add appointment type"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
