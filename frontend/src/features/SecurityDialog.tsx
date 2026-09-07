import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { UserSessionInfo, WorkspaceUser } from "../api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter } from "@/components/ui/dialog";
import { formatDateTime } from "../lib/format";
import { ChangePasswordDialog } from "./ChangePasswordDialog";

interface SecurityDialogProps {
  user: WorkspaceUser;
  onClose: () => void;
}

export function SecurityDialog({ user, onClose }: SecurityDialogProps) {
  const [sessions, setSessions] = useState<UserSessionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showChangePassword, setShowChangePassword] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const result = await api.mySessions();
      setSessions(result.sessions);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load sessions.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  async function signOutSession(sessionId: string) {
    setBusy(true);
    setError("");
    try {
      await api.revokeMySession(sessionId);
      await load();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to sign out that session.");
    } finally {
      setBusy(false);
    }
  }

  async function signOutOthers() {
    setBusy(true);
    setError("");
    try {
      await api.revokeMyOtherSessions();
      await load();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to sign out other sessions.");
    } finally {
      setBusy(false);
    }
  }

  const otherSessionCount = sessions.filter((session) => !session.isCurrent).length;

  return (
    <Dialog titleId="security-dialog-title" eyebrow="Account" title="Security" onClose={onClose} busy={busy} maxWidth="max-w-lg">
      {error && (
        <p role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {error}
        </p>
      )}

      <div className="mb-6">
        <h3 className="m-0 mb-1 text-sm font-bold uppercase tracking-wide text-muted-foreground">Password</h3>
        <p className="m-0 mb-3 text-sm text-muted-foreground">Signed in as {user.displayName} ({user.username}).</p>
        <Button type="button" variant="secondary" onClick={() => setShowChangePassword(true)}>Change Password</Button>
      </div>

      <div>
        <h3 className="m-0 mb-3 text-sm font-bold uppercase tracking-wide text-muted-foreground">Active Sessions</h3>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading sessions…</p>
        ) : (
          <div className="grid gap-2">
            {sessions.map((session) => (
              <div key={session.id} className="flex items-center justify-between gap-3 rounded-md border border-border p-3">
                <div>
                  <p className="m-0 text-sm font-semibold text-foreground">
                    {session.browserName || "Unknown browser"} · {session.deviceName || "Unknown device"}
                    {session.isCurrent && <span className="ml-2 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-bold text-emerald-800">This device</span>}
                  </p>
                  <p className="m-0 text-xs text-muted-foreground">
                    Last active: {formatDateTime(session.lastActivityAt)}
                    {session.ipAddress && ` · ${session.ipAddress}`}
                  </p>
                </div>
                {!session.isCurrent && (
                  <Button type="button" variant="secondary" size="sm" disabled={busy} onClick={() => void signOutSession(session.id)}>
                    Sign Out
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <DialogFooter>
        <Button type="button" variant="secondary" disabled={busy} onClick={onClose}>Close</Button>
        <Button type="button" variant="destructive" disabled={busy || otherSessionCount === 0} onClick={() => void signOutOthers()}>
          Sign Out All Other Sessions
        </Button>
      </DialogFooter>

      {showChangePassword && <ChangePasswordDialog onClose={() => setShowChangePassword(false)} />}
    </Dialog>
  );
}
