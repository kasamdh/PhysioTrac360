import { FormEvent, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ManagedClient } from "../api/types";

interface ArchiveClientDialogProps {
  client: ManagedClient;
  onClose: () => void;
  onArchived: () => Promise<void>;
}

export function ArchiveClientDialog({ client, onClose, onArchived }: ArchiveClientDialogProps) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.archiveManagedClient(client.clientNumber, reason);
      await onArchived();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to archive client.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="move-dialog client-dialog" role="dialog" aria-modal="true" aria-labelledby="archive-client-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">×</button>
        <p className="eyebrow">Client #{client.clientNumber}</p>
        <h2 id="archive-client-title">Archive {client.clientName}?</h2>
        <p>
          Archiving is permanent for this workspace and immediately blocks access for every
          user, therapist, and patient associated with {client.clientName}. No records, notes,
          or audit history are deleted — an archived client can be restored by support if needed.
        </p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <form className="stack-form" onSubmit={submit}>
          <label>
            Archive reason
            <textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Optional" />
          </label>
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
            <button className="primary-button" type="submit" disabled={busy}>{busy ? "Archiving..." : "Archive client"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
