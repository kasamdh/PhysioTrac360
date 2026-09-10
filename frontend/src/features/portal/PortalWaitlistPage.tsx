import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { PortalWaitlistEntry, PublicLocation } from "../../api/types";
import { formatDate } from "../../lib/format";

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

export function PortalWaitlistPage() {
  const [entries, setEntries] = useState<PortalWaitlistEntry[] | null>(null);
  const [locations, setLocations] = useState<PublicLocation[]>([]);
  const [locationId, setLocationId] = useState("");
  const [earliestDate, setEarliestDate] = useState(new Date().toISOString().slice(0, 10));
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function load() {
    try {
      const result = await api.portalWaitlist();
      setEntries(result.entries);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load your waitlist requests."));
    }
  }

  useEffect(() => {
    void load();
    api.portalBookingLocations().then((result) => setLocations(result.locations));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await api.portalJoinWaitlist({ locationId: locationId || undefined, earliestDate, notes: notes.trim() || undefined });
      setNotes("");
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to join the waitlist."));
    } finally {
      setSubmitting(false);
    }
  }

  async function leave(entryId: string) {
    try {
      await api.portalLeaveWaitlist(entryId);
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to remove this waitlist request."));
    }
  }

  const active = (entries || []).filter((entry) => entry.status === "active");

  return (
    <>
      <h1>Waitlist</h1>
      <p className="portal-empty">
        Ask to be seen sooner. We'll call you if an earlier opening matches your preferences.
      </p>

      <div className="portal-card">
        <h3>Request an earlier opening</h3>
        <form onSubmit={submit} style={{ display: "grid", gap: ".75rem" }}>
          <label>
            <span>Location (optional)</span>
            <select value={locationId} onChange={(event) => setLocationId(event.target.value)}>
              <option value="">Any location</option>
              {locations.map((location) => (
                <option key={location.id} value={location.id}>{location.name}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Earliest date you're available</span>
            <input type="date" value={earliestDate} onChange={(event) => setEarliestDate(event.target.value)} required />
          </label>
          <label>
            <span>Notes (optional)</span>
            <input value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="e.g. mornings preferred" maxLength={240} />
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="button-row">
            <button className="primary-button" type="submit" disabled={submitting}>
              {submitting ? "Joining..." : "Join waitlist"}
            </button>
          </div>
        </form>
      </div>

      <div>
        <p className="portal-section-heading">Your active requests</p>
        {entries === null ? (
          <p className="portal-empty">Loading...</p>
        ) : active.length ? (
          <div style={{ display: "grid", gap: ".6rem", marginTop: ".6rem" }}>
            {active.map((entry) => (
              <div key={entry.id} className="portal-appointment-card">
                <header>
                  <div>
                    <strong>{entry.location || "Any location"}{entry.appointmentType ? ` · ${entry.appointmentType}` : ""}</strong>
                    <div className="portal-empty">
                      From {formatDate(entry.earliestDate)}{entry.latestDate ? ` to ${formatDate(entry.latestDate)}` : ""}
                      {entry.providerName ? ` · ${entry.providerName}` : ""}
                    </div>
                    {entry.notes && <div className="portal-empty">{entry.notes}</div>}
                  </div>
                </header>
                <div className="button-row">
                  <button className="text-action" onClick={() => void leave(entry.id)}>Remove</button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="portal-empty">No active waitlist requests.</p>
        )}
      </div>
    </>
  );
}
