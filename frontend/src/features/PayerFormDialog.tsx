import { FormEvent, useState } from "react";

import { ApiError, api } from "../api/client";
import type { Payer } from "../api/types";

interface PayerFormDialogProps {
  payer?: Payer;
  onClose: () => void;
  onSaved: () => Promise<void>;
}

export function PayerFormDialog({ payer, onClose, onSaved }: PayerFormDialogProps) {
  const isEdit = Boolean(payer);
  const [form, setForm] = useState({
    name: payer?.name || "",
    payerId: payer?.payerId || "",
    electronicPayerId: payer?.electronicPayerId || "",
    phone: payer?.phone || "",
    addressLine1: payer?.addressLine1 || "",
    addressLine2: payer?.addressLine2 || "",
    city: payer?.city || "",
    state: payer?.state || "",
    zipCode: payer?.zipCode || "",
    timelyFilingDays: String(payer?.timelyFilingDays ?? 90),
    authorizationRequired: payer?.authorizationRequired ?? false,
    authorizationNotes: payer?.authorizationNotes || "",
    notes: payer?.notes || "",
  });
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    const body = { ...form, timelyFilingDays: Number(form.timelyFilingDays) || 90 };
    try {
      if (isEdit) {
        await api.updatePayer(payer!.id, body);
      } else {
        await api.createPayer(body);
      }
      await onSaved();
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        setError(requestError.message);
        setFieldErrors(requestError.fields);
      } else {
        setError("Unable to save this payer.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="move-dialog client-dialog" role="dialog" aria-modal="true" aria-labelledby="payer-form-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">&times;</button>
        <p className="eyebrow">Clinic settings · Payers</p>
        <h2 id="payer-form-title">{isEdit ? `Edit ${payer!.name}` : "Add a payer"}</h2>
        {error && <p className="form-error" role="alert">{error}</p>}
        <form className="stack-form" onSubmit={submit}>
          <div className="field-grid">
            <label>Payer name<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />{fieldErrors.name && <small className="field-error">{fieldErrors.name}</small>}</label>
            <label>Payer ID<input value={form.payerId} onChange={(event) => setForm({ ...form, payerId: event.target.value })} /></label>
            <label>Electronic payer ID<input value={form.electronicPayerId} onChange={(event) => setForm({ ...form, electronicPayerId: event.target.value })} /></label>
            <label>Phone<input value={form.phone} onChange={(event) => setForm({ ...form, phone: event.target.value })} /></label>
            <label>Address line 1<input value={form.addressLine1} onChange={(event) => setForm({ ...form, addressLine1: event.target.value })} /></label>
            <label>Address line 2<input value={form.addressLine2} onChange={(event) => setForm({ ...form, addressLine2: event.target.value })} /></label>
            <label>City<input value={form.city} onChange={(event) => setForm({ ...form, city: event.target.value })} /></label>
            <label>State<input value={form.state} onChange={(event) => setForm({ ...form, state: event.target.value })} /></label>
            <label>ZIP<input value={form.zipCode} onChange={(event) => setForm({ ...form, zipCode: event.target.value })} /></label>
            <label>Timely filing (days)<input type="number" min={1} max={999} value={form.timelyFilingDays} onChange={(event) => setForm({ ...form, timelyFilingDays: event.target.value })} />{fieldErrors.timelyFilingDays && <small className="field-error">{fieldErrors.timelyFilingDays}</small>}</label>
            <label className="check-label"><input type="checkbox" checked={form.authorizationRequired} onChange={(event) => setForm({ ...form, authorizationRequired: event.target.checked })} /> Authorization required by default</label>
          </div>
          <label>Authorization rules / notes<textarea value={form.authorizationNotes} onChange={(event) => setForm({ ...form, authorizationNotes: event.target.value })} /></label>
          <label>Internal notes<textarea value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} /></label>
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
            <button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving..." : isEdit ? "Save changes" : "Add payer"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
