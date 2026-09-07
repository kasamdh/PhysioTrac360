import { useEffect, useState } from "react";
import { Plus, Search } from "lucide-react";

import { ApiError, api } from "../api/client";
import type { ManagedClient } from "../api/types";
import { formatDate } from "../lib/format";
import { ActionMenuTrigger } from "@/components/ui/action-menu-trigger";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { StatusTabs } from "@/components/ui/status-tabs";
import { AddClientDialog } from "./AddClientDialog";
import { ArchiveClientDialog } from "./ArchiveClientDialog";
import { ClientUsersDialog } from "./ClientUsersDialog";
import { EditClientDialog } from "./EditClientDialog";
import { ReactivateClientDialog } from "./ReactivateClientDialog";
import { SuspendClientDialog } from "./SuspendClientDialog";

const TIMEZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "America/Phoenix", "Pacific/Honolulu"];
const TIERS = [["starter", "Starter"], ["professional", "Professional"], ["premium", "Premium"], ["enterprise", "Enterprise"]] as const;
const SORTS = [["client_number", "Client #"], ["client_name", "Client name"], ["created", "Created date"], ["users", "User count"]] as const;
const STATUS_TABS = [
  { value: "", label: "All Clients" },
  { value: "active", label: "Active Clients" },
  { value: "suspended", label: "Suspended Clients" },
  { value: "archived", label: "Archived Clients" },
];

function openClient(clientNumber: number) {
  window.location.hash = `clients/${clientNumber}`;
}

function statusBadge(client: ManagedClient) {
  if (client.archivedAt) return <Badge tone="danger">Archived</Badge>;
  if (client.status === "suspended") return <Badge tone="warning">Suspended</Badge>;
  return <Badge tone="success">Active</Badge>;
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
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [invite, setInvite] = useState("");
  const [editingClient, setEditingClient] = useState<ManagedClient | null>(null);
  const [managingUsersFor, setManagingUsersFor] = useState<ManagedClient | null>(null);
  const [suspendingClient, setSuspendingClient] = useState<ManagedClient | null>(null);
  const [reactivatingClient, setReactivatingClient] = useState<ManagedClient | null>(null);
  const [archivingClient, setArchivingClient] = useState<ManagedClient | null>(null);

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

  async function resendInvite(client: ManagedClient) {
    setBusy(true); setError("");
    try { const result = await api.resendAdminInvitation(client.clientNumber); setInvite(result.invitationUrl); }
    catch (requestError) { setError(requestError instanceof ApiError ? requestError.message : "Unable to resend invitation."); }
    finally { setBusy(false); }
  }

  const pageCount = Math.max(1, Math.ceil(total / Number(pageSize)));

  return <div className="mx-auto max-w-[1400px] p-6 md:p-8">
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <p className="m-0 mb-1 text-xs font-bold uppercase tracking-wider text-primary-deep">Super Admin · Settings</p>
        <h1 className="m-0 text-2xl font-bold tracking-tight text-foreground md:text-3xl">Client Management</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground md:text-base">Provision and manage independent physical therapy organizations. Each client remains isolated from every other tenant.</p>
      </div>
      <Button size="sm" className="h-11 gap-1.5" onClick={() => setOpen(true)}>
        <Plus className="h-4 w-4" /> Add client
      </Button>
    </header>

    {error && <p role="alert" className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">{error}</p>}
    {invite && <p role="status" className="mb-4 rounded-md border border-primary-soft bg-primary-soft/40 px-4 py-3 text-sm font-medium text-primary-deep">An invitation email was sent to the new administrator. If it doesn't arrive, share this link directly: <a className="underline" href={invite} target="_blank" rel="noreferrer">{invite}</a></p>}

    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
      <StatusTabs tabs={STATUS_TABS} value={status} onChange={setStatus} />
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Client #, name, email, city, or admin"
          className="h-11 w-72 pl-9 text-sm"
        />
      </div>
    </div>

    <div className="mb-4 flex flex-wrap items-center gap-2">
      <select value={tier} onChange={(event) => setTier(event.target.value)} className="h-10 rounded-md border border-input bg-white px-3 text-sm text-foreground">
        <option value="">All plans</option>
        {TIERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      <input value={state} onChange={(event) => setState(event.target.value)} placeholder="State" className="h-10 w-24 rounded-md border border-input bg-white px-3 text-sm text-foreground" />
      <select value={timezone} onChange={(event) => setTimezone(event.target.value)} className="h-10 rounded-md border border-input bg-white px-3 text-sm text-foreground">
        <option value="">All timezones</option>
        {TIMEZONES.map((zone) => <option key={zone} value={zone}>{zone}</option>)}
      </select>
      <select value={sort} onChange={(event) => setSort(event.target.value)} className="h-10 rounded-md border border-input bg-white px-3 text-sm text-foreground">
        {SORTS.map(([value, label]) => <option key={value} value={value}>Sort: {label}</option>)}
      </select>
      <select value={pageSize} onChange={(event) => setPageSize(event.target.value)} className="h-10 rounded-md border border-input bg-white px-3 text-sm text-foreground">
        <option value="10">10 / page</option>
        <option value="25">25 / page</option>
        <option value="50">50 / page</option>
        <option value="100">100 / page</option>
      </select>
    </div>

    <div className="overflow-hidden rounded-xl border border-border bg-white">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/50 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <th className="w-28 px-4 py-3">Actions</th>
              <th className="px-4 py-3">Client</th>
              <th className="px-4 py-3">Location</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Plan</th>
              <th className="px-4 py-3">Users</th>
              <th className="px-4 py-3">Primary admin</th>
              <th className="px-4 py-3">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {clients.map((client) => (
              <tr key={client.id} className="hover:bg-muted/30">
                <td className="px-4 py-3">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <ActionMenuTrigger aria-label={`Actions for ${client.clientName}`} />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent>
                      <DropdownMenuItem onSelect={() => openClient(client.clientNumber)}>View</DropdownMenuItem>
                      <DropdownMenuItem onSelect={() => setManagingUsersFor(client)}>Manage users</DropdownMenuItem>
                      <DropdownMenuItem onSelect={() => setEditingClient(client)}>Edit</DropdownMenuItem>
                      {!client.archivedAt && client.status === "active" && (
                        <DropdownMenuItem onSelect={() => setSuspendingClient(client)}>Suspend</DropdownMenuItem>
                      )}
                      {!client.archivedAt && client.status === "suspended" && (
                        <DropdownMenuItem onSelect={() => setReactivatingClient(client)}>Reactivate</DropdownMenuItem>
                      )}
                      {!client.archivedAt && (
                        <>
                          <DropdownMenuItem onSelect={() => void resendInvite(client)}>Resend invite</DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem destructive onSelect={() => setArchivingClient(client)}>Archive</DropdownMenuItem>
                        </>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </td>
                <td className="px-4 py-3">
                  <button type="button" className="border-0 bg-transparent p-0 text-left font-semibold text-primary-deep hover:underline" onClick={() => openClient(client.clientNumber)}>
                    #{client.clientNumber} {client.clientName}
                  </button>
                  <div className="text-xs text-muted-foreground">
                    {client.email}
                    {client.portalUrl && (
                      <>
                        {" · "}
                        <a className="hover:underline" href={client.portalUrl} target="_blank" rel="noreferrer">Portal</a>
                      </>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3 text-foreground">{client.city}, {client.state}</td>
                <td className="px-4 py-3">{statusBadge(client)}</td>
                <td className="px-4 py-3 text-foreground">{client.subscriptionTierLabel}</td>
                <td className="px-4 py-3 text-foreground">{client.userCount}</td>
                <td className="px-4 py-3 text-foreground">{client.primaryAdmin?.name || "Not assigned"}</td>
                <td className="px-4 py-3 text-muted-foreground">{formatDate(client.createdAt, { month: "short", day: "numeric", year: "numeric" })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!clients.length && <p className="px-4 py-10 text-center text-sm text-muted-foreground">No clients match this search.</p>}
    </div>

    <div className="mt-4 flex items-center justify-center gap-3 text-sm">
      <Button variant="secondary" size="sm" className="h-9" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>Previous</Button>
      <span className="text-muted-foreground">Page {page} of {pageCount} · {total} client{total === 1 ? "" : "s"}</span>
      <Button variant="secondary" size="sm" className="h-9" disabled={page >= pageCount} onClick={() => setPage((current) => current + 1)}>Next</Button>
    </div>
    {open && (
      <AddClientDialog
        onClose={() => setOpen(false)}
        onCreated={async (invitationUrl) => { setInvite(invitationUrl); setOpen(false); await load(); }}
      />
    )}
    {editingClient && <EditClientDialog client={editingClient} onClose={() => setEditingClient(null)} onSaved={async () => { setEditingClient(null); await load(); }} />}
    {managingUsersFor && <ClientUsersDialog client={managingUsersFor} onClose={() => setManagingUsersFor(null)} />}
    {suspendingClient && <SuspendClientDialog client={suspendingClient} onClose={() => setSuspendingClient(null)} onSuspended={async () => { setSuspendingClient(null); await load(); }} />}
    {reactivatingClient && <ReactivateClientDialog client={reactivatingClient} onClose={() => setReactivatingClient(null)} onReactivated={async () => { setReactivatingClient(null); await load(); }} />}
    {archivingClient && <ArchiveClientDialog client={archivingClient} onClose={() => setArchivingClient(null)} onArchived={async () => { setArchivingClient(null); await load(); }} />}
  </div>;
}
