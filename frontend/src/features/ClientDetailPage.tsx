import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { AuditEvent, ManagedClient } from "../api/types";
import { formatDate } from "../lib/format";
import { ArchiveClientDialog } from "./ArchiveClientDialog";
import { ClientUsersDialog } from "./ClientUsersDialog";
import { EditClientDialog } from "./EditClientDialog";
import { PrivilegedAccessTab } from "./PrivilegedAccessTab";
import { ReactivateClientDialog } from "./ReactivateClientDialog";
import { SuspendClientDialog } from "./SuspendClientDialog";

interface ClientDetailPageProps {
  clientNumber: number;
  onBack: () => void;
}

type Tab = "overview" | "users" | "subscription" | "audit" | "privileged" | "settings";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "users", label: "Users" },
  { id: "subscription", label: "Subscription" },
  { id: "audit", label: "Audit Log" },
  { id: "privileged", label: "Clinical Access" },
  { id: "settings", label: "Settings" },
];

const TIER_FEATURES: Record<string, string[]> = {
  starter: ["1 therapist", "Scheduling", "Documentation"],
  professional: ["5 therapists", "Home exercise programs", "Payments", "Secure messaging"],
  premium: ["Unlimited therapists", "AI-assisted documentation", "Advanced reporting"],
  enterprise: ["Custom configuration and limits"],
};

export function ClientDetailPage({ clientNumber, onBack }: ClientDetailPageProps) {
  const [client, setClient] = useState<ManagedClient | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [auditError, setAuditError] = useState("");
  const [showEdit, setShowEdit] = useState(false);
  const [showUsers, setShowUsers] = useState(false);
  const [showSuspend, setShowSuspend] = useState(false);
  const [showReactivate, setShowReactivate] = useState(false);
  const [showArchive, setShowArchive] = useState(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const result = await api.managedClient(clientNumber);
      setClient(result.client);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load this client.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    setEvents(null);
  }, [clientNumber]);

  useEffect(() => {
    if (tab !== "audit" || events !== null) return;
    api
      .clientAuditEvents(clientNumber)
      .then((result) => setEvents(result.events))
      .catch((requestError) => setAuditError(requestError instanceof ApiError ? requestError.message : "Unable to load the audit log."));
  }, [tab, clientNumber, events]);

  if (loading) return <div className="page-content"><p className="muted">Loading client...</p></div>;
  if (error || !client) {
    return (
      <div className="page-content">
        <button className="text-action" onClick={onBack}>&larr; Back to Client Management</button>
        <p className="form-error" role="alert">{error || "Client was not found."}</p>
      </div>
    );
  }

  return (
    <div className="page-content">
      <button className="text-action" onClick={onBack}>&larr; Back to Client Management</button>
      <header className="page-header split-header">
        <div>
          <p className="eyebrow">Client #{client.clientNumber}</p>
          <h1>{client.clientName}</h1>
          <p>
            <span className={`client-status ${client.status}`}>{client.archivedAt ? "Archived" : client.statusLabel}</span>
            {" "}· {client.subscriptionTierLabel}
          </p>
        </div>
      </header>

      <nav className="client-detail-tabs" aria-label="Client detail sections">
        {TABS.map((entry) => (
          <button key={entry.id} className={tab === entry.id ? "active" : ""} onClick={() => setTab(entry.id)}>
            {entry.label}
          </button>
        ))}
      </nav>

      {tab === "overview" && (
        <section className="surface-card">
          <div className="card-heading"><h2>Facility information</h2></div>
          <dl className="detail-grid">
            <div><dt>Address</dt><dd>{client.addressLine1}{client.addressLine2 ? `, ${client.addressLine2}` : ""}<br />{client.city}, {client.state} {client.zipCode}<br />{client.country}</dd></div>
            <div><dt>Email</dt><dd>{client.email || "Not set"}</dd></div>
            <div><dt>Phone</dt><dd>{client.phone || "Not set"}</dd></div>
            <div><dt>Timezone</dt><dd>{client.timezone}</dd></div>
            <div><dt>Portal URL</dt><dd>{client.portalUrl ? <a href={client.portalUrl} target="_blank" rel="noreferrer">{client.portalUrl}</a> : "Not configured"}</dd></div>
            <div><dt>Primary administrator</dt><dd>{client.primaryAdmin ? `${client.primaryAdmin.name} (${client.primaryAdmin.email})` : "Not assigned"}</dd></div>
            <div><dt>Users</dt><dd>{client.userCount}</dd></div>
            <div><dt>Created</dt><dd>{formatDate(client.createdAt, { month: "short", day: "numeric", year: "numeric" })}</dd></div>
            <div><dt>Last updated</dt><dd>{formatDate(client.updatedAt, { month: "short", day: "numeric", year: "numeric" })}</dd></div>
            {client.comments && <div><dt>Comments</dt><dd>{client.comments}</dd></div>}
          </dl>
        </section>
      )}

      {tab === "users" && (
        <section className="surface-card">
          <div className="card-heading"><h2>Users</h2><button className="primary-button" onClick={() => setShowUsers(true)}>Manage users</button></div>
          <p className="muted">{client.clientName} has {client.userCount} user{client.userCount === 1 ? "" : "s"}. Open Manage users to view roles and provision new accounts.</p>
        </section>
      )}

      {tab === "subscription" && (
        <section className="surface-card">
          <div className="card-heading"><h2>Subscription</h2><button className="secondary-button" onClick={() => setShowEdit(true)}>Change plan</button></div>
          <p><strong>{client.subscriptionTierLabel}</strong></p>
          <ul>
            {(TIER_FEATURES[client.subscriptionTier] || []).map((feature) => <li key={feature}>{feature}</li>)}
          </ul>
        </section>
      )}

      {tab === "audit" && (
        <section className="surface-card">
          <div className="card-heading"><h2>Audit log</h2></div>
          {auditError && <p className="form-error" role="alert">{auditError}</p>}
          {events === null && !auditError && <p className="muted">Loading audit events...</p>}
          {events && (
            <div className="table-wrap">
              <table>
                <thead><tr><th>When</th><th>Action</th><th>Actor</th></tr></thead>
                <tbody>
                  {events.map((event) => (
                    <tr key={event.id}>
                      <td><small>{formatDate(event.createdAt, { month: "short", day: "numeric", year: "numeric" })}</small></td>
                      <td>{event.action}</td>
                      <td>{event.actor}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {events && !events.length && <p className="empty-copy">No administrative activity recorded yet.</p>}
        </section>
      )}

      {tab === "privileged" && <PrivilegedAccessTab clientNumber={client.clientNumber} clientName={client.clientName} />}

      {tab === "settings" && (
        <section className="surface-card">
          <div className="card-heading"><h2>Settings</h2></div>
          <div className="button-row">
            <button className="secondary-button" onClick={() => setShowEdit(true)}>Edit client</button>
            {client.status === "active" && !client.archivedAt && (
              <button className="text-action" onClick={() => setShowSuspend(true)}>Suspend client</button>
            )}
            {client.status === "suspended" && !client.archivedAt && (
              <button className="text-action" onClick={() => setShowReactivate(true)}>Reactivate client</button>
            )}
            {!client.archivedAt && (
              <button className="text-action" onClick={() => setShowArchive(true)}>Archive client</button>
            )}
          </div>
          {client.archivedAt && <p className="muted">This client was archived on {formatDate(client.archivedAt, { month: "short", day: "numeric", year: "numeric" })}.</p>}
        </section>
      )}

      {showEdit && <EditClientDialog client={client} onClose={() => setShowEdit(false)} onSaved={async () => { setShowEdit(false); await load(); }} />}
      {showUsers && <ClientUsersDialog client={client} onClose={() => setShowUsers(false)} />}
      {showSuspend && <SuspendClientDialog client={client} onClose={() => setShowSuspend(false)} onSuspended={async () => { setShowSuspend(false); await load(); }} />}
      {showReactivate && <ReactivateClientDialog client={client} onClose={() => setShowReactivate(false)} onReactivated={async () => { setShowReactivate(false); await load(); }} />}
      {showArchive && <ArchiveClientDialog client={client} onClose={() => setShowArchive(false)} onArchived={async () => { setShowArchive(false); await load(); }} />}
    </div>
  );
}
