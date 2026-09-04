import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { WorkspaceUser } from "../api/types";

interface LoginScreenProps {
  onAuthenticated: (user: WorkspaceUser) => void;
}

export function LoginScreen({ onAuthenticated }: LoginScreenProps) {
  const portalSlug = window.location.pathname.split("/").filter(Boolean)[0] || "";
  const [facilityName, setFacilityName] = useState("Facility name");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!portalSlug || portalSlug === "app") return;
    api.facility(portalSlug).then((facility) => setFacilityName(facility.name)).catch(() => undefined);
  }, [portalSlug]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      onAuthenticated(await api.login(username, password, portalSlug));
    } catch (requestError) {
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : "Unable to sign in. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-layout">
      <section className="login-card" aria-labelledby="login-title">
        <div className="login-visual">
          <div className="login-brand-row">
            <div className="login-mark" aria-hidden="true">SM</div>
            <div className="login-brand-copy">
              <span>{facilityName}</span>
              <small>Complete practice operations</small>
            </div>
          </div>

          <div className="login-visual-content">
            <p className="eyebrow">Operations overview</p>
            <h2>Built for faster, clearer care workflows.</h2>
            <p>
              Documentation, scheduling, patient payments, billing, and secure communication in one workspace.
            </p>
          </div>

          <div className="login-stats">
            <div>
              <strong>1.8k</strong>
              <span>Visits this month</span>
            </div>
            <div>
              <strong>96%</strong>
              <span>Documentation completion</span>
            </div>
          </div>
        </div>

        <div className="login-form-panel">
          <p className="login-kicker">{facilityName}</p>
          <h1 id="login-title">Welcome back</h1>
          <p className="login-intro">One secure place to run your practice and keep care moving.</p>

          <form onSubmit={handleSubmit} className="login-form">
            <label className="field-label">
              <span>Username</span>
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                aria-invalid={Boolean(error)}
                required
              />
            </label>

            <label className="field-label">
              <span>Password</span>
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                autoComplete="current-password"
                required
              />
            </label>

            {error && <p className="form-error" role="alert">{error}</p>}

            <button className="primary-button" type="submit" disabled={submitting}>
              {submitting ? "Signing in…" : "Continue"}
            </button>
          </form>

          <p className="privacy-copy">
            This is a private clinical workspace. Contact your administrator with questions
            about the Privacy Policy or Terms of Service.
          </p>
        </div>
      </section>
    </main>
  );
}
