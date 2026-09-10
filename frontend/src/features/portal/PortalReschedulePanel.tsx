import { useEffect, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { PortalAppointment, PublicProviderSlots } from "../../api/types";

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00`);
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

function formatTime(iso: string): string {
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(new Date(iso));
}

interface PortalReschedulePanelProps {
  appointment: PortalAppointment;
  onCancel: () => void;
  onRescheduled: () => Promise<void>;
}

export function PortalReschedulePanel({ appointment, onCancel, onRescheduled }: PortalReschedulePanelProps) {
  const [date, setDate] = useState(todayIso());
  const [slots, setSlots] = useState<PublicProviderSlots[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedStart, setSelectedStart] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const locationId = appointment.locationId || "";
  const appointmentTypeId = appointment.appointmentTypeId || "";
  const providerId = appointment.providerId || "";

  useEffect(() => {
    if (!locationId || !appointmentTypeId) return;
    let active = true;
    setLoading(true);
    setSelectedStart("");
    api
      .portalBookingAvailability(locationId, appointmentTypeId, date, providerId, appointment.id)
      .then((result) => active && setSlots(result.providers))
      .catch((requestError) => active && setError(requestMessage(requestError, "Unable to load open times.")))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [locationId, appointmentTypeId, providerId, appointment.id, date]);

  async function submit() {
    if (!selectedStart) return;
    setSubmitting(true);
    setError("");
    try {
      await api.portalRescheduleAppointment(appointment.id, selectedStart);
      await onRescheduled();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to reschedule this appointment."));
    } finally {
      setSubmitting(false);
    }
  }

  if (!locationId || !appointmentTypeId) {
    return (
      <div>
        <p className="portal-empty">This appointment can't be rescheduled online. Please call the clinic.</p>
        <button className="secondary-button" onClick={onCancel}>Close</button>
      </div>
    );
  }

  const allSlots = slots.flatMap((entry) => entry.slots);

  return (
    <div style={{ display: "grid", gap: ".6rem" }}>
      <div className="booking-date-nav">
        <button className="secondary-button" onClick={() => setDate((current) => addDays(current, -1))} disabled={date <= todayIso()}>
          ← Earlier
        </button>
        <input type="date" value={date} min={todayIso()} onChange={(event) => setDate(event.target.value)} />
        <button className="secondary-button" onClick={() => setDate((current) => addDays(current, 1))}>Later →</button>
      </div>
      {loading && <p className="portal-empty">Loading open times...</p>}
      {!loading && allSlots.length === 0 && <p className="portal-empty">No open times on this date. Try another day.</p>}
      <div className="booking-slot-grid">
        {allSlots.map((slot) => (
          <button
            key={slot.start}
            className={`booking-slot-chip${selectedStart === slot.start ? " selected" : ""}`}
            onClick={() => setSelectedStart(slot.start)}
          >
            {formatTime(slot.start)}
          </button>
        ))}
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="button-row">
        <button className="secondary-button" onClick={onCancel} disabled={submitting}>Nevermind</button>
        <button className="primary-button" disabled={!selectedStart || submitting} onClick={() => void submit()}>
          {submitting ? "Saving..." : "Confirm new time"}
        </button>
      </div>
    </div>
  );
}
