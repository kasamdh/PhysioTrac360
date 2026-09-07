import { useState } from "react";

import { ApiError } from "../api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter } from "@/components/ui/dialog";

interface ConfirmActionDialogProps {
  eyebrow: string;
  title: string;
  body: string;
  confirmLabel: string;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}

export function ConfirmActionDialog({ eyebrow, title, body, confirmLabel, onClose, onConfirm }: ConfirmActionDialogProps) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await onConfirm();
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
    <Dialog titleId="confirm-action-title" eyebrow={eyebrow} title={title} onClose={onClose} busy={busy} maxWidth="max-w-md">
      <p className="m-0 text-[1.0625rem] leading-relaxed text-foreground">{body}</p>
      {error && (
        <p role="alert" className="mt-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {error}
        </p>
      )}
      <DialogFooter>
        <Button type="button" variant="secondary" disabled={busy} onClick={onClose}>Cancel</Button>
        <Button type="button" disabled={busy} onClick={() => void confirm()}>{busy ? "Working..." : confirmLabel}</Button>
      </DialogFooter>
    </Dialog>
  );
}
