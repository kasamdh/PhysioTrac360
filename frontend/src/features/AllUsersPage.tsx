import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ManagedClientUser } from "../api/types";
import { ConfirmActionDialog } from "./ConfirmActionDialog";
import { CreateUserDialog } from "./CreateUserDialog";
import { EditUserDialog } from "./EditUserDialog";

const ROLES = [
  ["admin", "Organization administrator"],
  ["director", "Clinical director"],
  ["therapist", "Physical therapist"],
  ["assistant", "PTA / therapy assistant"],
  ["scheduler", "Scheduler / front desk"],
  ["biller", "Billing specialist"],
  ["compliance", "Compliance officer"],
] as const;

function openClient(clientNumber: number) {
  window.location.hash = `clients/${clientNumber}`;
}

export function AllUsersPage() {
  const [users, setUsers] = useState<ManagedClientUser[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState("25");
  const [query, setQuery] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<ManagedClientUser | null>(null);
  const [deactivatingUser, setDeactivatingUser] = useState<ManagedClientUser | null>(null);
  const [reactivatingUser, setReactivatingUser] = useState<ManagedClientUser | null>(null);
  const [deletingUser, setDeletingUser] = useState<ManagedClientUser | null>(null);

  async function load() {
    try {
      const result = await api.allUsers({ q: query, role, status, pageSize, page: String(page) });
      setUsers(result.users);
      setTotal(result.total);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load users.");
    }
  }
  useEffect(() => { setPage(1); }, [query, role, status, pageSize]);
  useEffect(() => { void load(); }, [query, role, status, pageSize, page]);

  const pageCount = Math.max(1, Math.ceil(total / Number(pageSize)));

  return (
    <div className="page-content">
      <header className="page-header split-header">
        <div>
          <p className="eyebrow">Super Admin · Settings</p>
          <h1>Users</h1>
          <p>Every user across every client, in one place. Create, edit, deactivate, or soft-delete any account without leaving this page.</p>
        </div>
        <button className="primary-button" onClick={() => setOpen(true)}>+ Add user</button>
      </header>
      {error && <p className="form-error" role="alert">{error}</p>}
      <section className="surface-card client-management-card">
        <div className="client-toolbar">
          <label className="field-inline">
            <span>Search users</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Name, email, username, or client" />
          </label>
          <span className="client-count">{total} user{total === 1 ? "" : "s"}</span>
        </div>
        <div className="client-filter-bar">
          <label>Role<select value={role} onChange={(event) => setRole(event.target.value)}><option value="">All</option>{ROLES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>Status<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All</option><option value="active">Active</option><option value="inactive">Inactive</option><option value="archived">Archived</option></select></label>
          <label>Per page<select value={pageSize} onChange={(event) => setPageSize(event.target.value)}><option value="10">10</option><option value="25">25</option><option value="50">50</option><option value="100">100</option></select></label>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Name</th><th>Email</th><th>Client</th><th>Role</th><th>MFA</th><th>Status</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td><strong>{user.name}</strong><small>{user.username}</small></td>
                  <td>{user.email}</td>
                  <td>{user.clientNumber !== null ? <button className="text-action" onClick={() => openClient(user.clientNumber as number)}>#{user.clientNumber} {user.clientName}</button> : "—"}</td>
                  <td>{user.roleLabel}</td>
                  <td>{user.mustUseMfa ? "Required" : "Optional"}</td>
                  <td>{user.archivedAt ? "Archived" : user.active ? "Active" : "Inactive"}</td>
                  <td>
                    <button className="text-action" onClick={() => setEditingUser(user)}>Edit</button>{" "}
                    {!user.archivedAt && user.active && <button className="text-action" onClick={() => setDeactivatingUser(user)}>Deactivate</button>}
                    {!user.archivedAt && !user.active && <button className="text-action" onClick={() => setReactivatingUser(user)}>Reactivate</button>}
                    {!user.archivedAt && <>{" "}<button className="text-action" onClick={() => setDeletingUser(user)}>Soft delete</button></>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!users.length && <p className="empty-copy">No users match this search.</p>}
        <div className="client-pagination">
          <button className="secondary-button" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>Previous</button>
          <span>Page {page} of {pageCount}</span>
          <button className="secondary-button" disabled={page >= pageCount} onClick={() => setPage((current) => current + 1)}>Next</button>
        </div>
      </section>
      {open && <CreateUserDialog onClose={() => setOpen(false)} onCreated={async () => { setOpen(false); await load(); }} />}
      {editingUser && (
        <EditUserDialog
          user={editingUser}
          onClose={() => setEditingUser(null)}
          onSave={(body) => api.updateUser(editingUser.id, body)}
          onSaved={async () => { setEditingUser(null); await load(); }}
        />
      )}
      {deactivatingUser && (
        <ConfirmActionDialog
          eyebrow={deactivatingUser.clientName ? `#${deactivatingUser.clientNumber} ${deactivatingUser.clientName}` : "User"}
          title={`Deactivate ${deactivatingUser.name}?`}
          body="This immediately blocks sign-in for this account. No data is deleted, and it can be reactivated at any time."
          confirmLabel="Deactivate user"
          onClose={() => setDeactivatingUser(null)}
          onConfirm={async () => { await api.setUserActive(deactivatingUser.id, false); setDeactivatingUser(null); await load(); }}
        />
      )}
      {reactivatingUser && (
        <ConfirmActionDialog
          eyebrow={reactivatingUser.clientName ? `#${reactivatingUser.clientNumber} ${reactivatingUser.clientName}` : "User"}
          title={`Reactivate ${reactivatingUser.name}?`}
          body="This restores sign-in access for this account according to its existing role."
          confirmLabel="Reactivate user"
          onClose={() => setReactivatingUser(null)}
          onConfirm={async () => { await api.setUserActive(reactivatingUser.id, true); setReactivatingUser(null); await load(); }}
        />
      )}
      {deletingUser && (
        <ConfirmActionDialog
          eyebrow={deletingUser.clientName ? `#${deletingUser.clientNumber} ${deletingUser.clientName}` : "User"}
          title={`Soft delete ${deletingUser.name}?`}
          body="This blocks sign-in and hides the account from the default list. No records are deleted — the account is preserved and can be restored by support if needed."
          confirmLabel="Soft delete user"
          onClose={() => setDeletingUser(null)}
          onConfirm={async () => { await api.archiveUser(deletingUser.id); setDeletingUser(null); await load(); }}
        />
      )}
    </div>
  );
}
