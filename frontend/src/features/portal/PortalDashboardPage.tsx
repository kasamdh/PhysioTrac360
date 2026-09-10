import { useEffect, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { PortalAppointment, PortalDashboard } from "../../api/types";
import { formatDate, formatTime } from "../../lib/format";

function AppointmentRow({ appointment }: { appointment: PortalAppointment }) {
  return (
    <li>
      <span>
        <strong>{formatDate(appointment.date)} · {formatTime(appointment.startsAt)}</strong>
        <small>
          {appointment.kindLabel} with {appointment.providerName}
          {appointment.isTelehealth ? " · Telehealth" : appointment.location ? ` · ${appointment.location}` : ""}
        </small>
      </span>
      <span className={`status-pill ${appointment.status}`}>{appointment.statusLabel}</span>
    </li>
  );
}

interface PortalDashboardPageProps {
  onNavigate: (page: "appointments" | "book" | "forms" | "documents" | "hep" | "outcomes" | "messages" | "payments") => void;
}

export function PortalDashboardPage({ onNavigate }: PortalDashboardPageProps) {
  const [dashboard, setDashboard] = useState<PortalDashboard | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api
      .portalDashboard()
      .then((result) => active && setDashboard(result))
      .catch((requestError) => active && setError(requestError instanceof ApiError ? requestError.message : "Unable to load your dashboard."))
      .finally(() => {});
    return () => {
      active = false;
    };
  }, []);

  if (error) return <p className="form-error" role="alert">{error}</p>;
  if (!dashboard) return <p className="portal-empty">Loading your dashboard...</p>;

  return (
    <>
      <div>
        <p className="eyebrow">Welcome back</p>
        <h1>{dashboard.patient.firstName}</h1>
      </div>

      <div className="portal-card">
        <p className="eyebrow">Next appointment</p>
        {dashboard.nextAppointment ? (
          <ul className="record-list"><AppointmentRow appointment={dashboard.nextAppointment} /></ul>
        ) : <p className="portal-empty">No upcoming appointment scheduled.</p>}
        <div className="button-row" style={{ marginTop: ".75rem" }}>
          <button className="secondary-button" onClick={() => onNavigate("appointments")}>My appointments</button>
          <button className="primary-button" onClick={() => onNavigate("book")}>Book a visit</button>
        </div>
      </div>

      <div className="portal-dashboard-grid">
        <div className="portal-card">
          <h3>Upcoming appointments</h3>
          {dashboard.upcomingAppointments.length ? (
            <ul className="record-list">{dashboard.upcomingAppointments.map((appointment) => <AppointmentRow key={appointment.id} appointment={appointment} />)}</ul>
          ) : <p className="portal-empty">Nothing else on the calendar right now.</p>}
        </div>

        <div className="portal-card">
          <h3>Outstanding balance</h3>
          <p style={{ fontSize: "1.75rem", fontWeight: 700, margin: "0 0 .25rem" }}>${dashboard.outstandingBalance}</p>
          <p className="portal-empty">{Number(dashboard.outstandingBalance) > 0 ? "View invoices or pay online." : "You're all caught up."}</p>
          <div className="button-row" style={{ marginTop: ".5rem" }}>
            <button className="secondary-button" onClick={() => onNavigate("payments")}>View payments</button>
          </div>
        </div>

        <div className="portal-card">
          <h3>Messages</h3>
          <p className="portal-empty">{dashboard.newMessageCount > 0 ? `${dashboard.newMessageCount} new message${dashboard.newMessageCount === 1 ? "" : "s"}` : "No new messages."}</p>
          <div className="button-row" style={{ marginTop: ".5rem" }}>
            <button className="secondary-button" onClick={() => onNavigate("messages")}>View messages</button>
          </div>
        </div>

        <div className="portal-card">
          <h3>Home exercise program</h3>
          {dashboard.homeExerciseProgram ? (
            <>
              <p className="portal-empty">{dashboard.homeExerciseProgram.title} · {dashboard.homeExerciseProgram.exerciseCount} exercise{dashboard.homeExerciseProgram.exerciseCount === 1 ? "" : "s"}</p>
              <div className="button-row" style={{ marginTop: ".5rem" }}>
                <button className="secondary-button" onClick={() => onNavigate("hep")}>View exercises</button>
              </div>
            </>
          ) : <p className="portal-empty">No active home exercise program.</p>}
        </div>

        <div className="portal-card">
          <h3>Forms due</h3>
          {dashboard.formsDue.length ? (
            <ul className="record-list">
              {dashboard.formsDue.map((form) => (
                <li key={form.templateSlug}>
                  <span><strong>{form.name}</strong></span>
                  <span className={`status-pill ${form.status}`}>{form.status === "expired" ? "Expired" : form.status === "in_progress" ? "In progress" : "Not started"}</span>
                </li>
              ))}
            </ul>
          ) : <p className="portal-empty">Nothing due right now.</p>}
          {dashboard.formsDue.length > 0 && (
            <div className="button-row" style={{ marginTop: ".5rem" }}>
              <button className="secondary-button" onClick={() => onNavigate("forms")}>Complete forms</button>
            </div>
          )}
        </div>

        <div className="portal-card">
          <h3>Outcome measures due</h3>
          {dashboard.outcomeMeasuresDue.length ? (
            <ul className="record-list">
              {dashboard.outcomeMeasuresDue.map((assignment) => (
                <li key={assignment.id}>
                  <span><strong>{assignment.measureLabel}</strong></span>
                </li>
              ))}
            </ul>
          ) : <p className="portal-empty">Nothing due right now.</p>}
          {dashboard.outcomeMeasuresDue.length > 0 && (
            <div className="button-row" style={{ marginTop: ".5rem" }}>
              <button className="secondary-button" onClick={() => onNavigate("outcomes")}>Complete now</button>
            </div>
          )}
        </div>

        <div className="portal-card">
          <h3>Recent documents</h3>
          {dashboard.recentDocuments.length ? (
            <ul className="record-list">
              {dashboard.recentDocuments.map((document) => (
                <li key={document.id}>
                  <span><strong>{document.title}</strong><small>{formatDate(document.uploadedAt)}</small></span>
                </li>
              ))}
            </ul>
          ) : <p className="portal-empty">No documents shared yet.</p>}
          <div className="button-row" style={{ marginTop: ".5rem" }}>
            <button className="secondary-button" onClick={() => onNavigate("documents")}>View documents</button>
          </div>
        </div>

        <div className="portal-card">
          <h3>Notifications</h3>
          {dashboard.notifications.length ? (
            <ul className="record-list">
              {dashboard.notifications.map((notification) => (
                <li key={notification.id}>
                  <span><strong>New {notification.categoryLabel.toLowerCase()} message</strong><small>{formatDate(notification.receivedAt)}</small></span>
                </li>
              ))}
            </ul>
          ) : <p className="portal-empty">You're all caught up.</p>}
        </div>
      </div>
    </>
  );
}
