import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { PortalWaitlistStaffEntry } from "../api/types";
import { formatDate } from "../lib/format";

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

/** Front-desk visibility into portal waitlist requests — read the request,
 * call the patient, then book them normally; marking an entry fulfilled or
 * removed here doesn't create an appointment on its own. */
export function WaitlistPanel() {
  const [entries, setEntries] = useState<PortalWaitlistStaffEntry[] | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);

  async function load() {
    try {
      setEntries((await api.waitlistStaffList()).entries);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load the waitlist."));
    }
  }

  useEffect(() => {
    if (open) void load();
  }, [open]);

  async function updateStatus(entryId: string, status: "fulfilled" | "cancelled") {
    try {
      await api.waitlistStaffUpdateStatus(entryId, status);
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to update this waitlist entry."));
    }
  }

  return (
    <section className="surface-card">
      <header className="card-heading">
        <div>
          <p className="eyebrow">Portal requests</p>
          <h2>Waitlist{entries && entries.length ? ` (${entries.length})` : ""}</h2>
        </div>
        <button className="secondary-button" type="button" onClick={() => setOpen((value) => !value)}>
          {open ? "Hide" : "Show"}
        </button>
      </header>
      {open && (
        <>
          {error && <p className="form-error" role="alert">{error}</p>}
          {!entries && !error && <p className="muted">Loading…</p>}
          {entries && entries.length === 0 && <p className="muted">No active waitlist requests.</p>}
          {entries && entries.length > 0 && (
            <ul className="summary-list">
              {entries.map((entry) => (
                <li key={entry.id}>
                  <span>
                    <strong>{entry.patient.fullName}</strong>
                    <small>
                      {entry.location || "Any location"}
                      {entry.appointmentType ? ` · ${entry.appointmentType}` : ""}
                      {entry.providerName ? ` · ${entry.providerName}` : ""} · from {formatDate(entry.earliestDate)}
                      {entry.latestDate ? ` to ${formatDate(entry.latestDate)}` : ""}
                    </small>
                    {entry.notes && <small>{entry.notes}</small>}
                  </span>
                  <span className="button-row">
                    <button className="secondary-button" type="button" onClick={() => void updateStatus(entry.id, "fulfilled")}>
                      Mark fulfilled
                    </button>
                    <button className="text-action" type="button" onClick={() => void updateStatus(entry.id, "cancelled")}>
                      Remove
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
