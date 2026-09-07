import { FormEvent, useState } from "react";

import { ApiError, api } from "../api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter, FormRow } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

interface AddClientDialogProps {
  onClose: () => void;
  onCreated: (invitationUrl: string) => Promise<void> | void;
}

const emptyForm = {
  clientName: "",
  clientEmail: "",
  addressLine1: "",
  city: "",
  state: "",
  zipCode: "",
  subscriptionTier: "professional",
  timezone: "America/New_York",
  adminFirstName: "",
  adminLastName: "",
  adminEmail: "",
  comments: "",
};

const TIERS = [["starter", "Starter"], ["professional", "Professional"], ["premium", "Premium"], ["enterprise", "Enterprise"]] as const;
const TIMEZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "America/Phoenix", "Pacific/Honolulu"];

const selectClass = "flex h-[54px] w-full rounded-md border-0 bg-white px-4 text-[1.0625rem] text-foreground shadow-[inset_0_0_0_1px_var(--color-input)] outline-none focus:shadow-[inset_0_0_0_1.5px_var(--color-primary)] disabled:cursor-not-allowed disabled:opacity-50";

export function AddClientDialog({ onClose, onCreated }: AddClientDialogProps) {
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  function update(field: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setFieldErrors((current) => ({ ...current, [field]: "" }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      const result = await api.createManagedClient(form);
      await onCreated(result.invitationUrl);
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        setError(requestError.message);
        setFieldErrors(requestError.fields);
      } else {
        setError("Unable to create client.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog titleId="add-client-title" eyebrow="Provision tenant" title="Add client" onClose={onClose} busy={busy} maxWidth="max-w-3xl">
      {error && (
        <p role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {error}
        </p>
      )}
      <form onSubmit={submit}>
        <h3 className="m-0 mb-2 text-sm font-bold uppercase tracking-wide text-muted-foreground">Facility information</h3>
        <FormRow label="Client name" htmlFor="add-client-name" error={fieldErrors.clientName}>
          <Input id="add-client-name" required value={form.clientName} onChange={(event) => update("clientName", event.target.value)} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="Client email" htmlFor="add-client-email" error={fieldErrors.clientEmail}>
          <Input id="add-client-email" required type="email" value={form.clientEmail} onChange={(event) => update("clientEmail", event.target.value)} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="Address" htmlFor="add-client-address" error={fieldErrors.addressLine1}>
          <Input id="add-client-address" required value={form.addressLine1} onChange={(event) => update("addressLine1", event.target.value)} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="City" htmlFor="add-client-city" error={fieldErrors.city}>
          <Input id="add-client-city" required value={form.city} onChange={(event) => update("city", event.target.value)} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="State" htmlFor="add-client-state" error={fieldErrors.state}>
          <Input id="add-client-state" required value={form.state} onChange={(event) => update("state", event.target.value)} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="ZIP" htmlFor="add-client-zip" error={fieldErrors.zipCode}>
          <Input id="add-client-zip" required value={form.zipCode} onChange={(event) => update("zipCode", event.target.value)} className="text-[1.0625rem]" />
        </FormRow>

        <h3 className="m-0 mb-2 mt-4 text-sm font-bold uppercase tracking-wide text-muted-foreground">Account settings</h3>
        <FormRow label="Subscription" htmlFor="add-client-tier">
          <select id="add-client-tier" value={form.subscriptionTier} onChange={(event) => update("subscriptionTier", event.target.value)} className={selectClass}>
            {TIERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </FormRow>
        <FormRow label="Timezone" htmlFor="add-client-timezone">
          <select id="add-client-timezone" value={form.timezone} onChange={(event) => update("timezone", event.target.value)} className={selectClass}>
            {TIMEZONES.map((zone) => <option key={zone} value={zone}>{zone}</option>)}
          </select>
        </FormRow>

        <h3 className="m-0 mb-2 mt-4 text-sm font-bold uppercase tracking-wide text-muted-foreground">Primary administrator</h3>
        <FormRow label="First name" htmlFor="add-client-admin-first-name" error={fieldErrors.adminFirstName}>
          <Input id="add-client-admin-first-name" required value={form.adminFirstName} onChange={(event) => update("adminFirstName", event.target.value)} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="Last name" htmlFor="add-client-admin-last-name" error={fieldErrors.adminLastName}>
          <Input id="add-client-admin-last-name" required value={form.adminLastName} onChange={(event) => update("adminLastName", event.target.value)} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="Admin email" htmlFor="add-client-admin-email" error={fieldErrors.adminEmail}>
          <Input id="add-client-admin-email" required type="email" value={form.adminEmail} onChange={(event) => update("adminEmail", event.target.value)} className="text-[1.0625rem]" />
        </FormRow>
        <FormRow label="Comments" htmlFor="add-client-comments">
          <Textarea id="add-client-comments" rows={3} value={form.comments} onChange={(event) => update("comments", event.target.value)} />
        </FormRow>

        <DialogFooter>
          <Button type="button" variant="secondary" disabled={busy} onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy}>{busy ? "Creating..." : "Create client"}</Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
}
