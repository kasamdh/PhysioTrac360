import { useState } from "react";

import { ApiError } from "../api/client";

interface ConfirmActionDialogProps {
  eyebrow: string;
  title: string;
  body: string;
  confirmLabel: string;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}

export function ConfirmActionDialog({ eyebrow, title, body, confirmLabel, onClose, onConfirm }: ConfirmActionDialogProps) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await onConfirm();
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        const fieldMessages = Object.values(requestError.fields).join(" ");
        setError(fieldMessages || requestError.message);
      } else {
        setError("Unable to complete this action.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="move-dialog client-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-action-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">&times;</button>
        <p className="eyebrow">{eyebrow}</p>
        <h2 id="confirm-action-title">{title}</h2>
        <p>{body}</p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="button-row" style={{ marginTop: "1rem" }}>
          <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="primary-button" type="button" onClick={() => void confirm()} disabled={busy}>{busy ? "Working..." : confirmLabel}</button>
        </div>
      </section>
    </div>
  );
}
