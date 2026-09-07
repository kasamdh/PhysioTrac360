import { useState } from "react";

import { ApiError } from "@/api/client";
import type { ComplianceFinding } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter } from "@/components/ui/dialog";

interface SignNoteDialogProps {
  blockers: ComplianceFinding[];
  onClose: () => void;
  onConfirm: () => Promise<void>;
}

export function SignNoteDialog({ blockers, onClose, onConfirm }: SignNoteDialogProps) {
  const [attested, setAttested] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await onConfirm();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to sign this note.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog titleId="sign-note-title" title="Sign Clinical Note" onClose={onClose} busy={busy} maxWidth="max-w-lg">
      {blockers.length > 0 ? (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <p className="m-0 mb-2 font-semibold">{blockers.length} required item{blockers.length === 1 ? "" : "s"} remaining:</p>
          <ul className="m-0 list-disc pl-5">
            {blockers.map((finding) => <li key={finding.code}>{finding.title}</li>)}
          </ul>
        </div>
      ) : (
        <>
          <p className="m-0 mb-4 text-[1.0625rem] leading-relaxed text-foreground">
            By signing this document you confirm that you have reviewed the documentation and that it accurately reflects the care provided.
          </p>
          <label className="flex items-start gap-2 text-sm font-medium text-foreground">
            <input type="checkbox" checked={attested} onChange={(e) => setAttested(e.target.checked)} className="mt-0.5 h-4 w-4" />
            I have reviewed this note and attest that it is accurate and complete.
          </label>
        </>
      )}

      {error && (
        <p role="alert" className="mt-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {error}
        </p>
      )}

      <DialogFooter>
        <Button type="button" variant="secondary" disabled={busy} onClick={onClose}>Cancel</Button>
        {blockers.length === 0 && (
          <Button type="button" disabled={busy || !attested} onClick={() => void confirm()}>
            {busy ? "Signing..." : "Sign Note"}
          </Button>
        )}
      </DialogFooter>
    </Dialog>
  );
}
