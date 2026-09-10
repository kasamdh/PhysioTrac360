import { useEffect, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { PortalAppointment, PortalAppointmentsList } from "../../api/types";
import { formatDate, formatTime } from "../../lib/format";
import { PortalReschedulePanel } from "./PortalReschedulePanel";

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function AppointmentCard({
  appointment,
  onChanged,
}: {
  appointment: PortalAppointment;
  onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reschedulingOpen, setReschedulingOpen] = useState(false);
  const [joinMessage, setJoinMessage] = useState("");

  async function join() {
    setBusy(true);
    setError("");
    setJoinMessage("");
    try {
      const result = await api.portalJoinTelehealth(appointment.id);
      if (result.joinable && result.joinUrl) {
        window.open(result.joinUrl, "_blank", "noopener,noreferrer");
      } else {
        setJoinMessage(result.message);
      }
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to join this visit."));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!window.confirm("Cancel this appointment?")) return;
    setBusy(true);
    setError("");
    try {
      await api.portalCancelAppointment(appointment.id);
      await onChanged();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to cancel this appointment."));
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await api.portalConfirmAppointment(appointment.id);
      await onChanged();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to confirm this appointment."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="portal-appointment-card">
      <header>
        <div>
          <strong>{formatDate(appointment.date)} · {formatTime(appointment.startsAt)}</strong>
          <div className="portal-empty">
            {appointment.kindLabel} with {appointment.providerName}
            {appointment.isTelehealth ? " · Telehealth" : appointment.location ? ` · ${appointment.location}` : ""}
          </div>
        </div>
        <span className={`status-pill ${appointment.status}`}>{appointment.statusLabel}</span>
      </header>
      {appointment.confirmedAt && <p className="portal-empty">Confirmed on {formatDate(appointment.confirmedAt)}.</p>}
      {appointment.isTelehealth && appointment.canJoinTelehealth && (
        <div className="button-row">
          <button className="primary-button" disabled={busy} onClick={() => void join()}>
            {busy ? "Joining..." : "Join Visit"}
          </button>
        </div>
      )}
      {joinMessage && <p className="form-notice" role="status">{joinMessage}</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
      {reschedulingOpen ? (
        <PortalReschedulePanel
          appointment={appointment}
          onCancel={() => setReschedulingOpen(false)}
          onRescheduled={async () => {
            setReschedulingOpen(false);
            await onChanged();
          }}
        />
      ) : (
        (appointment.canCancel || appointment.canReschedule || appointment.canConfirm) && (
          <div className="button-row">
            {appointment.canConfirm && (
              <button className="secondary-button" disabled={busy} onClick={() => void confirm()}>
                Confirm visit
              </button>
            )}
            {appointment.canReschedule && (
              <button className="secondary-button" disabled={busy} onClick={() => setReschedulingOpen(true)}>
                Reschedule
              </button>
            )}
            {appointment.canCancel && (
              <button className="text-action" disabled={busy} onClick={() => void cancel()}>
                Cancel
              </button>
            )}
          </div>
        )
      )}
      {!reschedulingOpen &&
        appointment.status === "scheduled" &&
        !appointment.canCancel &&
        !appointment.canReschedule && (
          <p className="portal-empty">This appointment is too close to change online — please call the clinic.</p>
        )}
    </div>
  );
}

export function PortalAppointmentsPage() {
  const [data, setData] = useState<PortalAppointmentsList | null>(null);
  const [error, setError] = useState("");

  async function load() {
    try {
      setData(await api.portalAppointments());
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load your appointments."));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  if (error) return <p className="form-error" role="alert">{error}</p>;
  if (!data) return <p className="portal-empty">Loading your appointments...</p>;

  return (
    <>
      <h1>My Appointments</h1>

      <div>
        <p className="portal-section-heading">Upcoming</p>
        {data.upcoming.length ? (
          <div style={{ display: "grid", gap: ".75rem", marginTop: ".6rem" }}>
            {data.upcoming.map((appointment) => (
              <AppointmentCard key={appointment.id} appointment={appointment} onChanged={load} />
            ))}
          </div>
        ) : (
          <p className="portal-empty">No upcoming appointments.</p>
        )}
      </div>

      <div>
        <p className="portal-section-heading">Past visits</p>
        {data.past.length ? (
          <div style={{ display: "grid", gap: ".75rem", marginTop: ".6rem" }}>
            {data.past.map((appointment) => (
              <div key={appointment.id} className="portal-appointment-card">
                <header>
                  <div>
                    <strong>{formatDate(appointment.date)} · {formatTime(appointment.startsAt)}</strong>
                    <div className="portal-empty">
                      {appointment.kindLabel} with {appointment.providerName}
                    </div>
                  </div>
                  <span className={`status-pill ${appointment.status}`}>{appointment.statusLabel}</span>
                </header>
              </div>
            ))}
          </div>
        ) : (
          <p className="portal-empty">No past visits yet.</p>
        )}
      </div>
    </>
  );
}
