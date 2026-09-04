import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { AuditEvent } from "../api/types";
import { formatDate } from "../lib/format";

export function SafetyPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    api.auditEvents()
      .then((payload) => active && setEvents(payload.events))
      .catch((requestError) => {
        if (active) {
          setError(requestError instanceof ApiError ? requestError.message : "Unable to load audit history.");
        }
      })
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  return <div className="page-content">
    <header className="page-header"><div><p className="eyebrow">Safety & compliance</p><h1>Audit and safeguards</h1><p>Review application audit history and the controls that remain server-authoritative.</p></div></header>
    <section className="safety-grid safety-page-grid">
      <article className="surface-card"><strong>Access boundary</strong><small>Organization, role, and patient scope are enforced by Django on every protected request.</small></article>
      <article className="surface-card"><strong>Therapist approval</strong><small>Clinical drafts, goals, and home programs stay non-final until an authorized therapist reviews them.</small></article>
      <article className="surface-card"><strong>Record integrity</strong><small>Finalization runs server-side compliance checks; signed notes remain locked and require addenda.</small></article>
      <article className="surface-card"><strong>Production requirements</strong><small>HIPAA-eligible hosting, BAAs, encryption, backups, enforced MFA/SSO, RLS, and recovery testing are still required.</small></article>
    </section>
    <section className="surface-card safety-audit-card">
      <header className="card-heading"><div><p className="eyebrow">Organization audit history</p><h2>Recent events</h2><p className="muted">The application audit trail is metadata-only and should not duplicate clinical narrative.</p></div></header>
      {loading ? <p className="empty-copy">Loading audit history...</p> : error ? <p className="form-error" role="alert">{error}</p> : events.length ? <ul className="timeline-list">{events.map((event) => <li key={event.id}><time>{formatDate(event.createdAt)}</time><span><strong>{event.action.replaceAll("_", " ").replaceAll(".", " · ")}</strong><small>{event.actor} · {event.objectType}</small></span></li>)}</ul> : <p className="empty-copy">No audit events are available.</p>}
    </section>
  </div>;
}
