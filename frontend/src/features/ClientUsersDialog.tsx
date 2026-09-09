import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ManagedClient, ManagedClientUser } from "../api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter, FormRow } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { LicenseBadge } from "@/components/ui/license-banner";
import { Select } from "@/components/ui/select";
import { StatusBadge } from "@/components/ui/status-banner";
import { US_STATES } from "@/lib/usStates";

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
  licenseNumber: "",
  licenseIssuingState: "",
  licenseExpiresAt: "",
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

const selectClass = "flex h-[54px] w-full rounded-md border-0 bg-white px-4 text-[1.0625rem] text-foreground shadow-[inset_0_0_0_1px_var(--color-input)] outline-none focus:shadow-[inset_0_0_0_1.5px_var(--color-primary)] disabled:cursor-not-allowed disabled:opacity-50";

export function ClientUsersDialog({ client, onClose }: ClientUsersDialogProps) {
  const [users, setUsers] = useState<ManagedClientUser[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const isLicensedRole = form.role === "therapist" || form.role === "assistant";

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
    <Dialog titleId="client-users-title" eyebrow={`Client #${client.clientNumber}`} title={`Manage users for ${client.clientName}`} onClose={onClose} busy={busy} maxWidth="max-w-3xl">
      <p className="m-0 mb-4 text-sm text-muted-foreground">New accounts are scoped to this client. Platform access cannot be assigned here.</p>
      {error && (
        <p role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {error}
        </p>
      )}

      <form onSubmit={createUser}>
        <h3 className="m-0 mb-2 text-sm font-bold uppercase tracking-wide text-muted-foreground">Create client user</h3>
        <FormRow label="Username" htmlFor="client-user-username" error={fieldErrors.username}>
          <Input id="client-user-username" required value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="Email" htmlFor="client-user-email" error={fieldErrors.email}>
          <Input id="client-user-email" required type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="First name" htmlFor="client-user-first-name" error={fieldErrors.firstName}>
          <Input id="client-user-first-name" required value={form.firstName} onChange={(event) => setForm({ ...form, firstName: event.target.value })} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="Last name" htmlFor="client-user-last-name" error={fieldErrors.lastName}>
          <Input id="client-user-last-name" required value={form.lastName} onChange={(event) => setForm({ ...form, lastName: event.target.value })} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="Role" htmlFor="client-user-role" error={fieldErrors.role}>
          <select id="client-user-role" value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })} className={selectClass}>
            {roles.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </FormRow>
        <FormRow label="Credential" htmlFor="client-user-credential">
          <Input id="client-user-credential" value={form.credential} onChange={(event) => setForm({ ...form, credential: event.target.value })} className="text-[1.0625rem]" placeholder="e.g. DPT, PT, PTA" />
        </FormRow>
        {isLicensedRole && (
          <>
            <FormRow label="License Number" htmlFor="client-user-license-number" error={fieldErrors.licenseNumber}>
              <Input id="client-user-license-number" required value={form.licenseNumber} onChange={(event) => setForm({ ...form, licenseNumber: event.target.value })} className="text-[1.0625rem]" />
            </FormRow>
            <FormRow label="Issuing State" htmlFor="client-user-license-state" error={fieldErrors.licenseIssuingState}>
              <Select id="client-user-license-state" required value={form.licenseIssuingState} onChange={(event) => setForm({ ...form, licenseIssuingState: event.target.value })} className="text-[1.0625rem]">
                <option value="">Select a state</option>
                {US_STATES.map((state) => (
                  <option key={state.code} value={state.code}>{state.name}</option>
                ))}
              </Select>
            </FormRow>
            <FormRow label="License Expires" htmlFor="client-user-license-expires" error={fieldErrors.licenseExpiresAt}>
              <Input id="client-user-license-expires" required type="date" value={form.licenseExpiresAt} onChange={(event) => setForm({ ...form, licenseExpiresAt: event.target.value })} className="text-[1.0625rem]" />
            </FormRow>
          </>
        )}
        <FormRow label="Temporary password" htmlFor="client-user-password" error={fieldErrors.password}>
          <Input id="client-user-password" required type="password" autoComplete="new-password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="Confirm password" htmlFor="client-user-confirm-password" error={fieldErrors.confirmPassword}>
          <Input id="client-user-confirm-password" required type="password" autoComplete="new-password" value={form.confirmPassword} onChange={(event) => setForm({ ...form, confirmPassword: event.target.value })} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="MFA policy">
          <label className="flex h-[54px] items-center gap-2 text-[0.9375rem] font-medium text-foreground">
            <input
              type="checkbox"
              checked={form.mustUseMfa}
              onChange={(event) => setForm({ ...form, mustUseMfa: event.target.checked })}
              className="h-4 w-4"
            />
            Require MFA under the client policy
          </label>
        </FormRow>
        <DialogFooter>
          <Button type="submit" disabled={busy}>{busy ? "Creating..." : "Create user"}</Button>
        </DialogFooter>
      </form>

      <section aria-labelledby="client-user-list-title" className="mt-6">
        <h3 id="client-user-list-title" className="m-0 mb-3 text-sm font-bold uppercase tracking-wide text-muted-foreground">Current users</h3>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading users...</p>
        ) : (
          <div className="overflow-hidden rounded-xl border border-border">
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/50 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <th className="px-4 py-3">User</th>
                    <th className="px-4 py-3">Username</th>
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
                        <div className="font-semibold text-foreground">{user.name}</div>
                        <div className="text-xs text-muted-foreground">{user.email}</div>
                      </td>
                      <td className="px-4 py-3 text-foreground">{user.username}</td>
                      <td className="px-4 py-3 text-foreground">{user.roleLabel}</td>
                      <td className="px-4 py-3 text-muted-foreground">{user.mustUseMfa ? "Required" : "Optional"}</td>
                      <td className="px-4 py-3"><StatusBadge status={user.status} /></td>
                      <td className="px-4 py-3"><LicenseBadge status={user.licenseAlertStatus} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!users.length && <p className="px-4 py-10 text-center text-sm text-muted-foreground">This client has no users yet.</p>}
          </div>
        )}
      </section>
    </Dialog>
  );
}
