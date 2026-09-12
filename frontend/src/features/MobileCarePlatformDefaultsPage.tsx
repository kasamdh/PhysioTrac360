import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { MobileCarePlatformDefaults } from "../api/types";

export function MobileCarePlatformDefaultsPage() {
  const [defaults, setDefaults] = useState<MobileCarePlatformDefaults | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setDefaults((await api.superAdminMobileCarePlatformDefaults()).platformDefaults);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load platform defaults.");
    }
  }
  useEffect(() => { void load(); }, []);

  function update<K extends keyof MobileCarePlatformDefaults>(key: K, value: MobileCarePlatformDefaults[K]) {
    setDefaults((current) => (current ? { ...current, [key]: value } : current));
    setSaved(false);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!defaults) return;
    setBusy(true); setError(""); setSaved(false);
    try {
      const result = await api.updateSuperAdminMobileCarePlatformDefaults({
        defaultVisitDurationMinutes: defaults.defaultVisitDurationMinutes,
        offerExpirationHours: defaults.offerExpirationHours,
        patientCancellationWindowHours: defaults.patientCancellationWindowHours,
        providerCancellationNoticeHours: defaults.providerCancellationNoticeHours,
        maxTravelRadiusMiles: defaults.maxTravelRadiusMiles,
        sameProviderContinuityPreferred: defaults.sameProviderContinuityPreferred,
      });
      setDefaults(result.platformDefaults);
      setSaved(true);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to save platform defaults.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-content">
      <header className="page-header split-header">
        <div>
          <p className="eyebrow">Platform</p>
          <h1>Mobile Care platform defaults</h1>
          <p>
            The starting values every organization's own Mobile Care configuration falls back to until they set their
            own. Changing a value here only affects an organization that hasn't overridden that particular setting.
          </p>
        </div>
      </header>
      <section className="surface-card">
        {error && <p className="form-error" role="alert">{error}</p>}
        {saved && <p className="empty-copy">Saved.</p>}
        {!defaults ? (
          <p className="empty-copy">Loading…</p>
        ) : (
          <form onSubmit={save}>
            <div className="field-grid">
              <label>
                Default visit duration (minutes)
                <input
                  type="number" min="1" required value={defaults.defaultVisitDurationMinutes}
                  onChange={(event) => update("defaultVisitDurationMinutes", Number(event.target.value))}
                />
              </label>
              <label>
                Maximum travel radius (miles)
                <input
                  type="number" min="1" required value={defaults.maxTravelRadiusMiles}
                  onChange={(event) => update("maxTravelRadiusMiles", Number(event.target.value))}
                />
              </label>
              <label>
                Offer expiration time (hours)
                <input
                  type="number" min="1" required value={defaults.offerExpirationHours}
                  onChange={(event) => update("offerExpirationHours", Number(event.target.value))}
                />
              </label>
              <label>
                Patient cancellation window (hours)
                <input
                  type="number" min="0" required value={defaults.patientCancellationWindowHours}
                  onChange={(event) => update("patientCancellationWindowHours", Number(event.target.value))}
                />
              </label>
              <label>
                Provider cancellation notice (hours)
                <input
                  type="number" min="0" required value={defaults.providerCancellationNoticeHours}
                  onChange={(event) => update("providerCancellationNoticeHours", Number(event.target.value))}
                />
              </label>
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: ".5rem" }}>
              <input
                type="checkbox" checked={defaults.sameProviderContinuityPreferred}
                onChange={(event) => update("sameProviderContinuityPreferred", event.target.checked)}
              />
              Prefer the patient's existing provider by default
            </label>
            <div className="button-row">
              <button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving..." : "Save platform defaults"}</button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
