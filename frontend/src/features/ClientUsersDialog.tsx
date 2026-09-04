import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ManagedClient, ManagedClientUser } from "../api/types";

interface ClientUsersDialogProps {
  client: ManagedClient;
  onClose: () => void;
}

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

export function ClientUsersDialog({ client, onClose }: ClientUsersDialogProps) {
  const [users, setUsers] = useState<ManagedClientUser[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  async function load() {
    setLoading(true);
    try {
      const result = await api.managedClientUsers(client.clientNumber);
      setUsers(result.users);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load client users.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [client.clientNumber]);

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      await api.createManagedClientUser(client.clientNumber, form);
      setForm(emptyForm);
      await load();
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        setError(requestError.message);
        setFieldErrors(requestError.fields);
      } else {
        setError("Unable to create the client user.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="move-dialog client-dialog" role="dialog" aria-modal="true" aria-labelledby="client-users-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">&times;</button>
        <p className="eyebrow">Client #{client.clientNumber}</p>
        <h2 id="client-users-title">Manage users for {client.clientName}</h2>
        <p className="muted">New accounts are scoped to this client. Platform access cannot be assigned here.</p>
        {error && <p className="form-error" role="alert">{error}</p>}

        <form className="stack-form" onSubmit={createUser}>
          <h3>Create client user</h3>
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
          <label className="check-label"><input type="checkbox" checked={form.mustUseMfa} onChange={(event) => setForm({ ...form, mustUseMfa: event.target.checked })} /> Require MFA under the client policy</label>
          <div className="button-row"><button className="primary-button" type="submit" disabled={busy}>{busy ? "Creating..." : "Create user"}</button></div>
        </form>

        <section className="client-user-list" aria-labelledby="client-user-list-title">
          <h3 id="client-user-list-title">Current users</h3>
          {loading ? <p className="muted">Loading users...</p> : (
            <div className="table-wrap"><table><thead><tr><th>User</th><th>Username</th><th>Role</th><th>MFA</th><th>Status</th></tr></thead><tbody>{users.map((user) => <tr key={user.id}><td><strong>{user.name}</strong><small>{user.email}</small></td><td>{user.username}</td><td>{user.roleLabel}</td><td>{user.mustUseMfa ? "Required" : "Optional"}</td><td>{user.active ? "Active" : "Inactive"}</td></tr>)}</tbody></table></div>
          )}
          {!loading && !users.length && <p className="empty-copy">This client has no users yet.</p>}
        </section>
      </section>
    </div>
  );
}
