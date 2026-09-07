import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import { ApiError, api } from "@/api/client";
import type { NoteIntervention } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeaderRow, TableHeader, TableRow } from "@/components/ui/table";

type DraftRow = Omit<NoteIntervention, "id"> & { id?: string };

function toDraft(item: NoteIntervention): DraftRow {
  return { ...item };
}

interface InterventionTableProps {
  noteId: string;
  items: NoteIntervention[];
  onSaved: (items: NoteIntervention[]) => void;
  disabled?: boolean;
}

export function InterventionTable({ noteId, items, onSaved, disabled }: InterventionTableProps) {
  const [rows, setRows] = useState<DraftRow[]>(items.map(toDraft));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);

  const totalMinutes = rows.reduce((sum, row) => sum + (Number(row.minutes) || 0), 0);
  const timedMinutes = rows.filter((row) => row.isTimed).reduce((sum, row) => sum + (Number(row.minutes) || 0), 0);

  function updateRow(index: number, patch: Partial<DraftRow>) {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
    setDirty(true);
  }
  function removeRow(index: number) {
    setRows((current) => current.filter((_, i) => i !== index));
    setDirty(true);
  }
  function addRow() {
    setRows((current) => [
      ...current,
      { description: "", bodyRegion: "", minutes: 0, units: null, isTimed: true, patientResponse: "", order: current.length },
    ]);
    setDirty(true);
  }

  async function save() {
    setBusy(true);
    setError("");
    try {
      const result = await api.replaceInterventions(
        noteId,
        rows.map((row) => ({
          description: row.description,
          bodyRegion: row.bodyRegion,
          minutes: row.minutes,
          units: row.units,
          isTimed: row.isTimed,
          patientResponse: row.patientResponse,
        })),
      );
      setRows(result.interventionItems.map(toDraft));
      onSaved(result.interventionItems);
      setDirty(false);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to save interventions.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {error && (
        <p role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {error}
        </p>
      )}
      <Table>
        <TableHeader>
          <TableHeaderRow>
            <TableHead>Description</TableHead>
            <TableHead className="w-32">Body Region</TableHead>
            <TableHead className="w-20">Minutes</TableHead>
            <TableHead className="w-16">Units</TableHead>
            <TableHead className="w-16">Timed</TableHead>
            <TableHead>Response</TableHead>
            <TableHead className="w-10" />
          </TableHeaderRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={index}>
              <TableCell><Input value={row.description} disabled={disabled} placeholder="Therapeutic exercise" onChange={(e) => updateRow(index, { description: e.target.value })} className="h-9 text-sm" /></TableCell>
              <TableCell><Input value={row.bodyRegion} disabled={disabled} onChange={(e) => updateRow(index, { bodyRegion: e.target.value })} className="h-9 text-sm" /></TableCell>
              <TableCell><Input type="number" min={0} value={row.minutes} disabled={disabled} onChange={(e) => updateRow(index, { minutes: Number(e.target.value) || 0 })} className="h-9 text-sm" /></TableCell>
              <TableCell><Input type="number" min={0} value={row.units ?? ""} disabled={disabled} onChange={(e) => updateRow(index, { units: e.target.value ? Number(e.target.value) : null })} className="h-9 text-sm" /></TableCell>
              <TableCell><input type="checkbox" checked={row.isTimed} disabled={disabled} onChange={(e) => updateRow(index, { isTimed: e.target.checked })} className="h-4 w-4" /></TableCell>
              <TableCell><Input value={row.patientResponse} disabled={disabled} placeholder="Tolerated well" onChange={(e) => updateRow(index, { patientResponse: e.target.value })} className="h-9 text-sm" /></TableCell>
              <TableCell>
                {!disabled && (
                  <button type="button" onClick={() => removeRow(index)} className="border-0 bg-transparent p-1 text-destructive" aria-label="Remove row">
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {!rows.length && <p className="px-1 py-3 text-sm text-muted-foreground">No interventions recorded yet.</p>}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-foreground">
          <span className="font-semibold">Total Timed Minutes: {timedMinutes}</span>
          <span className="ml-4 font-semibold">Total Treatment Minutes: {totalMinutes}</span>
        </div>
        {!disabled && (
          <div className="flex gap-2">
            <Button type="button" variant="secondary" size="sm" className="gap-1.5" onClick={addRow}>
              <Plus className="h-3.5 w-3.5" /> Add intervention
            </Button>
            <Button type="button" size="sm" disabled={busy || !dirty} onClick={() => void save()}>
              {busy ? "Saving..." : "Save interventions"}
            </Button>
          </div>
        )}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Minutes alone do not determine billing units — confirm coding against your organization's billing policy.
      </p>
    </div>
  );
}
