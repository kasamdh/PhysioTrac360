import { useState } from "react";

import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter, FormRow } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

interface AddendumDialogProps {
  onClose: () => void;
  onConfirm: (reason: string, body: string) => Promise<void>;
}

export function AddendumDialog({ onClose, onConfirm }: AddendumDialogProps) {
  const [reason, setReason] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await onConfirm(reason, body);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to save this addendum.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog titleId="addendum-title" eyebrow="Addendum" title="Add a correction to this signed note" onClose={onClose} busy={busy} maxWidth="max-w-lg">
      <p className="m-0 mb-4 text-sm text-muted-foreground">
        The signed note is never changed. This addendum is appended and clearly attributed to you and today's date.
      </p>
      <FormRow label="Reason" htmlFor="addendum-reason">
        <Input id="addendum-reason" required value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Clarify measurement" />
      </FormRow>
      <FormRow label="Addendum text" htmlFor="addendum-body">
        <Textarea id="addendum-body" required rows={5} value={body} onChange={(e) => setBody(e.target.value)} />
      </FormRow>

      {error && (
        <p role="alert" className="mt-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {error}
        </p>
      )}

      <DialogFooter>
        <Button type="button" variant="secondary" disabled={busy} onClick={onClose}>Cancel</Button>
        <Button type="button" disabled={busy || !reason.trim() || !body.trim()} onClick={() => void confirm()}>
          {busy ? "Saving..." : "Save addendum"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
