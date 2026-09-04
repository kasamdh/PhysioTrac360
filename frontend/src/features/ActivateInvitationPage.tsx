import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { WorkspaceUser } from "../api/types";

interface ActivateInvitationPageProps {
  token: string;
  onActivated: (user: WorkspaceUser) => void;
}

export function ActivateInvitationPage({ token, onActivated }: ActivateInvitationPageProps) {
  const [organizationName, setOrganizationName] = useState("");
  const [email, setEmail] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [loadingPreview, setLoadingPreview] = useState(true);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let active = true;
    api
      .previewInvitation(token)
      .then((result) => {
        if (!active) return;
        setOrganizationName(result.organizationName);
        setEmail(result.email);
      })
      .catch((requestError) => {
        if (!active) return;
        setPreviewError(requestError instanceof ApiError ? requestError.message : "This invitation link is not valid.");
      })
      .finally(() => active && setLoadingPreview(false));
    return () => {
      active = false;
    };
  }, [token]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (password.length < 12) {
      setError("Choose a password with at least 12 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      const user = await api.activateInvitation(token, password);
      onActivated(user);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to activate this invitation.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-layout">
      <section className="login-card" aria-labelledby="activate-title">
        <div className="login-visual">
          <div className="login-brand-row">
            <div className="login-mark" aria-hidden="true">PT</div>
            <div className="login-brand-copy">
              <span>{organizationName || "PhysioTrac360"}</span>
              <small>Welcome to your practice workspace</small>
            </div>
          </div>
          <div className="login-visual-content">
            <p className="eyebrow">Account setup</p>
            <h2>You've been invited as this organization's administrator.</h2>
            <p>Choose a password to activate your account. This link can only be used once.</p>
          </div>
        </div>

        <div className="login-form-panel">
          <p className="login-kicker">{organizationName || "Your organization"}</p>
          <h1 id="activate-title">Set your password</h1>

          {loadingPreview && <p className="login-intro">Checking your invitation...</p>}

          {!loadingPreview && previewError && (
            <p className="form-error" role="alert">{previewError}</p>
          )}

          {!loadingPreview && !previewError && (
            <>
              <p className="login-intro">
                Signing in as <strong>{email}</strong>. Choose a password to finish setting up
                your account.
              </p>
              <form onSubmit={handleSubmit} className="login-form">
                <label className="field-label">
                  <span>New password</span>
                  <input
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    type="password"
                    autoComplete="new-password"
                    minLength={12}
                    required
                  />
                </label>
                <label className="field-label">
                  <span>Confirm password</span>
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

                <button className="primary-button" type="submit" disabled={submitting}>
                  {submitting ? "Activating..." : "Activate account"}
                </button>
              </form>
            </>
          )}
        </div>
      </section>
    </main>
  );
}
