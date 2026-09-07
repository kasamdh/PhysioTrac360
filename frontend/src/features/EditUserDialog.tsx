import { FormEvent, useState } from "react";
import { Info } from "lucide-react";

import { ApiError } from "../api/client";
import type { ManagedClientUser, UserLicenseInfo } from "../api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter, FormRow } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { LicenseBanner } from "@/components/ui/license-banner";
import { StatusBanner } from "@/components/ui/status-banner";
import { formatDateTime } from "../lib/format";
import { LicenseListSection } from "./LicenseListSection";
import { StatusActionDialog } from "./StatusActionDialog";

interface EditUserDialogProps {
  user: ManagedClientUser;
  onClose: () => void;
  onSave: (body: Record<string, unknown>) => Promise<unknown>;
  onSaved: () => Promise<void>;
  onStatusAction: (action: string, reason: string) => Promise<unknown>;
  onRevokeSessions: () => Promise<unknown>;
  onCreateLicense: (body: Record<string, unknown>) => Promise<{ license: UserLicenseInfo }>;
  onUpdateLicense: (licenseId: string, body: Record<string, unknown>) => Promise<{ license: UserLicenseInfo }>;
  onDeleteLicense: (licenseId: string) => Promise<unknown>;
  onUploadLicenseDocument: (licenseId: string, file: File) => Promise<{ license: UserLicenseInfo }>;
  onVerifyLicense: (licenseId: string, notes: string) => Promise<{ license: UserLicenseInfo }>;
  licenseDocumentUrl: (licenseId: string) => string;
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

const selectClass = "flex h-[54px] w-full rounded-md border-0 bg-white px-4 text-[1.0625rem] text-foreground shadow-[inset_0_0_0_1px_var(--color-input)] outline-none focus:shadow-[inset_0_0_0_1.5px_var(--color-primary)] disabled:cursor-not-allowed disabled:opacity-50";

interface PendingAction {
  action: string;
  eyebrow: string;
  title: string;
  body: string;
  confirmLabel: string;
  destructive?: boolean;
  requireReason?: boolean;
  reasonLabel?: string;
  isSessionRevoke?: boolean;
}

export function EditUserDialog({
  user, onClose, onSave, onSaved, onStatusAction, onRevokeSessions,
  onCreateLicense, onUpdateLicense, onDeleteLicense, onUploadLicenseDocument, onVerifyLicense, licenseDocumentUrl,
  isOwnAccount = false,
}: EditUserDialogProps) {
  const [form, setForm] = useState({
    username: user.username,
    password: "",
    firstName: user.firstName,
    lastName: user.lastName,
    email: user.email,
    role: user.role,
    credential: user.credential,
    mustUseMfa: user.mustUseMfa,
  });
  const isLicensedRole = form.role === "therapist" || form.role === "assistant";
  const [licenses, setLicenses] = useState<UserLicenseInfo[]>(user.licenses);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);

  async function handleCreateLicense(body: Record<string, unknown>) {
    const result = await onCreateLicense(body);
    setLicenses((current) => [...current, result.license]);
  }
  async function handleUpdateLicense(licenseId: string, body: Record<string, unknown>) {
    const result = await onUpdateLicense(licenseId, body);
    setLicenses((current) => current.map((license) => (license.id === licenseId ? result.license : license)));
  }
  async function handleDeleteLicense(licenseId: string) {
    await onDeleteLicense(licenseId);
    setLicenses((current) => current.filter((license) => license.id !== licenseId));
  }
  async function handleUploadLicenseDocument(licenseId: string, file: File) {
    const result = await onUploadLicenseDocument(licenseId, file);
    setLicenses((current) => current.map((license) => (license.id === licenseId ? result.license : license)));
  }
  async function handleVerifyLicense(licenseId: string, notes: string) {
    const result = await onVerifyLicense(licenseId, notes);
    setLicenses((current) => current.map((license) => (license.id === licenseId ? result.license : license)));
  }

  const eyebrow = user.clientName ? `#${user.clientNumber} ${user.clientName}` : "User";
  const readOnly = user.status === "deleted";

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

  async function runStatusAction(reason: string) {
    if (!pendingAction) return;
    if (pendingAction.isSessionRevoke) {
      await onRevokeSessions();
    } else {
      await onStatusAction(pendingAction.action, reason);
    }
    setPendingAction(null);
    await onSaved();
  }

  const statusActions: { key: string; label: string; make: () => PendingAction }[] = [];
  if (!isOwnAccount) {
    if (user.status === "active") {
      statusActions.push(
        {
          key: "deactivate",
          label: "Deactivate User",
          make: () => ({
            action: "deactivate",
            eyebrow,
            title: `Deactivate ${user.name}?`,
            body: "This immediately blocks sign-in for this account. No data is deleted, and it can be reactivated at any time.",
            confirmLabel: "Deactivate user",
          }),
        },
        {
          key: "suspend",
          label: "Suspend User",
          make: () => ({
            action: "suspend",
            eyebrow,
            title: `Suspend ${user.name}?`,
            body: "This blocks sign-in immediately and requires an administrator to explicitly reactivate the account — it will not expire on its own.",
            confirmLabel: "Suspend user",
            destructive: true,
            requireReason: true,
            reasonLabel: "Reason for suspension",
          }),
        },
      );
    } else if (user.status === "inactive") {
      statusActions.push({
        key: "activate",
        label: "Activate User",
        make: () => ({
          action: "activate",
          eyebrow,
          title: `Activate ${user.name}?`,
          body: "This restores sign-in access for this account according to its existing role.",
          confirmLabel: "Activate user",
        }),
      });
    } else if (user.status === "locked_out") {
      statusActions.push({
        key: "unlock",
        label: "Unlock Account",
        make: () => ({
          action: "unlock",
          eyebrow,
          title: "Are you sure you want to unlock this account?",
          body: "This clears the failed sign-in count and lockout immediately, letting this user sign in again right away.",
          confirmLabel: "Unlock account",
        }),
      });
    } else if (user.status === "suspended") {
      statusActions.push({
        key: "reactivate",
        label: "Reactivate User",
        make: () => ({
          action: "reactivate",
          eyebrow,
          title: `Reactivate ${user.name}?`,
          body: "This restores sign-in access and clears the suspension.",
          confirmLabel: "Reactivate user",
        }),
      });
    } else if (user.status === "deleted") {
      statusActions.push({
        key: "restore",
        label: "Restore User",
        make: () => ({
          action: "restore",
          eyebrow,
          title: `Restore ${user.name}?`,
          body: "This is a privileged action: it restores sign-in access and returns the account to the default list. All historical records were preserved while deleted.",
          confirmLabel: "Restore user",
        }),
      });
    }
    if (user.status !== "deleted") {
      statusActions.push({
        key: "delete",
        label: "Delete User",
        make: () => ({
          action: "delete",
          eyebrow,
          title: `Delete ${user.name}?`,
          body: "This blocks sign-in and hides the account from the default list. No records are deleted — clinical history, signatures, and audit events are preserved, and the account can be restored later by an authorized administrator.",
          confirmLabel: "Delete user",
          destructive: true,
          requireReason: true,
          reasonLabel: "Reason (optional)",
        }),
      });
    }
  }

  return (
    <Dialog titleId="edit-user-title" eyebrow={eyebrow} title="Edit User" onClose={onClose} busy={busy} maxWidth="max-w-3xl">
      <StatusBanner user={user} />
      <LicenseBanner licenses={licenses} />

      {statusActions.length > 0 && (
        <div className="mb-6 flex flex-wrap gap-2">
          {statusActions.map((item) => (
            <Button
              key={item.key}
              type="button"
              variant={item.key === "suspend" || item.key === "delete" ? "destructive" : "secondary"}
              onClick={() => setPendingAction(item.make())}
            >
              {item.label}
            </Button>
          ))}
        </div>
      )}

      {!isOwnAccount && (
        <div className="mb-6">
          <h3 className="m-0 mb-2 text-sm font-bold uppercase tracking-wide text-muted-foreground">
            Active Sessions: {user.activeSessions.length}
          </h3>
          {user.activeSessions.length > 0 && (
            <div className="mb-2 grid gap-1.5">
              {user.activeSessions.map((session) => (
                <div key={session.id} className="text-sm text-foreground">
                  {session.browserName || "Unknown browser"} / {session.deviceName || "Unknown device"}
                  <span className="text-muted-foreground"> — Last active: {formatDateTime(session.lastActivityAt)}</span>
                </div>
              ))}
            </div>
          )}
          {user.activeSessions.length > 0 && (
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={() =>
                setPendingAction({
                  action: "revoke-sessions",
                  eyebrow,
                  title: `Sign ${user.name} out from all devices?`,
                  body: "This immediately revokes every active session for this user. They will need to sign in again.",
                  confirmLabel: "Sign out from all devices",
                  destructive: true,
                  isSessionRevoke: true,
                })
              }
            >
              Sign Out User From All Devices
            </Button>
          )}
        </div>
      )}

      {isLicensedRole && !readOnly && (
        <LicenseListSection
          licenses={licenses}
          onCreate={handleCreateLicense}
          onUpdate={handleUpdateLicense}
          onDelete={handleDeleteLicense}
          onUploadDocument={handleUploadLicenseDocument}
          onVerify={handleVerifyLicense}
          documentUrl={licenseDocumentUrl}
        />
      )}

      {error && (
        <p role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {error}
        </p>
      )}

      {readOnly ? (
        <p className="text-sm text-muted-foreground">
          This account is read-only while deleted. Use Restore User above if this account needs to be reinstated.
        </p>
      ) : (
        <form onSubmit={submit}>
          <FormRow label="User ID" htmlFor="edit-user-username" error={fieldErrors.username}>
            <Input id="edit-user-username" required value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} className="text-[1.0625rem]" />
          </FormRow>
          <FormRow
            label="New Password"
            htmlFor="edit-user-password"
            error={isOwnAccount ? undefined : fieldErrors.password}
            hint={isOwnAccount ? "Use the self-service change password option for your own account." : undefined}
          >
            <div className="flex items-center gap-2">
              <Input
                id="edit-user-password"
                type="password"
                autoComplete="new-password"
                disabled={isOwnAccount}
                value={form.password}
                onChange={(event) => setForm({ ...form, password: event.target.value })}
                placeholder="Leave blank to keep the current password"
                className="text-[1.0625rem]"
              />
              <span
                title="Leave blank to keep the current password. Otherwise, enter at least 8 characters. The user will be required to set their own password the next time they sign in."
                className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary text-white"
              >
                <Info className="h-3.5 w-3.5" aria-hidden="true" />
                <span className="sr-only">Password requirements</span>
              </span>
            </div>
          </FormRow>
          <FormRow label="First name" htmlFor="edit-user-first-name" error={fieldErrors.firstName}>
            <Input id="edit-user-first-name" required value={form.firstName} onChange={(event) => setForm({ ...form, firstName: event.target.value })} className="text-[1.0625rem]" />
          </FormRow>
          <FormRow label="Last name" htmlFor="edit-user-last-name" error={fieldErrors.lastName}>
            <Input id="edit-user-last-name" required value={form.lastName} onChange={(event) => setForm({ ...form, lastName: event.target.value })} className="text-[1.0625rem]" />
          </FormRow>
          <FormRow label="E-Mail Address" htmlFor="edit-user-email" error={fieldErrors.email}>
            <Input id="edit-user-email" required type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} className="text-[1.0625rem]" />
          </FormRow>
          <FormRow
            label="Access Level"
            htmlFor="edit-user-role"
            hint={isOwnAccount ? "You cannot change your own role." : undefined}
            error={isOwnAccount ? undefined : fieldErrors.role}
          >
            <select
              id="edit-user-role"
              disabled={isOwnAccount}
              value={form.role}
              onChange={(event) => setForm({ ...form, role: event.target.value })}
              className={selectClass}
            >
              {roles.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </FormRow>
          <FormRow label="Credential" htmlFor="edit-user-credential">
            <Input id="edit-user-credential" value={form.credential} onChange={(event) => setForm({ ...form, credential: event.target.value })} placeholder="e.g. DPT, PT, PTA" className="text-[1.0625rem]" />
          </FormRow>
          <FormRow label="MFA policy" hint={isOwnAccount ? "You cannot opt your own account out of MFA policy." : undefined}>
            <label className="flex h-[54px] items-center gap-2 text-[0.9375rem] font-medium text-foreground">
              <input
                type="checkbox"
                disabled={isOwnAccount}
                checked={form.mustUseMfa}
                onChange={(event) => setForm({ ...form, mustUseMfa: event.target.checked })}
                className="h-4 w-4"
              />
              Require MFA under the client policy
            </label>
          </FormRow>
          <DialogFooter>
            <Button type="button" variant="secondary" disabled={busy} onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={busy}>{busy ? "Saving..." : "Save and Close"}</Button>
          </DialogFooter>
        </form>
      )}

      {pendingAction && (
        <StatusActionDialog
          eyebrow={pendingAction.eyebrow}
          title={pendingAction.title}
          body={pendingAction.body}
          confirmLabel={pendingAction.confirmLabel}
          destructive={pendingAction.destructive}
          requireReason={pendingAction.requireReason}
          reasonLabel={pendingAction.reasonLabel}
          onClose={() => setPendingAction(null)}
          onConfirm={runStatusAction}
        />
      )}
    </Dialog>
  );
}
