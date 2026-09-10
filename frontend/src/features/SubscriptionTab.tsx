import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ClientSubscriptionDetail } from "../api/types";
import { formatDate } from "../lib/format";

interface SubscriptionTabProps {
  clientNumber: number;
}

const STATUS_OPTIONS: Array<[string, string]> = [
  ["trial", "Trial"],
  ["active", "Active"],
  ["past_due", "Past due"],
  ["suspended", "Suspended"],
  ["cancelled", "Cancelled"],
];

const BILLING_CYCLE_OPTIONS: Array<[string, string]> = [
  ["monthly", "Monthly"],
  ["annual", "Annual"],
];

export function SubscriptionTab({ clientNumber }: SubscriptionTabProps) {
  const [detail, setDetail] = useState<ClientSubscriptionDetail | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  const [planCode, setPlanCode] = useState("");
  const [status, setStatus] = useState("trial");
  const [billingCycle, setBillingCycle] = useState("monthly");
  const [seatCount, setSeatCount] = useState("1");
  const [selectedFeatures, setSelectedFeatures] = useState<string[]>([]);

  async function load() {
    setError("");
    try {
      const result = await api.clientSubscription(clientNumber);
      setDetail(result);
      if (result.subscription) {
        setPlanCode(result.subscription.planCode);
        setStatus(result.subscription.status);
        setBillingCycle(result.subscription.billingCycle);
        setSeatCount(String(result.subscription.providerSeatCount));
        setSelectedFeatures(result.subscription.featureCodes);
      } else if (result.plans.length) {
        setPlanCode(result.plans[0].code);
        setSelectedFeatures(result.plans[0].featureCodes);
      }
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load the subscription.");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientNumber]);

  function toggleFeature(code: string) {
    setSelectedFeatures((current) => (current.includes(code) ? current.filter((entry) => entry !== code) : [...current, code]));
  }

  function selectPlan(code: string) {
    setPlanCode(code);
    // Changing the plan resets features to that plan's baseline on save
    // (matches the backend's own rule) — mirror it here so the checkboxes
    // reflect what will actually happen before the admin saves.
    const plan = detail?.plans.find((entry) => entry.code === code);
    if (plan) setSelectedFeatures(plan.featureCodes);
  }

  async function save() {
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      await api.updateClientSubscription(clientNumber, {
        planCode,
        status,
        billingCycle,
        providerSeatCount: Number(seatCount),
        features: selectedFeatures,
      });
      setSaved(true);
      await load();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to save the subscription.");
    } finally {
      setSaving(false);
    }
  }

  if (!detail) {
    return (
      <section className="surface-card">
        <p className="muted">Loading subscription...</p>
      </section>
    );
  }

  return (
    <section className="surface-card">
      <div className="card-heading">
        <h2>Subscription</h2>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {saved && <p className="form-notice" role="status">Subscription saved.</p>}

      {detail.subscription ? (
        <dl className="detail-grid">
          <div><dt>Current plan</dt><dd>{detail.subscription.planName}</dd></div>
          <div><dt>Status</dt><dd>{detail.subscription.statusLabel}</dd></div>
          <div><dt>Billing cycle</dt><dd>{detail.subscription.billingCycleLabel}</dd></div>
          <div><dt>Started</dt><dd>{formatDate(detail.subscription.startsAt, { month: "short", day: "numeric", year: "numeric" })}</dd></div>
          <div><dt>Ends</dt><dd>{detail.subscription.endsAt ? formatDate(detail.subscription.endsAt, { month: "short", day: "numeric", year: "numeric" }) : "No end date set"}</dd></div>
          <div><dt>Provider seats</dt><dd>{detail.subscription.providerSeatCount}</dd></div>
        </dl>
      ) : (
        <p className="empty-copy">No subscription has been assigned to this client yet — set one below.</p>
      )}

      <h3>Plan &amp; billing</h3>
      <div className="stack-form field-grid">
        <label>
          <span>Plan</span>
          <select value={planCode} onChange={(event) => selectPlan(event.target.value)}>
            {detail.plans.map((plan) => (
              <option key={plan.code} value={plan.code}>{plan.name} — ${plan.monthlyPrice}/mo</option>
            ))}
          </select>
        </label>
        <label>
          <span>Status</span>
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            {STATUS_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>
          <span>Billing cycle</span>
          <select value={billingCycle} onChange={(event) => setBillingCycle(event.target.value)}>
            {BILLING_CYCLE_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>
          <span>Provider seats</span>
          <input type="number" min={1} value={seatCount} onChange={(event) => setSeatCount(event.target.value)} />
        </label>
      </div>

      <h3>Enabled features</h3>
      <p className="muted">
        Changing the plan above resets this list to that plan's defaults — adjust individual features afterward if this
        client needs a customized set. The backend enforces these, not just the UI.
      </p>
      <div className="field-grid">
        {detail.features.map((feature) => (
          <label key={feature.code} className="check-label" title={feature.description}>
            <input type="checkbox" checked={selectedFeatures.includes(feature.code)} onChange={() => toggleFeature(feature.code)} />
            <span>{feature.name}</span>
          </label>
        ))}
      </div>

      <div className="button-row">
        <button type="button" className="primary-button" disabled={saving} onClick={() => void save()}>
          {saving ? "Saving..." : "Save subscription"}
        </button>
      </div>
    </section>
  );
}
