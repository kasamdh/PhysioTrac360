import { FormEvent, useState } from "react";

import { ApiError, api } from "../api/client";

interface ChangePasswordDialogProps {
  onClose: () => void;
}

export function ChangePasswordDialog({ onClose }: ChangePasswordDialogProps) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (newPassword.length < 12) {
      setError("Choose a new password with at least 12 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("New passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(currentPassword, newPassword);
      setSuccess(true);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to change your password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="move-dialog" role="dialog" aria-modal="true" aria-labelledby="change-password-title">
        <button className="dialog-close" onClick={onClose} aria-label="Close">&times;</button>
        <p className="eyebrow">Account</p>
        <h2 id="change-password-title">Change password</h2>

        {success ? (
          <>
            <p className="form-notice">Your password has been updated.</p>
            <div className="button-row" style={{ marginTop: "1rem" }}>
              <button className="primary-button" type="button" onClick={onClose}>Done</button>
            </div>
          </>
        ) : (
          <form onSubmit={handleSubmit}>
            <label className="field-label">
              <span>Current password</span>
              <input
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                type="password"
                autoComplete="current-password"
                required
              />
            </label>
            <label className="field-label">
              <span>New password</span>
              <input
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                type="password"
                autoComplete="new-password"
                minLength={12}
                required
              />
            </label>
            <label className="field-label">
              <span>Confirm new password</span>
              <input
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                type="password"
                autoComplete="new-password"
                minLength={12}
                required
              />
            </label>
            <small className="muted">Use at least 12 characters.</small>

            {error && <p className="form-error" role="alert">{error}</p>}

            <div className="button-row" style={{ marginTop: "1rem" }}>
              <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
              <button className="primary-button" type="submit" disabled={busy}>
                {busy ? "Saving…" : "Change password"}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
