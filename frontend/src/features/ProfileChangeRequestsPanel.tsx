import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ProfileChangeRequestStaff } from "../api/types";
import { formatDate } from "../lib/format";

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

const FIELD_LABELS: Record<string, string> = {
  phone: "Phone",
  email: "Email",
  address: "Address",
  emergency_contact: "Emergency contact",
};

/** Staff review queue for patient-submitted contact-info changes — nothing
 * here writes to a chart until a scheduler/clinician explicitly approves it. */
export function ProfileChangeRequestsPanel() {
  const [requests, setRequests] = useState<ProfileChangeRequestStaff[] | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [busyId, setBusyId] = useState("");

  async function load() {
    try {
      setRequests((await api.profileChangeRequestsStaffList()).requests);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load profile change requests."));
    }
  }

  useEffect(() => {
    if (open) void load();
  }, [open]);

  async function decide(requestId: string, decision: "approve" | "reject") {
    setBusyId(requestId);
    try {
      await api.decideProfileChangeRequest(requestId, decision);
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to record this decision."));
    } finally {
      setBusyId("");
    }
  }

  return (
    <section className="surface-card">
      <header className="card-heading">
        <div>
          <p className="eyebrow">Portal requests</p>
          <h2>Profile changes{requests && requests.length ? ` (${requests.length})` : ""}</h2>
        </div>
        <button className="secondary-button" type="button" onClick={() => setOpen((value) => !value)}>
          {open ? "Hide" : "Show"}
        </button>
      </header>
      {open && (
        <>
          {error && <p className="form-error" role="alert">{error}</p>}
          {!requests && !error && <p className="muted">Loading…</p>}
          {requests && requests.length === 0 && <p className="muted">No pending profile change requests.</p>}
          {requests && requests.length > 0 && (
            <ul className="summary-list">
              {requests.map((request) => (
                <li key={request.id}>
                  <span>
                    <strong>{request.patient.fullName}</strong>
                    <small>Requested {formatDate(request.createdAt)}</small>
                    {Object.entries(request.changes).map(([field, value]) => (
                      <small key={field}>{FIELD_LABELS[field] || field}: {value}</small>
                    ))}
                  </span>
                  <span className="button-row">
                    <button
                      className="secondary-button"
                      type="button"
                      disabled={busyId === request.id}
                      onClick={() => void decide(request.id, "approve")}
                    >
                      Approve
                    </button>
                    <button
                      className="text-action"
                      type="button"
                      disabled={busyId === request.id}
                      onClick={() => void decide(request.id, "reject")}
                    >
                      Reject
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
