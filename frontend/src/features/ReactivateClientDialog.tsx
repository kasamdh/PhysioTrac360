import { useState } from "react";

import { ApiError, api } from "../api/client";
import type { ManagedClient } from "../api/types";

interface ReactivateClientDialogProps {
  client: ManagedClient;
  onClose: () => void;
  onReactivated: () => Promise<void>;
}

export function ReactivateClientDialog({ client, onClose, onReactivated }: ReactivateClientDialogProps) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await api.setManagedClientStatus(client.clientNumber, "activate");
      await onReactivated();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to reactivate client.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="move-dialog client-dialog" role="dialog" aria-modal="true" aria-labelledby="reactivate-client-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">×</button>
        <p className="eyebrow">Client #{client.clientNumber}</p>
        <h2 id="reactivate-client-title">Reactivate {client.clientName}?</h2>
        <p>
          Reactivating this client restores system access for its administrator, staff,
          therapists, and patients according to their previous permissions.
        </p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="button-row" style={{ marginTop: "1rem" }}>
          <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="primary-button" type="button" onClick={() => void confirm()} disabled={busy}>{busy ? "Reactivating..." : "Reactivate client"}</button>
        </div>
      </section>
    </div>
  );
}
