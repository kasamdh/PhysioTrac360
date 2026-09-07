import { useEffect, useState } from "react";
import { Plus } from "lucide-react";

import { ApiError, api } from "../api/client";
import type { ManagedClientUser } from "../api/types";
import { ActionMenuTrigger } from "@/components/ui/action-menu-trigger";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { LicenseBadge } from "@/components/ui/license-banner";
import { StatusBadge } from "@/components/ui/status-banner";
import { StatusTabs } from "@/components/ui/status-tabs";
import { CreateOrganizationUserDialog } from "./CreateOrganizationUserDialog";
import { EditUserDialog } from "./EditUserDialog";

const STATUS_TABS = [
  { value: "", label: "All Users" },
  { value: "active", label: "Active" },
  { value: "inactive", label: "Inactive" },
  { value: "locked_out", label: "Locked Out" },
  { value: "suspended", label: "Suspended" },
  { value: "deleted", label: "Deleted" },
];

interface OrganizationUsersPageProps {
  currentUserId: string;
}

export function OrganizationUsersPage({ currentUserId }: OrganizationUsersPageProps) {
  const [users, setUsers] = useState<ManagedClientUser[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState("25");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<ManagedClientUser | null>(null);

  async function load() {
    try {
      const result = await api.organizationUsers({ status, pageSize, page: String(page) });
      setUsers(result.users);
      setTotal(result.total);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load users.");
    }
  }
  useEffect(() => { setPage(1); }, [status, pageSize]);
  useEffect(() => { void load(); }, [status, pageSize, page]);

  const pageCount = Math.max(1, Math.ceil(total / Number(pageSize)));
  const licenseAlertCount = users.filter((user) => user.licenseAlertStatus === "expiring_soon" || user.licenseAlertStatus === "expired").length;

  return (
    <div className="mx-auto max-w-[1400px] p-6 md:p-8">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="m-0 mb-1 text-xs font-bold uppercase tracking-wider text-primary-deep">Settings</p>
          <h1 className="m-0 text-2xl font-bold tracking-tight text-foreground md:text-3xl">Users</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground md:text-base">
            Create and edit accounts for your organization, including status, from the Edit dialog. Everything here is scoped to your organization only.
          </p>
        </div>
        <Button size="sm" className="h-11 gap-1.5" onClick={() => setOpen(true)}>
          <Plus className="h-4 w-4" /> Create user
        </Button>
      </header>

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {error}
        </p>
      )}

      {licenseAlertCount > 0 && (
        <p role="status" className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-800">
          {licenseAlertCount} clinician license{licenseAlertCount === 1 ? "" : "s"} need{licenseAlertCount === 1 ? "s" : ""} attention — renew before they lapse.
        </p>
      )}

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <StatusTabs tabs={STATUS_TABS} value={status} onChange={setStatus} />
        <select
          value={pageSize}
          onChange={(event) => setPageSize(event.target.value)}
          className="h-11 rounded-md border border-input bg-white px-3 text-sm text-foreground"
        >
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
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">MFA</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">License</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {users.map((user) => (
                <tr key={user.id} className="hover:bg-muted/30">
                  <td className="px-4 py-3">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <ActionMenuTrigger aria-label={`Actions for ${user.name}`} />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent>
                        <DropdownMenuItem onSelect={() => setEditingUser(user)}>Edit user</DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-semibold text-foreground">{user.name}</div>
                    <div className="text-xs text-muted-foreground">{user.username} · {user.email}</div>
                  </td>
                  <td className="px-4 py-3 text-foreground">{user.roleLabel}</td>
                  <td className="px-4 py-3 text-muted-foreground">{user.mustUseMfa ? "Required" : "Optional"}</td>
                  <td className="px-4 py-3"><StatusBadge status={user.status} /></td>
                  <td className="px-4 py-3"><LicenseBadge status={user.licenseAlertStatus} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!users.length && <p className="px-4 py-10 text-center text-sm text-muted-foreground">Your organization has no users yet.</p>}
      </div>

      <div className="mt-4 flex items-center justify-center gap-3 text-sm">
        <Button variant="secondary" size="sm" className="h-9" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>
          Previous
        </Button>
        <span className="text-muted-foreground">Page {page} of {pageCount} · {total} user{total === 1 ? "" : "s"}</span>
        <Button variant="secondary" size="sm" className="h-9" disabled={page >= pageCount} onClick={() => setPage((current) => current + 1)}>
          Next
        </Button>
      </div>

      {open && <CreateOrganizationUserDialog onClose={() => setOpen(false)} onCreated={async () => { setOpen(false); await load(); }} />}
      {editingUser && (
        <EditUserDialog
          user={editingUser}
          isOwnAccount={editingUser.id === currentUserId}
          onClose={() => { setEditingUser(null); void load(); }}
          onSave={(body) => api.updateOrganizationUser(editingUser.id, body)}
          onStatusAction={(action, reason) => api.organizationUserStatusAction(editingUser.id, action, reason)}
          onRevokeSessions={() => api.organizationUserRevokeSessions(editingUser.id)}
          onCreateLicense={(body) => api.createOrganizationUserLicense(editingUser.id, body)}
          onUpdateLicense={(licenseId, body) => api.updateOrganizationUserLicense(editingUser.id, licenseId, body)}
          onDeleteLicense={(licenseId) => api.deleteOrganizationUserLicense(editingUser.id, licenseId)}
          onUploadLicenseDocument={(licenseId, file) => api.uploadOrganizationUserLicenseDocument(editingUser.id, licenseId, file)}
          onVerifyLicense={(licenseId, notes) => api.verifyOrganizationUserLicense(editingUser.id, licenseId, notes)}
          licenseDocumentUrl={(licenseId) => api.organizationUserLicenseDocumentUrl(editingUser.id, licenseId)}
          onSaved={async () => { setEditingUser(null); await load(); }}
        />
      )}
    </div>
  );
}
