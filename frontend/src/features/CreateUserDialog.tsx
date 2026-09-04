import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ManagedClient } from "../api/types";

interface CreateUserDialogProps {
  onClose: () => void;
  onCreated: () => Promise<void>;
}

const emptyForm = {
  clientNumber: "",
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

export function CreateUserDialog({ onClose, onCreated }: CreateUserDialogProps) {
  const [clients, setClients] = useState<ManagedClient[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    api.managedClients("", { pageSize: "100", sort: "client_name" }).then((result) => setClients(result.clients)).catch(() => undefined);
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      await api.createUser({ ...form, clientNumber: Number(form.clientNumber) });
      await onCreated();
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
    <div className="modal-backdrop">
      <section className="move-dialog client-dialog" role="dialog" aria-modal="true" aria-labelledby="create-user-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">&times;</button>
        <p className="eyebrow">Platform · Users</p>
        <h2 id="create-user-title">Add user</h2>
        {error && <p className="form-error" role="alert">{error}</p>}

        <form className="stack-form" onSubmit={submit}>
          <label>
            Client
            <select required aria-invalid={Boolean(fieldErrors.clientNumber)} value={form.clientNumber} onChange={(event) => setForm({ ...form, clientNumber: event.target.value })}>
              <option value="" disabled>Choose a client</option>
              {clients.map((client) => (
                <option key={client.id} value={client.clientNumber}>#{client.clientNumber} {client.clientName}</option>
              ))}
            </select>
            {fieldErrors.clientNumber && <small className="field-error">{fieldErrors.clientNumber}</small>}
          </label>

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
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
            <button className="primary-button" type="submit" disabled={busy}>{busy ? "Creating..." : "Create user"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
