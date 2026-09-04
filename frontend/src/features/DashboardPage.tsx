import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { DashboardData } from "../api/types";
import { formatDate, formatTime } from "../lib/format";

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api.dashboard()
      .then((payload) => active && setData(payload))
      .catch((requestError) => {
        if (active) {
          setError(requestError instanceof ApiError ? requestError.message : "Unable to load the dashboard.");
        }
      });
    return () => {
      active = false;
    };
  }, []);

  if (error) {
    return <section className="page-error" role="alert"><h1>Workspace unavailable</h1><p>{error}</p></section>;
  }
  if (!data) {
    return <section className="page-loading" aria-live="polite">Loading today’s workspace…</section>;
  }

  const metrics = [
    ["◷", data.metrics.appointments, "Visits today", "crimson"],
    ["▤", data.metrics.pendingNotes, "Notes awaiting review", "amber"],
    ["⌁", data.metrics.dueReassessments, "Reassessments due", "purple"],
    ["✉", data.metrics.unreadMessages, "Secure messages", "green"],
  ];

  return (
    <div className="page-content">
      <header className="page-header">
        <div>
          <p className="eyebrow">Today · {formatDate(data.today, { weekday: "long" })}</p>
          <h1>Today</h1>
            <p>Run your day from one connected workspace for documentation, scheduling, payments, billing, and patient communication.</p>
        </div>
      </header>

      <section className="metric-grid" aria-label="Today at a glance">
        {metrics.map(([icon, value, label, tone]) => (
          <article className="metric-card" key={String(label)}>
            <span className={`metric-icon ${tone}`}>{icon}</span>
            <span><strong>{value}</strong><small>{label}</small></span>
          </article>
        ))}
      </section>

      <section className="platform-panel" aria-labelledby="platform-title">
        <header className="card-heading">
          <div>
            <p className="eyebrow">Practice platform</p>
            <h2 id="platform-title">Everything your team needs in one place</h2>
            <p className="muted">Connected workflows for the clinical, operational, and financial side of care.</p>
          </div>
          <span className="platform-badge">All-in-one workspace</span>
        </header>
        <div className="platform-grid">
          {[
            ["01", "Documentation", "Fast PT notes, progress tracking, and clinician-reviewed drafts.", "Live", "crimson"],
            ["02", "Scheduling", "Day, week, work-week, and month views with home-visit support.", "Live", "teal"],
            ["03", "Patient payments", "Record payment status with processor references and no card data.", "Live", "green"],
            ["04", "Billing", "Create superbills and keep service charges connected to the chart.", "Live", "amber"],
            ["05", "Patient communication", "Keep secure messages and care context together in the patient workspace.", "Live", "blue"],
          ].map(([number, title, detail, status, tone]) => (
            <article className={`platform-item ${tone}`} key={title}>
              <span className="platform-number">{number}</span>
              <div><strong>{title}</strong><p>{detail}</p></div>
              <span className="platform-status">{status}</span>
            </article>
          ))}
        </div>
      </section>

      <section className="content-grid">
        <article className="surface-card">
          <header className="card-heading"><div><p className="eyebrow">Schedule</p><h2>Today’s visits</h2></div></header>
          {data.appointments.length ? (
            <ul className="appointment-list">
              {data.appointments.map((appointment) => (
                <li key={appointment.id}>
                  <time>{formatTime(appointment.startsAt)}</time>
                  <span><strong>{appointment.patient.fullName}</strong><small>{appointment.kindLabel} · {appointment.isHomeVisit ? "Home visit" : appointment.location || "Location pending"}</small></span>
                  <span className={`status-pill ${appointment.status}`}>{appointment.statusLabel}</span>
                </li>
              ))}
            </ul>
          ) : <p className="empty-copy">No visits scheduled for this day.</p>}
        </article>

        <article className="surface-card">
          <header className="card-heading"><div><p className="eyebrow">Safety queue</p><h2>Needs attention</h2></div></header>
          {data.alerts.length ? (
            <ul className="attention-list">
              {data.alerts.map((alert) => (
                <li key={`${alert.patientId}-${alert.code}`}>
                  <span className={`severity-dot ${alert.severity}`} />
                  <span><strong>{alert.title}</strong><small>{alert.patientName} · {alert.detail}</small></span>
                </li>
              ))}
            </ul>
          ) : <p className="empty-copy positive">No documentation alerts need attention.</p>}
        </article>
      </section>

      <section className="content-grid">
        <article className="surface-card">
          <header className="card-heading"><div><p className="eyebrow">Documentation</p><h2>Draft notes</h2></div></header>
          {data.pendingNotes.length ? (
            <ul className="compact-list">
              {data.pendingNotes.map((note) => <li key={note.id}><span><strong>{note.patientName}</strong><small>{note.noteTypeLabel} · {formatDate(note.serviceDate, { month: "short", day: "numeric" })}</small></span><span>{note.statusLabel}</span></li>)}
            </ul>
          ) : <p className="empty-copy">No draft notes in your scope.</p>}
        </article>
        <article className="surface-card">
          <header className="card-heading"><div><p className="eyebrow">Clinical drafts</p><h2>Therapist review required</h2></div></header>
          {data.drafts.length ? (
            <ul className="compact-list">
              {data.drafts.map((draft) => <li key={draft.id}><span><strong>{draft.kindLabel}</strong><small>{draft.patientName} · {formatDate(draft.createdAt, { month: "short", day: "numeric" })}</small></span><span>Review</span></li>)}
            </ul>
          ) : <p className="empty-copy">No clinical drafts awaiting review.</p>}
        </article>
      </section>
    </div>
  );
}
