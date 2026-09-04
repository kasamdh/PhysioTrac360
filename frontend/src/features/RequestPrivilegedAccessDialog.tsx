import { FormEvent, useState } from "react";

import { ApiError, api } from "../api/client";

interface RequestPrivilegedAccessDialogProps {
  clientNumber: number;
  clientName: string;
  onClose: () => void;
  onGranted: () => Promise<void>;
}

const DURATIONS = [
  [1, "1 hour"],
  [4, "4 hours"],
  [24, "24 hours"],
] as const;

export function RequestPrivilegedAccessDialog({ clientNumber, clientName, onClose, onGranted }: RequestPrivilegedAccessDialogProps) {
  const [reason, setReason] = useState("");
  const [durationHours, setDurationHours] = useState(1);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      await api.requestPrivilegedAccess(clientNumber, reason, durationHours);
      await onGranted();
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        setError(requestError.message);
        setFieldErrors(requestError.fields);
      } else {
        setError("Unable to request privileged access.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="move-dialog client-dialog" role="dialog" aria-modal="true" aria-labelledby="request-access-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">&times;</button>
        <p className="eyebrow">#{clientNumber} {clientName}</p>
        <h2 id="request-access-title">Request privileged clinical access</h2>
        <p>
          You have no standing access to this client's clinical records. This creates a
          time-boxed, fully audited grant — every chart you view while it is active is
          logged against this request.
        </p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <form className="stack-form" onSubmit={submit}>
          <label>
            Reason for access
            <textarea required rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="e.g. Investigating support ticket #4821 about a missing note." />
            {fieldErrors.reason && <small className="field-error">{fieldErrors.reason}</small>}
          </label>
          <label>
            Duration
            <select value={durationHours} onChange={(event) => setDurationHours(Number(event.target.value))}>
              {DURATIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            {fieldErrors.durationHours && <small className="field-error">{fieldErrors.durationHours}</small>}
          </label>
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
            <button className="primary-button" type="submit" disabled={busy}>{busy ? "Requesting..." : "Request access"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
