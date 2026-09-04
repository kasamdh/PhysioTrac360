import { FormEvent, useState } from "react";

import { ApiError } from "../api/client";
import type { ManagedClientUser } from "../api/types";

interface EditUserDialogProps {
  user: ManagedClientUser;
  onClose: () => void;
  onSave: (body: Record<string, unknown>) => Promise<unknown>;
  onSaved: () => Promise<void>;
  isOwnAccount?: boolean;
}

const roles = [
  ["admin", "Organization administrator"],
  ["director", "Clinical director"],
  ["therapist", "Physical therapist"],
  ["assistant", "PTA / therapy assistant"],
  ["scheduler", "Scheduler / front desk"],
  ["biller", "Billing specialist"],
  ["compliance", "Compliance officer"],
] as const;

export function EditUserDialog({ user, onClose, onSave, onSaved, isOwnAccount = false }: EditUserDialogProps) {
  const [form, setForm] = useState({
    firstName: user.firstName,
    lastName: user.lastName,
    email: user.email,
    role: user.role,
    mustUseMfa: user.mustUseMfa,
  });
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      await onSave(form);
      await onSaved();
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        setError(requestError.message);
        setFieldErrors(requestError.fields);
      } else {
        setError("Unable to update this user.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="move-dialog client-dialog" role="dialog" aria-modal="true" aria-labelledby="edit-user-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">&times;</button>
        <p className="eyebrow">{user.clientName ? `#${user.clientNumber} ${user.clientName}` : "User"}</p>
        <h2 id="edit-user-title">Edit {user.name}</h2>
        {error && <p className="form-error" role="alert">{error}</p>}
        <form className="stack-form" onSubmit={submit}>
          <div className="field-grid">
            <label>First name<input required value={form.firstName} onChange={(event) => setForm({ ...form, firstName: event.target.value })} />{fieldErrors.firstName && <small className="field-error">{fieldErrors.firstName}</small>}</label>
            <label>Last name<input required value={form.lastName} onChange={(event) => setForm({ ...form, lastName: event.target.value })} />{fieldErrors.lastName && <small className="field-error">{fieldErrors.lastName}</small>}</label>
            <label>Email<input required type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} />{fieldErrors.email && <small className="field-error">{fieldErrors.email}</small>}</label>
            <label>Role<select disabled={isOwnAccount} value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}>{roles.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>{isOwnAccount ? <small className="muted">You cannot change your own role.</small> : fieldErrors.role && <small className="field-error">{fieldErrors.role}</small>}</label>
          </div>
          <label className="check-label"><input type="checkbox" disabled={isOwnAccount} checked={form.mustUseMfa} onChange={(event) => setForm({ ...form, mustUseMfa: event.target.checked })} /> Require MFA under the client policy</label>
          {isOwnAccount && <small className="muted">You cannot opt your own account out of MFA policy.</small>}
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
            <button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving..." : "Save changes"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
