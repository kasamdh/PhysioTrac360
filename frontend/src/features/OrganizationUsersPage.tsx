import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ManagedClientUser } from "../api/types";
import { ConfirmActionDialog } from "./ConfirmActionDialog";
import { EditUserDialog } from "./EditUserDialog";

const emptyForm = {
  username: "",
  firstName: "",
  lastName: "",
  email: "",
  role: "therapist",
  credential: "",
  password: "",
  confirmPassword: "",
  mustUseMfa: true,
};

const roles = [
  ["admin", "Organization administrator"],
  ["director", "Clinical director"],
  ["therapist", "Physical therapist"],
  ["assistant", "PTA / therapy assistant"],
  ["scheduler", "Scheduler / front desk"],
  ["biller", "Billing specialist"],
  ["compliance", "Compliance officer"],
] as const;

interface OrganizationUsersPageProps {
  currentUserId: string;
}

export function OrganizationUsersPage({ currentUserId }: OrganizationUsersPageProps) {
  const [users, setUsers] = useState<ManagedClientUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [editingUser, setEditingUser] = useState<ManagedClientUser | null>(null);
  const [deactivatingUser, setDeactivatingUser] = useState<ManagedClientUser | null>(null);
  const [reactivatingUser, setReactivatingUser] = useState<ManagedClientUser | null>(null);
  const [deletingUser, setDeletingUser] = useState<ManagedClientUser | null>(null);

  async function load() {
    setLoading(true);
    try {
      const result = await api.organizationUsers();
      setUsers(result.users);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load users.");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { void load(); }, []);

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      await api.createOrganizationUser(form);
      setForm(emptyForm);
      setOpen(false);
      await load();
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        setError(requestError.message);
        setFieldErrors(requestError.fields);
      } else {
        setError("Unable to create the user.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-content">
      <header className="page-header split-header">
        <div>
          <p className="eyebrow">Settings</p>
          <h1>Users</h1>
          <p>Create, edit, deactivate, or soft-delete accounts for your organization. Everything here is scoped to your organization only.</p>
        </div>
        <button className="primary-button" onClick={() => setOpen(true)}>+ Create user</button>
      </header>
      {error && !open && <p className="form-error" role="alert">{error}</p>}
      <section className="surface-card client-management-card">
        <div className="client-toolbar">
          <span className="client-count">{users.length} user{users.length === 1 ? "" : "s"}</span>
        </div>
        {loading ? <p className="muted">Loading users...</p> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>MFA</th><th>Status</th><th>Actions</th></tr></thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id}>
                    <td><strong>{user.name}</strong><small>{user.username}</small></td>
                    <td>{user.email}</td>
                    <td>{user.roleLabel}</td>
                    <td>{user.mustUseMfa ? "Required" : "Optional"}</td>
                    <td>{user.archivedAt ? "Archived" : user.active ? "Active" : "Inactive"}</td>
                    <td>
                      <button className="text-action" onClick={() => setEditingUser(user)}>Edit</button>
                      {user.id !== currentUserId && !user.archivedAt && user.active && <>{" "}<button className="text-action" onClick={() => setDeactivatingUser(user)}>Deactivate</button></>}
                      {user.id !== currentUserId && !user.archivedAt && !user.active && <>{" "}<button className="text-action" onClick={() => setReactivatingUser(user)}>Reactivate</button></>}
                      {user.id !== currentUserId && !user.archivedAt && <>{" "}<button className="text-action" onClick={() => setDeletingUser(user)}>Soft delete</button></>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!loading && !users.length && <p className="empty-copy">Your organization has no users yet.</p>}
      </section>

      {open && (
        <div className="modal-backdrop">
          <section className="move-dialog client-dialog" role="dialog" aria-modal="true" aria-labelledby="create-org-user-title">
            <button className="dialog-close" onClick={() => setOpen(false)} disabled={busy} aria-label="Close">&times;</button>
            <p className="eyebrow">Your organization</p>
            <h2 id="create-org-user-title">Create user</h2>
            {error && <p className="form-error" role="alert">{error}</p>}
            <form className="stack-form" onSubmit={createUser}>
              <div className="field-grid">
                <label>Username<input required value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} />{fieldErrors.username && <small className="field-error">{fieldErrors.username}</small>}</label>
                <label>Email<input required type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} />{fieldErrors.email && <small className="field-error">{fieldErrors.email}</small>}</label>
                <label>First name<input required value={form.firstName} onChange={(event) => setForm({ ...form, firstName: event.target.value })} />{fieldErrors.firstName && <small className="field-error">{fieldErrors.firstName}</small>}</label>
                <label>Last name<input required value={form.lastName} onChange={(event) => setForm({ ...form, lastName: event.target.value })} />{fieldErrors.lastName && <small className="field-error">{fieldErrors.lastName}</small>}</label>
                <label>Role<select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}>{roles.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>{fieldErrors.role && <small className="field-error">{fieldErrors.role}</small>}</label>
                <label>Credential or license<input value={form.credential} onChange={(event) => setForm({ ...form, credential: event.target.value })} /></label>
                <label>Temporary password<input required type="password" autoComplete="new-password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} />{fieldErrors.password && <small className="field-error">{fieldErrors.password}</small>}</label>
                <label>Confirm password<input required type="password" autoComplete="new-password" value={form.confirmPassword} onChange={(event) => setForm({ ...form, confirmPassword: event.target.value })} />{fieldErrors.confirmPassword && <small className="field-error">{fieldErrors.confirmPassword}</small>}</label>
              </div>
              <label className="check-label"><input type="checkbox" checked={form.mustUseMfa} onChange={(event) => setForm({ ...form, mustUseMfa: event.target.checked })} /> Require MFA under the organization policy</label>
              <div className="button-row">
                <button className="secondary-button" type="button" onClick={() => setOpen(false)} disabled={busy}>Cancel</button>
                <button className="primary-button" type="submit" disabled={busy}>{busy ? "Creating..." : "Create user"}</button>
              </div>
            </form>
          </section>
        </div>
      )}

      {editingUser && (
        <EditUserDialog
          user={editingUser}
          isOwnAccount={editingUser.id === currentUserId}
          onClose={() => setEditingUser(null)}
          onSave={(body) => api.updateOrganizationUser(editingUser.id, body)}
          onSaved={async () => { setEditingUser(null); await load(); }}
        />
      )}
      {deactivatingUser && (
        <ConfirmActionDialog
          eyebrow="Your organization"
          title={`Deactivate ${deactivatingUser.name}?`}
          body="This immediately blocks sign-in for this account. No data is deleted, and it can be reactivated at any time."
          confirmLabel="Deactivate user"
          onClose={() => setDeactivatingUser(null)}
          onConfirm={async () => { await api.setOrganizationUserActive(deactivatingUser.id, false); setDeactivatingUser(null); await load(); }}
        />
      )}
      {reactivatingUser && (
        <ConfirmActionDialog
          eyebrow="Your organization"
          title={`Reactivate ${reactivatingUser.name}?`}
          body="This restores sign-in access for this account according to its existing role."
          confirmLabel="Reactivate user"
          onClose={() => setReactivatingUser(null)}
          onConfirm={async () => { await api.setOrganizationUserActive(reactivatingUser.id, true); setReactivatingUser(null); await load(); }}
        />
      )}
      {deletingUser && (
        <ConfirmActionDialog
          eyebrow="Your organization"
          title={`Soft delete ${deletingUser.name}?`}
          body="This blocks sign-in and hides the account from your user list. No records are deleted — the account is preserved and can be restored by support if needed."
          confirmLabel="Soft delete user"
          onClose={() => setDeletingUser(null)}
          onConfirm={async () => { await api.archiveOrganizationUser(deletingUser.id); setDeletingUser(null); await load(); }}
        />
      )}
    </div>
  );
}
