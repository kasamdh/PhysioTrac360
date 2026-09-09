import { ChangeEvent, useEffect, useState } from "react";

import { ApiError } from "../api/client";
import type { UserLicenseInfo } from "../api/types";
import { formatDate, formatDateTime } from "../lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LicenseBadge } from "@/components/ui/license-banner";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { US_STATES } from "@/lib/usStates";

interface LicenseListSectionProps {
  licenses: UserLicenseInfo[];
  onCreate: (body: Record<string, unknown>) => Promise<unknown>;
  onUpdate: (licenseId: string, body: Record<string, unknown>) => Promise<unknown>;
  onDelete: (licenseId: string) => Promise<unknown>;
  onUploadDocument: (licenseId: string, file: File) => Promise<unknown>;
  onVerify: (licenseId: string, notes: string) => Promise<unknown>;
  documentUrl: (licenseId: string) => string;
}

const emptyDraft = { licenseNumber: "", issuingState: "", licenseType: "", issueDate: "", expiresAt: "" };

function requestMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    const fieldMessages = Object.values(error.fields).join(" ");
    return fieldMessages || error.message;
  }
  return fallback;
}

function LicenseRow({ license, onUpdate, onDelete, onUploadDocument, onVerify, documentUrl }: {
  license: UserLicenseInfo;
  onUpdate: (licenseId: string, body: Record<string, unknown>) => Promise<unknown>;
  onDelete: (licenseId: string) => Promise<unknown>;
  onUploadDocument: (licenseId: string, file: File) => Promise<unknown>;
  onVerify: (licenseId: string, notes: string) => Promise<unknown>;
  documentUrl: (licenseId: string) => string;
}) {
  const [draft, setDraft] = useState({
    licenseNumber: license.licenseNumber,
    issuingState: license.issuingState,
    licenseType: license.licenseType,
    issueDate: license.issueDate ?? "",
    expiresAt: license.expiresAt,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const [notes, setNotes] = useState("");

  useEffect(() => {
    setDraft({
      licenseNumber: license.licenseNumber,
      issuingState: license.issuingState,
      licenseType: license.licenseType,
      issueDate: license.issueDate ?? "",
      expiresAt: license.expiresAt,
    });
  }, [license]);

  async function save() {
    setBusy(true);
    setError("");
    try {
      await onUpdate(license.id, draft);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to save this license."));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError("");
    try {
      await onDelete(license.id);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to remove this license."));
      setBusy(false);
    }
  }

  async function uploadDocument(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      await onUploadDocument(license.id, file);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to upload this document."));
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }

  async function verify() {
    setBusy(true);
    setError("");
    try {
      await onVerify(license.id, notes);
      setNotes("");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to verify this license."));
    } finally {
      setBusy(false);
    }
  }

  const canVerify = license.hasDocument && license.verificationStatus === "pending_verification";

  return (
    <div className="mb-4 rounded-lg border border-border p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <LicenseBadge status={license.colorBucket} />
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {license.verificationStatus === "verified" ? "Verified" : "Pending verification"}
        </span>
      </div>

      {error && (
        <p role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
          {error}
        </p>
      )}

      <div className="mb-3 grid grid-cols-2 gap-3 max-[560px]:grid-cols-1">
        <label className="text-sm">
          <span className="mb-1 block font-semibold text-foreground">License Number</span>
          <Input value={draft.licenseNumber} onChange={(event) => setDraft({ ...draft, licenseNumber: event.target.value })} />
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-semibold text-foreground">Issuing State</span>
          <Select value={draft.issuingState} onChange={(event) => setDraft({ ...draft, issuingState: event.target.value })}>
            <option value="">Select a state</option>
            {US_STATES.map((state) => (
              <option key={state.code} value={state.code}>{state.name}</option>
            ))}
          </Select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-semibold text-foreground">License Type</span>
          <Input value={draft.licenseType} onChange={(event) => setDraft({ ...draft, licenseType: event.target.value })} placeholder="e.g. DPT, PT, PTA" />
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-semibold text-foreground">Issue Date</span>
          <Input type="date" value={draft.issueDate} onChange={(event) => setDraft({ ...draft, issueDate: event.target.value })} />
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-semibold text-foreground">Expiration Date</span>
          <Input type="date" required value={draft.expiresAt} onChange={(event) => setDraft({ ...draft, expiresAt: event.target.value })} />
        </label>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" disabled={busy} onClick={() => void save()}>Save changes</Button>
        {license.hasDocument && (
          <a href={documentUrl(license.id)} target="_blank" rel="noreferrer" className="text-sm font-semibold text-primary-deep hover:underline">
            Download document
          </a>
        )}
        <label className="text-sm font-semibold text-primary-deep hover:underline cursor-pointer">
          {license.hasDocument ? "Replace document" : "Upload document"}
          <input type="file" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx" className="hidden" disabled={busy} onChange={(event) => void uploadDocument(event)} />
        </label>
      </div>

      {license.verificationStatus === "verified" && license.verifiedByName && (
        <p className="mb-3 text-xs text-muted-foreground">
          Verified by {license.verifiedByName}{license.verifiedAt ? ` on ${formatDateTime(license.verifiedAt)}` : ""}
          {license.verificationNotes ? ` — ${license.verificationNotes}` : ""}
        </p>
      )}

      {canVerify && (
        <div className="mb-3 rounded-md bg-muted/40 p-3">
          <Label htmlFor={`verify-notes-${license.id}`}>Verification notes (optional)</Label>
          <Textarea id={`verify-notes-${license.id}`} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Checked against the state board site" />
          <Button type="button" size="sm" className="mt-2" disabled={busy} onClick={() => void verify()}>Verify license</Button>
        </div>
      )}

      {confirmingRemove ? (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-foreground">Remove this license?</span>
          <Button type="button" variant="destructive" size="sm" disabled={busy} onClick={() => void remove()}>Yes, remove</Button>
          <Button type="button" variant="secondary" size="sm" disabled={busy} onClick={() => setConfirmingRemove(false)}>Cancel</Button>
        </div>
      ) : (
        <button type="button" className="border-0 bg-transparent p-0 text-sm font-semibold text-destructive hover:underline" onClick={() => setConfirmingRemove(true)}>
          Remove license
        </button>
      )}
    </div>
  );
}

export function LicenseListSection({ licenses, onCreate, onUpdate, onDelete, onUploadDocument, onVerify, documentUrl }: LicenseListSectionProps) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState(emptyDraft);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function addLicense() {
    setBusy(true);
    setError("");
    try {
      await onCreate(draft);
      setDraft(emptyDraft);
      setAdding(false);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to add this license."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-4">
      <h3 className="m-0 mb-3 text-sm font-bold uppercase tracking-wide text-muted-foreground">Professional Licenses</h3>
      {licenses.map((license) => (
        <LicenseRow
          key={license.id}
          license={license}
          onUpdate={onUpdate}
          onDelete={onDelete}
          onUploadDocument={onUploadDocument}
          onVerify={onVerify}
          documentUrl={documentUrl}
        />
      ))}

      {adding ? (
        <div className="rounded-lg border border-dashed border-border p-4">
          {error && (
            <p role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
              {error}
            </p>
          )}
          <div className="mb-3 grid grid-cols-2 gap-3 max-[560px]:grid-cols-1">
            <label className="text-sm">
              <span className="mb-1 block font-semibold text-foreground">License Number</span>
              <Input required value={draft.licenseNumber} onChange={(event) => setDraft({ ...draft, licenseNumber: event.target.value })} />
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-semibold text-foreground">Issuing State</span>
              <Select required value={draft.issuingState} onChange={(event) => setDraft({ ...draft, issuingState: event.target.value })}>
                <option value="">Select a state</option>
                {US_STATES.map((state) => (
                  <option key={state.code} value={state.code}>{state.name}</option>
                ))}
              </Select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-semibold text-foreground">License Type</span>
              <Input value={draft.licenseType} onChange={(event) => setDraft({ ...draft, licenseType: event.target.value })} placeholder="e.g. DPT, PT, PTA" />
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-semibold text-foreground">Issue Date</span>
              <Input type="date" value={draft.issueDate} onChange={(event) => setDraft({ ...draft, issueDate: event.target.value })} />
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-semibold text-foreground">Expiration Date</span>
              <Input type="date" required value={draft.expiresAt} onChange={(event) => setDraft({ ...draft, expiresAt: event.target.value })} />
            </label>
          </div>
          <div className="flex gap-2">
            <Button type="button" size="sm" disabled={busy} onClick={() => void addLicense()}>{busy ? "Adding..." : "Add license"}</Button>
            <Button type="button" variant="secondary" size="sm" disabled={busy} onClick={() => { setAdding(false); setDraft(emptyDraft); setError(""); }}>Cancel</Button>
          </div>
        </div>
      ) : (
        <Button type="button" variant="secondary" size="sm" onClick={() => setAdding(true)}>+ Add another license</Button>
      )}
    </div>
  );
}
