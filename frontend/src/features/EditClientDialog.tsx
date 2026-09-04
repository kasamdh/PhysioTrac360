import { FormEvent, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ManagedClient } from "../api/types";

interface EditClientDialogProps {
  client: ManagedClient;
  onClose: () => void;
  onSaved: () => Promise<void>;
}

export function EditClientDialog({ client, onClose, onSaved }: EditClientDialogProps) {
  const [form, setForm] = useState({
    clientName: client.clientName,
    clientEmail: client.email,
    clientPhone: client.phone,
    addressLine1: client.addressLine1,
    addressLine2: client.addressLine2,
    city: client.city,
    state: client.state,
    zipCode: client.zipCode,
    country: client.country,
    subscriptionTier: client.subscriptionTier,
    timezone: client.timezone,
    comments: client.comments,
  });
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  function update(field: string, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setFieldErrors((current) => ({ ...current, [field]: "" }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      await api.updateManagedClient(client.clientNumber, form);
      await onSaved();
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        setError(requestError.message);
        setFieldErrors(requestError.fields);
      } else {
        setError("Unable to update client.");
      }
    } finally {
      setBusy(false);
    }
  }

  return <div className="modal-backdrop"><section className="move-dialog client-dialog" role="dialog" aria-modal="true" aria-labelledby="edit-client-title"><button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">×</button><p className="eyebrow">Client #{client.clientNumber}</p><h2 id="edit-client-title">Edit {client.clientName}</h2>{error && <p className="form-error" role="alert">{error}</p>}<form className="stack-form" onSubmit={submit}><div className="field-grid"><label>Client name<input required value={form.clientName} onChange={(event) => update("clientName", event.target.value)} />{fieldErrors.clientName && <small className="field-error">{fieldErrors.clientName}</small>}</label><label>Client email<input required type="email" value={form.clientEmail} onChange={(event) => update("clientEmail", event.target.value)} />{fieldErrors.clientEmail && <small className="field-error">{fieldErrors.clientEmail}</small>}</label><label>Phone<input value={form.clientPhone} onChange={(event) => update("clientPhone", event.target.value)} /></label><label>Address line 1<input required value={form.addressLine1} onChange={(event) => update("addressLine1", event.target.value)} /></label><label>Address line 2<input value={form.addressLine2} onChange={(event) => update("addressLine2", event.target.value)} /></label><label>City<input required value={form.city} onChange={(event) => update("city", event.target.value)} /></label><label>State<input required value={form.state} onChange={(event) => update("state", event.target.value)} /></label><label>ZIP<input required value={form.zipCode} onChange={(event) => update("zipCode", event.target.value)} /></label><label>Country<input value={form.country} onChange={(event) => update("country", event.target.value)} /></label></div><div className="field-grid"><label>Subscription tier<select value={form.subscriptionTier} onChange={(event) => update("subscriptionTier", event.target.value)}><option value="starter">Starter</option><option value="professional">Professional</option><option value="premium">Premium</option><option value="enterprise">Enterprise</option></select></label><label>Timezone<select value={form.timezone} onChange={(event) => update("timezone", event.target.value)}><option>America/New_York</option><option>America/Chicago</option><option>America/Denver</option><option>America/Los_Angeles</option><option>America/Phoenix</option><option>Pacific/Honolulu</option></select></label></div><label>Comments<textarea rows={3} value={form.comments} onChange={(event) => update("comments", event.target.value)} /></label><div className="button-row"><button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button><button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving..." : "Save changes"}</button></div></form></section></div>;
}
