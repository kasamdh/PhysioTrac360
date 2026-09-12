import { useEffect, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { PortalMobileCareRequest } from "../../api/types";
import { formatDate, formatTime } from "../../lib/format";

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

const REQUESTED_SERVICE_OPTIONS = [
  { value: "", label: "Not sure yet" },
  { value: "evaluation", label: "Initial evaluation" },
  { value: "follow_up", label: "Follow-up visit" },
  { value: "progress", label: "Progress visit" },
  { value: "discharge", label: "Discharge visit" },
];

const TIME_WINDOW_OPTIONS = [
  { value: "", label: "No preference" },
  { value: "morning", label: "Morning (8am–12pm)" },
  { value: "afternoon", label: "Afternoon (12pm–5pm)" },
  { value: "evening", label: "Evening (5pm–9pm)" },
  { value: "any", label: "Any time" },
];

const GENDER_PREFERENCE_OPTIONS = [
  { value: "no_preference", label: "No preference" },
  { value: "male", label: "Male" },
  { value: "female", label: "Female" },
];

const PAYMENT_METHOD_OPTIONS = [
  { value: "insurance", label: "Insurance" },
  { value: "self_pay", label: "Self-pay" },
];

// The four stages the portal actually steps a patient through — a
// simplified, plain-language view of the request's real backend status
// (see _PATIENT_STAGE in care/api/patient_portal.py). Other outcomes
// (cancelled, expired, unable to match, in progress, completed) are shown
// as a plain status badge instead of this timeline.
const STAGE_TIMELINE: { key: string; label: string }[] = [
  { key: "request_received", label: "Request Received" },
  { key: "finding_therapist", label: "Finding Therapist" },
  { key: "therapist_matched", label: "Therapist Matched" },
  { key: "visit_scheduled", label: "Visit Scheduled" },
];

interface RequestDraft {
  requestedService: string;
  reasonForVisit: string;
  primaryCondition: string;
  specialtyRequested: string;
  addressLine1: string;
  addressLine2: string;
  city: string;
  state: string;
  zipCode: string;
  earliestDate: string;
  latestDate: string;
  preferredTimeWindow: string;
  providerGenderPreference: string;
  isNewPatient: boolean;
  paymentMethod: string;
  mobilityNotes: string;
  homeAccessNotes: string;
  notes: string;
}

function blankDraft(): RequestDraft {
  return {
    requestedService: "",
    reasonForVisit: "",
    primaryCondition: "",
    specialtyRequested: "",
    addressLine1: "",
    addressLine2: "",
    city: "",
    state: "",
    zipCode: "",
    earliestDate: new Date().toISOString().slice(0, 10),
    latestDate: "",
    preferredTimeWindow: "",
    providerGenderPreference: "no_preference",
    isNewPatient: false,
    paymentMethod: "insurance",
    mobilityNotes: "",
    homeAccessNotes: "",
    notes: "",
  };
}

const STEP_TITLES = [
  "Reason for visit",
  "Specialty",
  "Confirm visit address",
  "Preferred date",
  "Time window",
  "Preferences",
  "Review & submit",
];

export function PortalMobileCarePage() {
  const [requests, setRequests] = useState<PortalMobileCareRequest[] | null>(null);
  const [error, setError] = useState("");
  const [showWizard, setShowWizard] = useState(false);
  const [justSubmittedId, setJustSubmittedId] = useState<string | null>(null);

  async function load() {
    try {
      const result = await api.portalMobileCareRequests();
      setRequests(result.requests);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load your in-home PT requests."));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function cancel(requestId: string) {
    try {
      await api.portalCancelMobileCareRequest(requestId);
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to cancel this request."));
    }
  }

  const openStatuses = new Set(["pending", "matching", "provider_offered", "matched", "accepted", "scheduled", "in_progress"]);
  const open = (requests || []).filter((entry) => openStatuses.has(entry.status));
  const upcomingVisits = open.filter((entry) => entry.appointmentStartsAt);

  return (
    <>
      <h1>In-Home PT</h1>
      <p className="portal-empty">
        Request a physical therapy visit at your home. Our team will match you with a provider who covers your area
        and reach out to confirm a time.
      </p>

      {error && <p className="form-error" role="alert">{error}</p>}

      {!showWizard ? (
        <div className="portal-card">
          <h3>Request In-Home PT</h3>
          <p className="portal-empty">Tell us a bit about your visit — it only takes a minute.</p>
          <div className="button-row">
            <button className="primary-button" type="button" onClick={() => { setJustSubmittedId(null); setShowWizard(true); }}>
              Request In-Home PT
            </button>
          </div>
        </div>
      ) : (
        <RequestVisitWizard
          onCancel={() => setShowWizard(false)}
          onSubmitted={async (requestId) => {
            setShowWizard(false);
            setJustSubmittedId(requestId);
            await load();
          }}
        />
      )}

      {justSubmittedId && (
        <div className="portal-card">
          <p className="portal-section-heading">Request Received</p>
          <p className="portal-empty">
            We've received your request and are now finding a therapist who covers your area. You'll see your
            request's status update below as it progresses.
          </p>
        </div>
      )}

      <div>
        <p className="portal-section-heading">Your requests</p>
        {requests === null ? (
          <p className="portal-empty">Loading...</p>
        ) : open.length ? (
          <div style={{ display: "grid", gap: ".6rem", marginTop: ".6rem" }}>
            {open.map((entry) => (
              <RequestStatusCard key={entry.id} entry={entry} onCancel={() => void cancel(entry.id)} />
            ))}
          </div>
        ) : (
          <p className="portal-empty">No open in-home PT requests.</p>
        )}
      </div>

      <div>
        <p className="portal-section-heading">Upcoming home visits</p>
        {requests === null ? (
          <p className="portal-empty">Loading...</p>
        ) : upcomingVisits.length ? (
          <div style={{ display: "grid", gap: ".6rem", marginTop: ".6rem" }}>
            {upcomingVisits.map((entry) => (
              <div key={entry.id} className="portal-appointment-card">
                <header>
                  <div>
                    <strong>{entry.appointmentStartsAt ? formatDate(entry.appointmentStartsAt) : ""}{entry.appointmentStartsAt ? ` · ${formatTime(entry.appointmentStartsAt)}` : ""}</strong>
                    <div className="portal-empty">{entry.matchedProviderName || "Provider to be confirmed"}</div>
                  </div>
                  <span className="status-pill scheduled">{entry.stageLabel}</span>
                </header>
                {entry.visitInstructions && <p className="portal-empty">{entry.visitInstructions}</p>}
              </div>
            ))}
          </div>
        ) : (
          <p className="portal-empty">No upcoming home visits scheduled yet.</p>
        )}
      </div>
    </>
  );
}

/** One request's status card — the timeline (Request Received -> Finding
 * Therapist -> Therapist Matched -> Visit Scheduled) for the normal
 * happy path, or just a status badge for a cancelled/expired/unable-to-
 * match outcome. Shows only the patient-appropriate provider info
 * (name/credentials/specialty) once matched — never a match score or
 * ranking reason, which stay staff/provider-only. */
function RequestStatusCard({ entry, onCancel }: { entry: PortalMobileCareRequest; onCancel: () => void }) {
  const timelineIndex = STAGE_TIMELINE.findIndex((stage) => stage.key === entry.stage);
  return (
    <div className="portal-appointment-card">
      <header>
        <div>
          <strong>{entry.addressLine1}, {entry.city}, {entry.state} {entry.zipCode}</strong>
          <div className="portal-empty">
            {entry.requestedServiceLabel || "In-home PT visit"} · from {formatDate(entry.earliestDate)}
            {entry.latestDate ? ` to ${formatDate(entry.latestDate)}` : ""}
          </div>
        </div>
        <span className="status-pill scheduled">{entry.stageLabel}</span>
      </header>

      {timelineIndex >= 0 && (
        <ol style={{ display: "flex", flexWrap: "wrap", gap: ".5rem", margin: 0, padding: 0, listStyle: "none" }}>
          {STAGE_TIMELINE.map((stage, index) => (
            <li key={stage.key} className="portal-empty" style={index <= timelineIndex ? { color: "var(--sm-brand-deep)", fontWeight: 700 } : undefined}>
              {stage.label}{index < STAGE_TIMELINE.length - 1 ? " →" : ""}
            </li>
          ))}
        </ol>
      )}

      {entry.matchedProviderName && (
        <div className="portal-empty">
          Your therapist: {entry.matchedProviderName}
          {entry.matchedProviderCredentials ? `, ${entry.matchedProviderCredentials}` : ""}
          {entry.matchedProviderSpecialty ? ` · ${entry.matchedProviderSpecialty}` : ""}
        </div>
      )}

      {entry.appointmentStartsAt && (
        <div className="portal-empty">
          Visit scheduled: {formatDate(entry.appointmentStartsAt)} at {formatTime(entry.appointmentStartsAt)}
        </div>
      )}
      {entry.visitInstructions && <div className="portal-empty">{entry.visitInstructions}</div>}
      {entry.reasonForVisit && <div className="portal-empty">{entry.reasonForVisit}</div>}

      {entry.billingEstimate?.pricingConfigured && (
        <div className="portal-empty">
          <strong>Estimated cost</strong>
          <div>{entry.billingEstimate.servicePriceLabel} — ${entry.billingEstimate.servicePriceAmount}</div>
          {entry.billingEstimate.travelFeeAmount && (
            <div>{entry.billingEstimate.travelFeeLabel} — ${entry.billingEstimate.travelFeeAmount}</div>
          )}
          {entry.billingEstimate.packageApplied ? (
            <div>Covered by your {entry.billingEstimate.packageName} — you owe $0.00</div>
          ) : (
            <>
              {entry.billingEstimate.copayAmount && <div>Insurance copay on file: ${entry.billingEstimate.copayAmount}</div>}
              {entry.billingEstimate.depositAmount && <div>Deposit required: ${entry.billingEstimate.depositAmount}</div>}
              {entry.billingEstimate.patientResponsibility && (
                <div>Estimated amount you owe: ${entry.billingEstimate.patientResponsibility}</div>
              )}
            </>
          )}
        </div>
      )}

      {entry.canCancel && (
        <div className="button-row">
          <button className="text-action" onClick={onCancel}>Cancel request</button>
        </div>
      )}
    </div>
  );
}

/** The 7-screen "Request In-Home PT" wizard (reason -> specialty -> confirm
 * address -> date -> time window -> preferences -> review/submit). Step 3
 * offers a one-time copy-in from the patient's chart address — never a
 * live link — so the visit address can be confirmed as-is or overridden,
 * matching how this same non-duplication rule already works for staff. */
function RequestVisitWizard({ onCancel, onSubmitted }: { onCancel: () => void; onSubmitted: (requestId: string) => Promise<void> }) {
  const [step, setStep] = useState(1);
  const [draft, setDraft] = useState<RequestDraft>(blankDraft);
  const [chartAddress, setChartAddress] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.portalProfile().then((result) => setChartAddress(result.profile.address || "")).catch(() => undefined);
  }, []);

  function update<K extends keyof RequestDraft>(key: K, value: RequestDraft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  const canAdvance =
    step === 3 ? Boolean(draft.addressLine1 && draft.city && draft.state && draft.zipCode) :
    step === 4 ? Boolean(draft.earliestDate) :
    true;

  async function submit() {
    setSubmitting(true);
    setError("");
    try {
      const result = await api.portalCreateMobileCareRequest({
        addressLine1: draft.addressLine1,
        addressLine2: draft.addressLine2.trim() || undefined,
        city: draft.city,
        state: draft.state,
        zipCode: draft.zipCode,
        reasonForVisit: draft.reasonForVisit.trim() || undefined,
        notes: draft.notes.trim() || undefined,
        earliestDate: draft.earliestDate,
        latestDate: draft.latestDate || undefined,
        requestedService: draft.requestedService || undefined,
        preferredTimeWindow: draft.preferredTimeWindow || undefined,
        primaryCondition: draft.primaryCondition.trim() || undefined,
        specialtyRequested: draft.specialtyRequested.trim() || undefined,
        providerGenderPreference: draft.providerGenderPreference,
        isNewPatient: draft.isNewPatient,
        paymentMethod: draft.paymentMethod,
        mobilityNotes: draft.mobilityNotes.trim() || undefined,
        homeAccessNotes: draft.homeAccessNotes.trim() || undefined,
      });
      await onSubmitted(result.request.id);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to submit your request."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="portal-card">
      <p className="portal-empty">Step {step} of {STEP_TITLES.length}</p>
      <h3>{STEP_TITLES[step - 1]}</h3>

      <div style={{ display: "grid", gap: ".75rem" }}>
        {step === 1 && (
          <>
            <label>
              <span>What kind of visit?</span>
              <select value={draft.requestedService} onChange={(event) => update("requestedService", event.target.value)}>
                {REQUESTED_SERVICE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Reason for visit (optional)</span>
              <input value={draft.reasonForVisit} onChange={(event) => update("reasonForVisit", event.target.value)} maxLength={240} />
            </label>
            <label>
              <span>Primary condition (optional)</span>
              <input value={draft.primaryCondition} onChange={(event) => update("primaryCondition", event.target.value)} maxLength={240} />
            </label>
          </>
        )}

        {step === 2 && (
          <label>
            <span>Specialty requested (optional)</span>
            <input
              value={draft.specialtyRequested}
              onChange={(event) => update("specialtyRequested", event.target.value)}
              placeholder="e.g. orthopedics, neuro, pediatrics"
              maxLength={120}
            />
          </label>
        )}

        {step === 3 && (
          <>
            {chartAddress && (
              <p className="portal-empty">
                Address on file: {chartAddress}{" "}
                <button type="button" className="text-action" onClick={() => update("addressLine1", chartAddress)}>
                  Use this address
                </button>
              </p>
            )}
            <label>
              <span>Street address</span>
              <input value={draft.addressLine1} onChange={(event) => update("addressLine1", event.target.value)} required maxLength={200} />
            </label>
            <label>
              <span>Apartment / unit (optional)</span>
              <input value={draft.addressLine2} onChange={(event) => update("addressLine2", event.target.value)} maxLength={200} />
            </label>
            <label>
              <span>City</span>
              <input value={draft.city} onChange={(event) => update("city", event.target.value)} required maxLength={120} />
            </label>
            <label>
              <span>State</span>
              <input value={draft.state} onChange={(event) => update("state", event.target.value)} required maxLength={80} />
            </label>
            <label>
              <span>ZIP code</span>
              <input value={draft.zipCode} onChange={(event) => update("zipCode", event.target.value)} required pattern="\d{5}" maxLength={5} placeholder="12345" />
            </label>
          </>
        )}

        {step === 4 && (
          <>
            <label>
              <span>Preferred date</span>
              <input type="date" value={draft.earliestDate} onChange={(event) => update("earliestDate", event.target.value)} required />
            </label>
            <label>
              <span>Latest date you're available (optional)</span>
              <input type="date" value={draft.latestDate} onChange={(event) => update("latestDate", event.target.value)} />
            </label>
          </>
        )}

        {step === 5 && (
          <label>
            <span>Preferred time of day</span>
            <select value={draft.preferredTimeWindow} onChange={(event) => update("preferredTimeWindow", event.target.value)}>
              {TIME_WINDOW_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
        )}

        {step === 6 && (
          <>
            <label>
              <span>Provider gender preference</span>
              <select value={draft.providerGenderPreference} onChange={(event) => update("providerGenderPreference", event.target.value)}>
                {GENDER_PREFERENCE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Are you a new or existing patient here?</span>
              <select value={draft.isNewPatient ? "new" : "existing"} onChange={(event) => update("isNewPatient", event.target.value === "new")}>
                <option value="existing">Existing patient</option>
                <option value="new">New patient</option>
              </select>
            </label>
            <label>
              <span>How will this visit be paid for?</span>
              <select value={draft.paymentMethod} onChange={(event) => update("paymentMethod", event.target.value)}>
                {PAYMENT_METHOD_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Mobility / access needs (optional)</span>
              <input value={draft.mobilityNotes} onChange={(event) => update("mobilityNotes", event.target.value)} placeholder="e.g. I use a walker" maxLength={500} />
            </label>
            <label>
              <span>Home access notes (optional)</span>
              <input value={draft.homeAccessNotes} onChange={(event) => update("homeAccessNotes", event.target.value)} placeholder="e.g. gate code, parking" maxLength={500} />
            </label>
            <label>
              <span>Additional comments (optional)</span>
              <input value={draft.notes} onChange={(event) => update("notes", event.target.value)} placeholder="e.g. mornings preferred" maxLength={500} />
            </label>
          </>
        )}

        {step === 7 && (
          <div style={{ display: "grid", gap: ".4rem" }}>
            <p className="portal-empty"><strong>Visit:</strong> {REQUESTED_SERVICE_OPTIONS.find((o) => o.value === draft.requestedService)?.label || "Not sure yet"}{draft.reasonForVisit ? ` — ${draft.reasonForVisit}` : ""}</p>
            {draft.specialtyRequested && <p className="portal-empty"><strong>Specialty:</strong> {draft.specialtyRequested}</p>}
            <p className="portal-empty"><strong>Address:</strong> {draft.addressLine1}{draft.addressLine2 ? `, ${draft.addressLine2}` : ""}, {draft.city}, {draft.state} {draft.zipCode}</p>
            <p className="portal-empty"><strong>Date:</strong> from {formatDate(draft.earliestDate)}{draft.latestDate ? ` to ${formatDate(draft.latestDate)}` : ""}</p>
            <p className="portal-empty"><strong>Time window:</strong> {TIME_WINDOW_OPTIONS.find((o) => o.value === draft.preferredTimeWindow)?.label || "No preference"}</p>
            <p className="portal-empty"><strong>Preferences:</strong> {GENDER_PREFERENCE_OPTIONS.find((o) => o.value === draft.providerGenderPreference)?.label}, {draft.isNewPatient ? "new patient" : "existing patient"}, {PAYMENT_METHOD_OPTIONS.find((o) => o.value === draft.paymentMethod)?.label}</p>
            {draft.mobilityNotes && <p className="portal-empty"><strong>Mobility/access:</strong> {draft.mobilityNotes}</p>}
            {draft.homeAccessNotes && <p className="portal-empty"><strong>Home access:</strong> {draft.homeAccessNotes}</p>}
            {draft.notes && <p className="portal-empty"><strong>Comments:</strong> {draft.notes}</p>}
          </div>
        )}

        {error && <p className="form-error" role="alert">{error}</p>}

        <div className="button-row">
          <button className="secondary-button" type="button" onClick={step === 1 ? onCancel : () => setStep((s) => s - 1)} disabled={submitting}>
            {step === 1 ? "Cancel" : "Back"}
          </button>
          {step < STEP_TITLES.length ? (
            <button className="primary-button" type="button" onClick={() => setStep((s) => s + 1)} disabled={!canAdvance}>
              Next
            </button>
          ) : (
            <button className="primary-button" type="button" onClick={() => void submit()} disabled={submitting}>
              {submitting ? "Submitting..." : "Submit request"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
