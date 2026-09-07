import { useEffect, useState } from "react";
import { Plus, Search } from "lucide-react";

import { ApiError, api } from "@/api/client";
import type { NoteSummary, WorkspaceUser } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusTabs } from "@/components/ui/status-tabs";
import { formatDate, formatDateTime } from "@/lib/format";
import { StartDocumentationDialog } from "./StartDocumentationDialog";

const QUICK_TABS = [
  { value: "", label: "All" },
  { value: "mine", label: "My Documentation" },
  { value: "unsigned", label: "Unsigned Notes" },
  { value: "today", label: "Today's Notes" },
  { value: "drafts", label: "Drafts" },
  { value: "completed", label: "Completed" },
];

const NOTE_TYPE_OPTIONS = [
  ["", "All note types"],
  ["evaluation", "Initial Evaluation"],
  ["daily", "Daily Treatment Note"],
  ["progress", "Progress Note"],
  ["re_evaluation", "Re-evaluation"],
  ["discharge", "Discharge Summary"],
  ["handoff", "Handoff Summary"],
] as const;

const STATUS_OPTIONS = [
  ["", "All statuses"],
  ["draft", "Draft"],
  ["review_required", "Review required"],
  ["signed", "Signed / locked"],
  ["amended", "Amended"],
] as const;

function statusTone(status: string): "success" | "warning" | "neutral" {
  if (status === "signed") return "success";
  if (status === "review_required") return "warning";
  return "neutral";
}

interface DocumentationPageProps {
  user: WorkspaceUser;
  onOpenNote: (patientId: string, noteId: string) => void;
}

export function DocumentationPage({ user, onOpenNote }: DocumentationPageProps) {
  const [notes, setNotes] = useState<NoteSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState("25");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [noteType, setNoteType] = useState("");
  const [quick, setQuick] = useState("");
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  async function load() {
    try {
      const result = await api.listDocumentation({ q: query, status, noteType, quick, pageSize, page: String(page) });
      setNotes(result.notes);
      setTotal(result.total);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load documentation.");
    }
  }
  useEffect(() => { setPage(1); }, [query, status, noteType, quick, pageSize]);
  useEffect(() => { void load(); }, [query, status, noteType, quick, pageSize, page]);

  const pageCount = Math.max(1, Math.ceil(total / Number(pageSize)));

  return (
    <div className="mx-auto max-w-[1400px] p-6 md:p-8">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="m-0 text-2xl font-bold tracking-tight text-foreground md:text-3xl">Documentation</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground md:text-base">
            Start, continue, and sign clinical notes across your caseload.
          </p>
        </div>
        {user.capabilities.canAccessClinical && (
          <Button size="sm" className="h-11 gap-1.5" onClick={() => setStarting(true)}>
            <Plus className="h-4 w-4" /> New Note
          </Button>
        )}
      </header>

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {error}
        </p>
      )}

      <div className="mb-4">
        <StatusTabs tabs={QUICK_TABS} value={quick} onChange={setQuick} />
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search patient or provider" className="h-11 w-64 pl-9 text-sm" />
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="h-11 rounded-md border border-input bg-white px-3 text-sm text-foreground">
          {STATUS_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <select value={noteType} onChange={(e) => setNoteType(e.target.value)} className="h-11 rounded-md border border-input bg-white px-3 text-sm text-foreground">
          {NOTE_TYPE_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-white">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <th className="px-4 py-3">Patient</th>
                <th className="px-4 py-3">Service Date</th>
                <th className="px-4 py-3">Provider</th>
                <th className="px-4 py-3">Note Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Last Updated</th>
                <th className="w-28 px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {notes.map((note) => (
                <tr key={note.id} className="hover:bg-muted/30">
                  <td className="px-4 py-3 font-semibold text-foreground">{note.patientName}</td>
                  <td className="px-4 py-3 text-foreground">{formatDate(note.serviceDate)}</td>
                  <td className="px-4 py-3 text-muted-foreground">{note.therapistName}</td>
                  <td className="px-4 py-3 text-foreground">{note.noteTypeLabel}</td>
                  <td className="px-4 py-3">
                    <Badge tone={statusTone(note.status)}>{note.statusLabel}</Badge>
                    {note.status === "review_required" && note.cosignRequired && (
                      <span className="ml-1.5 text-xs text-amber-700">Awaiting cosign</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{formatDateTime(note.updatedAt)}</td>
                  <td className="px-4 py-3">
                    <Button variant="secondary" size="sm" className="h-8" onClick={() => onOpenNote(note.patientId, note.id)}>
                      {note.status === "signed" ? "View" : "Continue"}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!notes.length && <p className="px-4 py-10 text-center text-sm text-muted-foreground">No documentation matches this search.</p>}
      </div>

      <div className="mt-4 flex items-center justify-center gap-3 text-sm">
        <Button variant="secondary" size="sm" className="h-9" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>
          Previous
        </Button>
        <span className="text-muted-foreground">Page {page} of {pageCount} · {total} note{total === 1 ? "" : "s"}</span>
        <Button variant="secondary" size="sm" className="h-9" disabled={page >= pageCount} onClick={() => setPage((current) => current + 1)}>
          Next
        </Button>
      </div>

      {starting && (
        <StartDocumentationDialog
          onClose={() => setStarting(false)}
          onCreated={(note) => { setStarting(false); onOpenNote(note.patientId, note.id); }}
        />
      )}
    </div>
  );
}
