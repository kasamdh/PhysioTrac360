import { useEffect, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { PortalFormField, PortalFormSection, PortalFormSubmission, PortalInsurancePolicy, PortalPayerOption } from "../../api/types";
import { formatDate } from "../../lib/format";

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function Field({
  field,
  value,
  onChange,
  error,
}: {
  field: PortalFormField;
  value: unknown;
  onChange: (value: unknown) => void;
  error?: string;
}) {
  const inputId = `form-field-${field.key}`;
  return (
    <label htmlFor={inputId} style={{ display: "grid", gap: ".35rem" }}>
      <span>{field.label}{field.required ? " *" : ""}</span>
      {field.type === "textarea" && (
        <textarea id={inputId} value={(value as string) || ""} onChange={(event) => onChange(event.target.value)} rows={3} />
      )}
      {field.type === "number" && (
        <input id={inputId} type="number" value={(value as string) ?? ""} onChange={(event) => onChange(event.target.value)} />
      )}
      {field.type === "checkbox" && (
        <span style={{ display: "flex", alignItems: "center", gap: ".5rem" }}>
          <input id={inputId} type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} style={{ width: "auto" }} />
        </span>
      )}
      {field.type === "text" && (
        <input id={inputId} type="text" value={(value as string) || ""} onChange={(event) => onChange(event.target.value)} />
      )}
      {error && <small className="form-error" role="alert">{error}</small>}
    </label>
  );
}

function InsuranceStep() {
  const [payers, setPayers] = useState<PortalPayerOption[]>([]);
  const [policies, setPolicies] = useState<PortalInsurancePolicy[]>([]);
  const [payerId, setPayerId] = useState("");
  const [memberId, setMemberId] = useState("");
  const [groupNumber, setGroupNumber] = useState("");
  const [subscriberName, setSubscriberName] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");

  async function load() {
    const [payerResult, policyResult] = await Promise.all([api.portalInsurancePayers(), api.portalInsurancePolicies()]);
    setPayers(payerResult.payers);
    setPolicies(policyResult.policies);
    const primary = policyResult.policies.find((policy) => policy.rank === "primary");
    if (primary) {
      setPayerId(primary.payerId);
      setMemberId(primary.memberId);
      setGroupNumber(primary.groupNumber);
      setSubscriberName(primary.subscriberName);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function save() {
    setError("");
    setSaving(true);
    try {
      await api.portalCreateInsurancePolicy({ payerId, memberId, groupNumber, subscriberName, rank: "primary" });
      setNotice("Insurance information saved.");
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to save your insurance information."));
    } finally {
      setSaving(false);
    }
  }

  async function uploadCard(policyId: string, side: "front" | "back", file: File) {
    setError("");
    try {
      await api.portalUploadInsuranceCard(policyId, side, file);
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to upload this image."));
    }
  }

  const primaryPolicy = policies.find((policy) => policy.rank === "primary");

  return (
    <div style={{ display: "grid", gap: ".75rem" }}>
      <p className="portal-empty">Optional, but helps us verify your benefits before your visit.</p>
      <label>
        <span>Insurance company</span>
        <select value={payerId} onChange={(event) => setPayerId(event.target.value)}>
          <option value="">Select...</option>
          {payers.map((payer) => (
            <option key={payer.id} value={payer.id}>{payer.name}</option>
          ))}
        </select>
      </label>
      <label>
        <span>Member ID</span>
        <input value={memberId} onChange={(event) => setMemberId(event.target.value)} />
      </label>
      <label>
        <span>Group number (optional)</span>
        <input value={groupNumber} onChange={(event) => setGroupNumber(event.target.value)} />
      </label>
      <label>
        <span>Subscriber name (if not you)</span>
        <input value={subscriberName} onChange={(event) => setSubscriberName(event.target.value)} />
      </label>
      {error && <p className="form-error" role="alert">{error}</p>}
      {notice && <p className="form-notice" role="status">{notice}</p>}
      <div className="button-row">
        <button className="secondary-button" type="button" disabled={saving || !payerId || !memberId} onClick={() => void save()}>
          {saving ? "Saving..." : "Save insurance info"}
        </button>
      </div>

      {primaryPolicy && (
        <div style={{ display: "grid", gap: ".5rem" }}>
          <p className="portal-section-heading">Insurance card photos</p>
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <label>
              <span>Front {primaryPolicy.hasCardFront ? "(uploaded)" : ""}</span>
              <input
                type="file"
                accept="image/png,image/jpeg"
                onChange={(event) => event.target.files?.[0] && void uploadCard(primaryPolicy.id, "front", event.target.files[0])}
              />
            </label>
            <label>
              <span>Back {primaryPolicy.hasCardBack ? "(uploaded)" : ""}</span>
              <input
                type="file"
                accept="image/png,image/jpeg"
                onChange={(event) => event.target.files?.[0] && void uploadCard(primaryPolicy.id, "back", event.target.files[0])}
              />
            </label>
          </div>
        </div>
      )}
    </div>
  );
}

interface PortalFormPageProps {
  templateSlug: string;
  onDone: () => void;
}

export function PortalFormPage({ templateSlug, onDone }: PortalFormPageProps) {
  const [submission, setSubmission] = useState<PortalFormSubmission | null>(null);
  const [data, setData] = useState<Record<string, unknown>>({});
  const [stepIndex, setStepIndex] = useState(0);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let active = true;
    api
      .portalFormDetail(templateSlug)
      .then((result) => {
        if (!active) return;
        setSubmission(result.submission);
        setData(result.submission.data);
      })
      .catch((requestError) => active && setError(requestMessage(requestError, "Unable to load this form.")));
    return () => {
      active = false;
    };
  }, [templateSlug]);

  if (error) return <p className="form-error" role="alert">{error}</p>;
  if (!submission) return <p className="portal-empty">Loading...</p>;

  if (submission.status === "completed") {
    return (
      <div className="portal-card">
        <p className="eyebrow">{submission.templateName}</p>
        <h2>Submitted</h2>
        <p className="portal-empty">
          {submission.submittedAt ? `Submitted on ${formatDate(submission.submittedAt)}.` : "This form has been submitted."}
        </p>
        <button className="secondary-button" onClick={onDone}>Back to forms</button>
      </div>
    );
  }

  const schema: PortalFormSection[] = submission.schema || [];
  type Step = (PortalFormSection & { custom?: undefined }) | { key: string; label: string; fields?: undefined; custom: "insurance" };
  const steps: Step[] = [...schema];
  if (templateSlug === "digital-intake") {
    const consentIndex = steps.findIndex((step) => step.key === "consent");
    const insuranceStep: Step = { key: "insurance", label: "Insurance", custom: "insurance" };
    if (consentIndex >= 0) steps.splice(consentIndex, 0, insuranceStep);
    else steps.push(insuranceStep);
  }
  const step = steps[stepIndex];
  const isLastStep = stepIndex === steps.length - 1;

  function updateField(key: string, value: unknown) {
    setData((current) => ({ ...current, [key]: value }));
  }

  async function saveProgress(nextIndex?: number) {
    setError("");
    setSaving(true);
    try {
      const result = await api.portalFormSave(templateSlug, data);
      setSubmission(result.submission);
      if (nextIndex !== undefined) setStepIndex(nextIndex);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to save your progress."));
    } finally {
      setSaving(false);
    }
  }

  async function submitForm() {
    setError("");
    setFieldErrors({});
    setSubmitting(true);
    try {
      const result = await api.portalFormSubmit(templateSlug, data);
      setSubmission(result.submission);
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 422) {
        setFieldErrors((requestError.fields as Record<string, string>) || {});
        setError("Please complete the highlighted fields.");
      } else {
        setError(requestMessage(requestError, "Unable to submit this form."));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <div>
        <p className="eyebrow">{submission.templateName}</p>
        <h1>{step?.label}</h1>
      </div>
      <ol className="booking-stepper">
        {steps.map((entry, index) => (
          <li key={entry.key} className={index === stepIndex ? "active" : index < stepIndex ? "done" : ""}>
            <span className="booking-step-dot">{index < stepIndex ? "✓" : index + 1}</span>
            {entry.label}
          </li>
        ))}
      </ol>

      <section className="booking-card">
        {step?.custom === "insurance" ? (
          <InsuranceStep />
        ) : (
          <div style={{ display: "grid", gap: ".9rem" }}>
            {step?.fields.map((field) => (
              <Field key={field.key} field={field} value={data[field.key]} onChange={(value) => updateField(field.key, value)} error={fieldErrors[field.key]} />
            ))}
          </div>
        )}

        {error && <p className="form-error" role="alert">{error}</p>}

        <div className="booking-step-actions">
          <button className="secondary-button" disabled={stepIndex === 0 || saving} onClick={() => void saveProgress(stepIndex - 1)}>
            Back
          </button>
          <div className="button-row">
            <button className="secondary-button" disabled={saving} onClick={() => void saveProgress()}>
              {saving ? "Saving..." : "Save & exit"}
            </button>
            {!isLastStep ? (
              <button className="primary-button" disabled={saving} onClick={() => void saveProgress(stepIndex + 1)}>
                Continue
              </button>
            ) : (
              <button className="primary-button" disabled={submitting} onClick={() => void submitForm()}>
                {submitting ? "Submitting..." : "Submit"}
              </button>
            )}
          </div>
        </div>
      </section>
    </>
  );
}
