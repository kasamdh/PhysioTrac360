import { FormEvent, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ClinicLocation } from "../api/types";

interface LocationFormDialogProps {
  location?: ClinicLocation;
  onClose: () => void;
  onSaved: () => Promise<void>;
}

export function LocationFormDialog({ location, onClose, onSaved }: LocationFormDialogProps) {
  const isEdit = Boolean(location);
  const [form, setForm] = useState({
    name: location?.name || "",
    addressLine1: location?.addressLine1 || "",
    addressLine2: location?.addressLine2 || "",
    city: location?.city || "",
    state: location?.state || "",
    zipCode: location?.zipCode || "",
    phone: location?.phone || "",
    timezone: location?.timezone || "America/New_York",
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
        await api.updateLocation(location!.id, form);
      } else {
        await api.createLocation(form);
      }
      await onSaved();
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        setError(requestError.message);
        setFieldErrors(requestError.fields);
      } else {
        setError("Unable to save this location.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="move-dialog client-dialog" role="dialog" aria-modal="true" aria-labelledby="location-form-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">&times;</button>
        <p className="eyebrow">Clinic settings · Locations</p>
        <h2 id="location-form-title">{isEdit ? `Edit ${location!.name}` : "Add a location"}</h2>
        {error && <p className="form-error" role="alert">{error}</p>}
        <form className="stack-form" onSubmit={submit}>
          <div className="field-grid">
            <label>Location name<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />{fieldErrors.name && <small className="field-error">{fieldErrors.name}</small>}</label>
            <label>Phone<input value={form.phone} onChange={(event) => setForm({ ...form, phone: event.target.value })} /></label>
            <label>Address line 1<input value={form.addressLine1} onChange={(event) => setForm({ ...form, addressLine1: event.target.value })} /></label>
            <label>Address line 2<input value={form.addressLine2} onChange={(event) => setForm({ ...form, addressLine2: event.target.value })} /></label>
            <label>City<input value={form.city} onChange={(event) => setForm({ ...form, city: event.target.value })} /></label>
            <label>State<input value={form.state} onChange={(event) => setForm({ ...form, state: event.target.value })} /></label>
            <label>ZIP<input value={form.zipCode} onChange={(event) => setForm({ ...form, zipCode: event.target.value })} /></label>
            <label>Timezone
              <select value={form.timezone} onChange={(event) => setForm({ ...form, timezone: event.target.value })}>
                <option>America/New_York</option>
                <option>America/Chicago</option>
                <option>America/Denver</option>
                <option>America/Los_Angeles</option>
                <option>America/Phoenix</option>
                <option>Pacific/Honolulu</option>
              </select>
              {fieldErrors.timezone && <small className="field-error">{fieldErrors.timezone}</small>}
            </label>
          </div>
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
            <button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving..." : isEdit ? "Save changes" : "Add location"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
