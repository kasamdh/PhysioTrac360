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

  const showFacilityBox = Boolean(portalSlug) && portalSlug !== "app";

  return (
    <main className="signin-shell">
      <header className="signin-topbar">
        <span className="signin-topbar-mark" aria-hidden="true">PT</span>
        <strong className="signin-topbar-word">
          PhysioTrac<em>360</em>
        </strong>
      </header>

      <div className="signin-body">
        <div className="signin-hero">
          <div className="signin-hero-mark" aria-hidden="true">
            <svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path
                d="M6 34h9l5-14 9 28 8-20 5 6h16"
                stroke="currentColor"
                strokeWidth="4.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <div className="signin-hero-word">
            PhysioTrac<span>360</span>
          </div>
          <p className="signin-hero-tag">Complete practice operations</p>
        </div>

        <div className="signin-panel">
          <p className="signin-panel-brand" id="login-title">
            PhysioTrac<em>360</em>
          </p>
          <section className="signin-card" aria-labelledby="login-title">
            {error && (
              <p className="signin-banner signin-banner-error" role="alert">
                {error}
              </p>
            )}

            {showFacilityBox && (
              <div>
                <span className="signin-label" id="signin-org-label">
                  Organization
                </span>
                <div className="signin-field-box" role="note" aria-labelledby="signin-org-label">
                  {facilityName}
                </div>
              </div>
            )}

            <form onSubmit={handleSubmit} className="signin-form">
              <div>
                <label className="signin-label" htmlFor="signin-username">
                  Login User Id
                </label>
                <input
                  id="signin-username"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="Enter your user ID"
                  autoComplete="username"
                  aria-invalid={Boolean(error)}
                  required
                />
              </div>

              <div>
                <label className="signin-label" htmlFor="signin-password">
                  Login Password
                </label>
                <input
                  id="signin-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  type="password"
                  placeholder="Enter your password"
                  autoComplete="current-password"
                  required
                />
              </div>

              <button className="signin-button" type="submit" disabled={submitting}>
                {submitting ? "Signing in…" : "Login"}
              </button>
            </form>
          </section>
        </div>
      </div>

      <footer className="signin-footer">
        PhysioTrac360 &copy; {new Date().getFullYear()} PhysioTrac360, Inc. All rights reserved. Confidential.
      </footer>
    </main>
  );
}
