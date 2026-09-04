import { FormEvent, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ManagedClient } from "../api/types";

interface SuspendClientDialogProps {
  client: ManagedClient;
  onClose: () => void;
  onSuspended: () => Promise<void>;
}

export function SuspendClientDialog({ client, onClose, onSuspended }: SuspendClientDialogProps) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.setManagedClientStatus(client.clientNumber, "suspend", reason);
      await onSuspended();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to suspend client.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="move-dialog client-dialog" role="dialog" aria-modal="true" aria-labelledby="suspend-client-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">×</button>
        <p className="eyebrow">Client #{client.clientNumber}</p>
        <h2 id="suspend-client-title">Suspend {client.clientName}?</h2>
        <p>
          Suspending this client will immediately prevent all users, staff, therapists, and
          patients associated with {client.clientName} from accessing the system. No data will
          be deleted.
        </p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <form className="stack-form" onSubmit={submit}>
          <label>
            Suspension reason
            <textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Optional" />
          </label>
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
            <button className="primary-button" type="submit" disabled={busy}>{busy ? "Suspending..." : "Suspend client"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
