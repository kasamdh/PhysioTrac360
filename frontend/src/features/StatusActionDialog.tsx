import { useState } from "react";

import { ApiError } from "../api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface StatusActionDialogProps {
  eyebrow: string;
  title: string;
  body: string;
  confirmLabel: string;
  destructive?: boolean;
  requireReason?: boolean;
  reasonLabel?: string;
  onClose: () => void;
  onConfirm: (reason: string) => Promise<void>;
}

export function StatusActionDialog({
  eyebrow,
  title,
  body,
  confirmLabel,
  destructive,
  requireReason,
  reasonLabel = "Reason",
  onClose,
  onConfirm,
}: StatusActionDialogProps) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await onConfirm(reason);
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        const fieldMessages = Object.values(requestError.fields).join(" ");
        setError(fieldMessages || requestError.message);
      } else {
        setError("Unable to complete this action.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog titleId="status-action-title" eyebrow={eyebrow} title={title} onClose={onClose} busy={busy} maxWidth="max-w-md">
      <p className="m-0 text-[1.0625rem] leading-relaxed text-foreground">{body}</p>
      {requireReason && (
        <div className="mt-4">
          <Label htmlFor="status-action-reason">{reasonLabel}</Label>
          <Textarea
            id="status-action-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Optional notes for the audit trail"
          />
        </div>
      )}
      {error && (
        <p role="alert" className="mt-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {error}
        </p>
      )}
      <DialogFooter>
        <Button type="button" variant="secondary" disabled={busy} onClick={onClose}>Cancel</Button>
        <Button
          type="button"
          variant={destructive ? "destructive" : "default"}
          disabled={busy}
          onClick={() => void confirm()}
        >
          {busy ? "Working..." : confirmLabel}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
