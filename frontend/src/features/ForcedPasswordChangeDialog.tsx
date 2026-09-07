import { FormEvent, useState } from "react";

import { ApiError, api } from "../api/client";
import type { WorkspaceUser } from "../api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface ForcedPasswordChangeDialogProps {
  user: WorkspaceUser;
  onChanged: (user: WorkspaceUser) => void;
  onLogout: () => void;
}

export function ForcedPasswordChangeDialog({ user, onChanged, onLogout }: ForcedPasswordChangeDialogProps) {
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (newPassword.length < 12) {
      setError("Choose a new password with at least 12 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("New passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.changePassword({ newPassword, confirmPassword });
      onChanged({ ...user, mustChangePassword: false });
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to change your password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen flex-col bg-white font-sans">
      <header className="flex flex-none items-center gap-[0.7rem] bg-gradient-to-r from-[#0b2b27] to-primary-deep px-[1.4rem] py-[0.8rem] text-white">
        <span
          className="grid h-[34px] w-[34px] place-items-center rounded-[9px] border border-white/30 bg-white/16 text-[0.8rem] font-semibold tracking-[0.04em]"
          aria-hidden="true"
        >
          PT
        </span>
        <strong className="text-[1.05rem] font-semibold tracking-[-0.01em]">
          PhysioTrac<em className="text-primary-soft">360</em>
        </strong>
      </header>

      <div className="flex flex-1 items-center justify-center bg-[#eef2f1] px-5 py-10">
        <section
          aria-labelledby="forced-password-title"
          className="w-full max-w-[460px] rounded-[10px] bg-white p-8 shadow-[0_18px_40px_rgb(15_23_42_/_12%)]"
        >
          <p className="m-0 mb-1 text-xs font-bold uppercase tracking-wider text-primary-deep">Security</p>
          <h1 id="forced-password-title" className="m-0 mb-2 text-2xl font-bold text-[#172127]">
            Set a new password
          </h1>
          <p className="mb-6 text-sm text-muted-foreground">
            An administrator reset the password for {user.displayName}. Choose a new password to continue.
          </p>

          {error && (
            <p role="alert" className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
              {error}
            </p>
          )}

          <form onSubmit={submit} className="grid gap-4">
            <div>
              <Label htmlFor="forced-new-password">New password</Label>
              <Input
                id="forced-new-password"
                type="password"
                autoComplete="new-password"
                minLength={12}
                required
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="forced-confirm-password">Confirm new password</Label>
              <Input
                id="forced-confirm-password"
                type="password"
                autoComplete="new-password"
                minLength={12}
                required
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
              />
            </div>
            <p className="m-0 text-xs text-muted-foreground">Use at least 12 characters.</p>
            <Button type="submit" disabled={busy} className="mt-2 h-14 w-full">
              {busy ? "Saving…" : "Set new password"}
            </Button>
          </form>

          <button
            type="button"
            onClick={onLogout}
            className="mt-4 w-full border-0 bg-transparent p-0 text-center text-sm font-medium text-muted-foreground hover:text-foreground hover:underline"
          >
            Log out instead
          </button>
        </section>
      </div>

      <footer className="flex-none px-4 py-4 text-center text-[0.9375rem] text-[#8b98a3]">
        PhysioTrac360 &copy; {new Date().getFullYear()} PhysioTrac360, Inc. All rights reserved. Confidential.
      </footer>
    </main>
  );
}
