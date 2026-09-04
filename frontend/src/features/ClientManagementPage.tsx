import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ManagedClient } from "../api/types";
import { formatDate } from "../lib/format";
import { ArchiveClientDialog } from "./ArchiveClientDialog";
import { ClientUsersDialog } from "./ClientUsersDialog";
import { EditClientDialog } from "./EditClientDialog";
import { ReactivateClientDialog } from "./ReactivateClientDialog";
import { SuspendClientDialog } from "./SuspendClientDialog";

const emptyForm = { clientName: "", clientEmail: "", addressLine1: "", city: "", state: "", zipCode: "", subscriptionTier: "professional", timezone: "America/New_York", adminFirstName: "", adminLastName: "", adminEmail: "", comments: "" };

const TIMEZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "America/Phoenix", "Pacific/Honolulu"];
const TIERS = [["starter", "Starter"], ["professional", "Professional"], ["premium", "Premium"], ["enterprise", "Enterprise"]] as const;
const SORTS = [["client_number", "Client #"], ["client_name", "Client name"], ["created", "Created date"], ["users", "User count"]] as const;

function openClient(clientNumber: number) {
  window.location.hash = `clients/${clientNumber}`;
}

export function ClientManagementPage() {
  const [clients, setClients] = useState<ManagedClient[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [tier, setTier] = useState("");
  const [state, setState] = useState("");
  const [timezone, setTimezone] = useState("");
  const [sort, setSort] = useState("client_number");
  const [pageSize, setPageSize] = useState("25");
  const [form, setForm] = useState(emptyForm);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [invite, setInvite] = useState("");
  const [editingClient, setEditingClient] = useState<ManagedClient | null>(null);
  const [managingUsersFor, setManagingUsersFor] = useState<ManagedClient | null>(null);
  const [suspendingClient, setSuspendingClient] = useState<ManagedClient | null>(null);
  const [reactivatingClient, setReactivatingClient] = useState<ManagedClient | null>(null);
  const [archivingClient, setArchivingClient] = useState<ManagedClient | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  async function load() {
    try {
      const result = await api.managedClients(query, {
        status,
        subscriptionTier: tier,
        state,
        timezone,
        sort,
        pageSize,
        page: String(page),
      });
      setClients(result.clients);
      setTotal(result.total);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load clients.");
    }
  }
  useEffect(() => { setPage(1); }, [query, status, tier, state, timezone, sort, pageSize]);
  useEffect(() => { void load(); }, [query, status, tier, state, timezone, sort, pageSize, page]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setFieldErrors({});
    try { const result = await api.createManagedClient(form); setInvite(result.invitationUrl); setForm(emptyForm); setOpen(false); await load(); }
    catch (requestError) { if (requestError instanceof ApiError) { setError(requestError.message); setFieldErrors(requestError.fields); } else setError("Unable to create client."); }
    finally { setBusy(false); }
  }

  async function resendInvite(client: ManagedClient) {
    setBusy(true); setError("");
    try { const result = await api.resendAdminInvitation(client.clientNumber); setInvite(result.invitationUrl); }
    catch (requestError) { setError(requestError instanceof ApiError ? requestError.message : "Unable to resend invitation."); }
    finally { setBusy(false); }
  }

  const pageCount = Math.max(1, Math.ceil(total / Number(pageSize)));

  return <div className="page-content"><header className="page-header split-header"><div><p className="eyebrow">Super Admin · Settings</p><h1>Client Management</h1><p>Provision and manage independent physical therapy organizations. Each client remains isolated from every other tenant.</p></div><button className="primary-button" onClick={() => setOpen(true)}>+ Add client</button></header>
    {error && <p className="form-error" role="alert">{error}</p>}
    {invite && <p className="form-notice" role="status">Development invitation link (local testing only): <a href={invite} target="_blank" rel="noreferrer">{invite}</a></p>}
    <section className="surface-card client-management-card">
      <div className="client-toolbar"><label className="field-inline"><span>Search clients</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Client #, name, email, city, or admin" /></label><span className="client-count">{total} client{total === 1 ? "" : "s"}</span></div>
      <div className="client-filter-bar">
        <label>Status<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All</option><option value="active">Active</option><option value="suspended">Suspended</option><option value="archived">Archived</option></select></label>
        <label>Subscription<select value={tier} onChange={(event) => setTier(event.target.value)}><option value="">All</option>{TIERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label>State<input value={state} onChange={(event) => setState(event.target.value)} placeholder="e.g. NC" style={{ width: "5rem" }} /></label>
        <label>Timezone<select value={timezone} onChange={(event) => setTimezone(event.target.value)}><option value="">All</option>{TIMEZONES.map((zone) => <option key={zone} value={zone}>{zone}</option>)}</select></label>
        <label>Sort by<select value={sort} onChange={(event) => setSort(event.target.value)}>{SORTS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label>Per page<select value={pageSize} onChange={(event) => setPageSize(event.target.value)}><option value="10">10</option><option value="25">25</option><option value="50">50</option><option value="100">100</option></select></label>
      </div>
      <div className="table-wrap"><table><thead><tr><th>Client #</th><th>Client</th><th>Portal URL</th><th>Location</th><th>Status</th><th>Plan</th><th>Timezone</th><th>Users</th><th>Primary admin</th><th>Created</th><th>Actions</th></tr></thead><tbody>{clients.map((client) => <tr key={client.id}><td><strong>{client.clientNumber}</strong></td><td><button className="text-action" onClick={() => openClient(client.clientNumber)}><strong>{client.clientName}</strong></button><small>{client.email}</small></td><td>{client.portalUrl ? <a className="client-portal-link" href={client.portalUrl} target="_blank" rel="noreferrer">Open portal</a> : <small>Not configured</small>}</td><td>{client.city}, {client.state}</td><td><span className={`client-status ${client.status}`}>{client.archivedAt ? "Archived" : client.statusLabel}</span></td><td>{client.subscriptionTierLabel}</td><td><small>{client.timezone}</small></td><td>{client.userCount}</td><td>{client.primaryAdmin?.name || "Not assigned"}</td><td>{formatDate(client.createdAt, { month: "short", day: "numeric", year: "numeric" })}</td><td>
        <button className="text-action" disabled={busy} onClick={() => openClient(client.clientNumber)}>View</button>{" "}
        <button className="text-action" disabled={busy} onClick={() => setManagingUsersFor(client)}>Manage users</button>{" "}
        <button className="text-action" disabled={busy} onClick={() => setEditingClient(client)}>Edit</button>{" "}
        {!client.archivedAt && client.status === "active" && <button className="text-action" disabled={busy} onClick={() => setSuspendingClient(client)}>Suspend</button>}
        {!client.archivedAt && client.status === "suspended" && <button className="text-action" disabled={busy} onClick={() => setReactivatingClient(client)}>Reactivate</button>}
        {!client.archivedAt && <>{" "}<button className="text-action" disabled={busy} onClick={() => void resendInvite(client)}>Resend invite</button>{" "}<button className="text-action" disabled={busy} onClick={() => setArchivingClient(client)}>Archive</button></>}
      </td></tr>)}</tbody></table></div>
      {!clients.length && <p className="empty-copy">No clients match this search.</p>}
      <div className="client-pagination">
        <button className="secondary-button" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>Previous</button>
        <span>Page {page} of {pageCount}</span>
        <button className="secondary-button" disabled={page >= pageCount} onClick={() => setPage((current) => current + 1)}>Next</button>
      </div>
    </section>
    {open && <div className="modal-backdrop"><section className="move-dialog client-dialog" role="dialog" aria-modal="true" aria-labelledby="client-dialog-title"><button className="dialog-close" onClick={() => setOpen(false)} aria-label="Close">×</button><p className="eyebrow">Provision tenant</p><h2 id="client-dialog-title">Add client</h2>{error && <p className="form-error" role="alert">{error}</p>}<form className="stack-form" onSubmit={create}><h3>Facility information</h3><div className="field-grid"><label>Client name<input required aria-invalid={Boolean(fieldErrors.clientName)} value={form.clientName} onChange={(event) => setForm({ ...form, clientName: event.target.value })} />{fieldErrors.clientName && <small className="field-error">{fieldErrors.clientName}</small>}</label><label>Client email<input required type="email" aria-invalid={Boolean(fieldErrors.clientEmail)} value={form.clientEmail} onChange={(event) => setForm({ ...form, clientEmail: event.target.value })} />{fieldErrors.clientEmail && <small className="field-error">{fieldErrors.clientEmail}</small>}</label><label>Address<input required aria-invalid={Boolean(fieldErrors.addressLine1)} value={form.addressLine1} onChange={(event) => setForm({ ...form, addressLine1: event.target.value })} />{fieldErrors.addressLine1 && <small className="field-error">{fieldErrors.addressLine1}</small>}</label><label>City<input required aria-invalid={Boolean(fieldErrors.city)} value={form.city} onChange={(event) => setForm({ ...form, city: event.target.value })} />{fieldErrors.city && <small className="field-error">{fieldErrors.city}</small>}</label><label>State<input required aria-invalid={Boolean(fieldErrors.state)} value={form.state} onChange={(event) => setForm({ ...form, state: event.target.value })} />{fieldErrors.state && <small className="field-error">{fieldErrors.state}</small>}</label><label>ZIP<input required aria-invalid={Boolean(fieldErrors.zipCode)} value={form.zipCode} onChange={(event) => setForm({ ...form, zipCode: event.target.value })} />{fieldErrors.zipCode && <small className="field-error">{fieldErrors.zipCode}</small>}</label></div><h3>Account settings</h3><div className="field-grid"><label>Subscription<select value={form.subscriptionTier} onChange={(event) => setForm({ ...form, subscriptionTier: event.target.value })}><option value="starter">Starter</option><option value="professional">Professional</option><option value="premium">Premium</option><option value="enterprise">Enterprise</option></select></label><label>Timezone<select value={form.timezone} onChange={(event) => setForm({ ...form, timezone: event.target.value })}><option>America/New_York</option><option>America/Chicago</option><option>America/Denver</option><option>America/Los_Angeles</option><option>America/Phoenix</option><option>Pacific/Honolulu</option></select></label></div><h3>Primary administrator</h3><div className="field-grid"><label>First name<input required aria-invalid={Boolean(fieldErrors.adminFirstName)} value={form.adminFirstName} onChange={(event) => setForm({ ...form, adminFirstName: event.target.value })} />{fieldErrors.adminFirstName && <small className="field-error">{fieldErrors.adminFirstName}</small>}</label><label>Last name<input required aria-invalid={Boolean(fieldErrors.adminLastName)} value={form.adminLastName} onChange={(event) => setForm({ ...form, adminLastName: event.target.value })} />{fieldErrors.adminLastName && <small className="field-error">{fieldErrors.adminLastName}</small>}</label><label>Admin email<input required type="email" aria-invalid={Boolean(fieldErrors.adminEmail)} value={form.adminEmail} onChange={(event) => setForm({ ...form, adminEmail: event.target.value })} />{fieldErrors.adminEmail && <small className="field-error">{fieldErrors.adminEmail}</small>}</label></div><label>Comments<textarea rows={3} value={form.comments} onChange={(event) => setForm({ ...form, comments: event.target.value })} /></label><div className="button-row"><button className="secondary-button" type="button" onClick={() => setOpen(false)}>Cancel</button><button className="primary-button" disabled={busy} type="submit">{busy ? "Creating..." : "Create client"}</button></div></form></section></div>}
    {editingClient && <EditClientDialog client={editingClient} onClose={() => setEditingClient(null)} onSaved={async () => { setEditingClient(null); await load(); }} />}
    {managingUsersFor && <ClientUsersDialog client={managingUsersFor} onClose={() => setManagingUsersFor(null)} />}
    {suspendingClient && <SuspendClientDialog client={suspendingClient} onClose={() => setSuspendingClient(null)} onSuspended={async () => { setSuspendingClient(null); await load(); }} />}
    {reactivatingClient && <ReactivateClientDialog client={reactivatingClient} onClose={() => setReactivatingClient(null)} onReactivated={async () => { setReactivatingClient(null); await load(); }} />}
    {archivingClient && <ArchiveClientDialog client={archivingClient} onClose={() => setArchivingClient(null)} onArchived={async () => { setArchivingClient(null); await load(); }} />}
  </div>;
}
