import { FormEvent, useState } from "react";

import { ApiError, api } from "../api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter, FormRow } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { US_STATES } from "@/lib/usStates";

interface CreateOrganizationUserDialogProps {
  onClose: () => void;
  onCreated: () => Promise<void>;
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

export function CreateOrganizationUserDialog({ onClose, onCreated }: CreateOrganizationUserDialogProps) {
  const [form, setForm] = useState(emptyForm);
  const isLicensedRole = form.role === "therapist" || form.role === "assistant";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      await api.createOrganizationUser(form);
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
    <Dialog titleId="create-org-user-title" eyebrow="Your organization" title="Create user" onClose={onClose} busy={busy} maxWidth="max-w-2xl">
      {error && (
        <p role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {error}
        </p>
      )}
      <form onSubmit={submit}>
        <FormRow label="User ID" htmlFor="create-org-user-username" error={fieldErrors.username}>
          <Input id="create-org-user-username" required value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="E-Mail Address" htmlFor="create-org-user-email" error={fieldErrors.email}>
          <Input id="create-org-user-email" required type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="First name" htmlFor="create-org-user-first-name" error={fieldErrors.firstName}>
          <Input id="create-org-user-first-name" required value={form.firstName} onChange={(event) => setForm({ ...form, firstName: event.target.value })} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="Last name" htmlFor="create-org-user-last-name" error={fieldErrors.lastName}>
          <Input id="create-org-user-last-name" required value={form.lastName} onChange={(event) => setForm({ ...form, lastName: event.target.value })} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="Access Level" htmlFor="create-org-user-role" error={fieldErrors.role}>
          <select
            id="create-org-user-role"
            value={form.role}
            onChange={(event) => setForm({ ...form, role: event.target.value })}
            className={selectClass}
          >
            {roles.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </FormRow>
        <FormRow label="Credential" htmlFor="create-org-user-credential">
          <Input id="create-org-user-credential" value={form.credential} onChange={(event) => setForm({ ...form, credential: event.target.value })} className="text-[1.0625rem]" placeholder="e.g. DPT, PT, PTA" />
        </FormRow>
        {isLicensedRole && (
          <>
            <FormRow label="License Number" htmlFor="create-org-user-license-number" error={fieldErrors.licenseNumber}>
              <Input id="create-org-user-license-number" required value={form.licenseNumber} onChange={(event) => setForm({ ...form, licenseNumber: event.target.value })} className="text-[1.0625rem]" />
            </FormRow>
            <FormRow label="Issuing State" htmlFor="create-org-user-license-state" error={fieldErrors.licenseIssuingState}>
              <Select id="create-org-user-license-state" required value={form.licenseIssuingState} onChange={(event) => setForm({ ...form, licenseIssuingState: event.target.value })} className="text-[1.0625rem]">
                <option value="">Select a state</option>
                {US_STATES.map((state) => (
                  <option key={state.code} value={state.code}>{state.name}</option>
                ))}
              </Select>
            </FormRow>
            <FormRow label="License Expires" htmlFor="create-org-user-license-expires" error={fieldErrors.licenseExpiresAt}>
              <Input id="create-org-user-license-expires" required type="date" value={form.licenseExpiresAt} onChange={(event) => setForm({ ...form, licenseExpiresAt: event.target.value })} className="text-[1.0625rem]" />
            </FormRow>
          </>
        )}
        <FormRow label="Temporary Password" htmlFor="create-org-user-password" error={fieldErrors.password}>
          <Input id="create-org-user-password" required type="password" autoComplete="new-password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="Confirm Password" htmlFor="create-org-user-confirm-password" error={fieldErrors.confirmPassword}>
          <Input id="create-org-user-confirm-password" required type="password" autoComplete="new-password" value={form.confirmPassword} onChange={(event) => setForm({ ...form, confirmPassword: event.target.value })} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="MFA policy">
          <label className="flex h-[54px] items-center gap-2 text-[0.9375rem] font-medium text-foreground">
            <input
              type="checkbox"
              checked={form.mustUseMfa}
              onChange={(event) => setForm({ ...form, mustUseMfa: event.target.checked })}
              className="h-4 w-4"
            />
            Require MFA under the organization policy
          </label>
        </FormRow>
        <DialogFooter>
          <Button type="button" variant="secondary" disabled={busy} onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy}>{busy ? "Creating..." : "Create user"}</Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
}
