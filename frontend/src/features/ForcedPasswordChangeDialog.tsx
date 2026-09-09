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

  // Sizing/radius-only override — --color-primary is now the Source Motion
  // red app-wide, so the shared Input/Button components already render
  // in-brand here, the same as every other page.
  const inputClass = "h-14 rounded-[10px] text-[1.0625rem]";

  return (
    <main className="flex min-h-screen flex-col bg-[#F7F7F8] font-sans">
      <div className="flex flex-1 items-center justify-center px-5 py-10">
        <section
          aria-labelledby="forced-password-title"
          className="w-full max-w-[460px] rounded-xl border border-[#E5E7EB] bg-white p-8 shadow-[0_8px_24px_rgba(31,31,31,0.06)]"
        >
          <img
            src={`${import.meta.env.BASE_URL}assets/source-motion-logo.png`}
            alt="Source Motion Physical Therapy"
            className="mx-auto mb-6 h-auto w-full max-w-[220px] object-contain"
          />
          <p className="m-0 mb-1 text-sm font-bold uppercase tracking-wider text-primary">Security</p>
          <h1 id="forced-password-title" className="m-0 mb-2 text-[clamp(1.75rem,3vw,2.25rem)] font-bold text-[#222222]">
            Set a new password
          </h1>
          <p className="mb-6 text-[1.0625rem] text-[#6B7280]">
            An administrator reset the password for {user.displayName}. Choose a new password to continue.
          </p>

          {error && (
            <p role="alert" className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-base font-medium text-red-700">
              {error}
            </p>
          )}

          <form onSubmit={submit} className="grid gap-4">
            <div>
              <Label htmlFor="forced-new-password" className="text-[1.0625rem]">New password</Label>
              <Input
                id="forced-new-password"
                type="password"
                autoComplete="new-password"
                minLength={12}
                required
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                className={inputClass}
              />
            </div>
            <div>
              <Label htmlFor="forced-confirm-password" className="text-[1.0625rem]">Confirm new password</Label>
              <Input
                id="forced-confirm-password"
                type="password"
                autoComplete="new-password"
                minLength={12}
                required
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                className={inputClass}
              />
            </div>
            <p className="m-0 text-sm text-[#6B7280]">Use at least 12 characters.</p>
            <Button
              type="submit"
              disabled={busy}
              className="mt-2 h-14 w-full rounded-[10px] text-[1.0625rem] font-semibold"
            >
              {busy ? "Saving…" : "Set new password"}
            </Button>
          </form>

          <button
            type="button"
            onClick={onLogout}
            className="mt-4 w-full border-0 bg-transparent p-0 text-center text-base font-medium text-[#6B7280] hover:text-[#222222] hover:underline"
          >
            Log out instead
          </button>
        </section>
      </div>

      <footer className="flex-none px-4 py-4 text-center text-[0.9375rem] text-[#6B7280]">
        &copy; {new Date().getFullYear()} Source Motion Physical Therapy LLC. All rights reserved. Confidential.
      </footer>
    </main>
  );
}
