import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeaderRow, TableHeader, TableRow } from "@/components/ui/table";

export interface StrengthRow {
  movement: string;
  left: string;
  right: string;
  comments: string;
}

const emptyRow: StrengthRow = { movement: "", left: "", right: "", comments: "" };

interface StrengthTableProps {
  rows: StrengthRow[];
  onChange: (rows: StrengthRow[]) => void;
  disabled?: boolean;
}

export function StrengthTable({ rows, onChange, disabled }: StrengthTableProps) {
  function updateRow(index: number, patch: Partial<StrengthRow>) {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }
  function removeRow(index: number) {
    onChange(rows.filter((_, i) => i !== index));
  }

  return (
    <div>
      <Table>
        <TableHeader>
          <TableHeaderRow>
            <TableHead>Movement</TableHead>
            <TableHead className="w-24">Left</TableHead>
            <TableHead className="w-24">Right</TableHead>
            <TableHead>Comments</TableHead>
            <TableHead className="w-10" />
          </TableHeaderRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={index}>
              <TableCell><Input value={row.movement} disabled={disabled} placeholder="Shoulder Flexion" onChange={(e) => updateRow(index, { movement: e.target.value })} className="h-9 text-sm" /></TableCell>
              <TableCell><Input value={row.left} disabled={disabled} placeholder="4-/5" onChange={(e) => updateRow(index, { left: e.target.value })} className="h-9 text-sm" /></TableCell>
              <TableCell><Input value={row.right} disabled={disabled} placeholder="5/5" onChange={(e) => updateRow(index, { right: e.target.value })} className="h-9 text-sm" /></TableCell>
              <TableCell><Input value={row.comments} disabled={disabled} onChange={(e) => updateRow(index, { comments: e.target.value })} className="h-9 text-sm" /></TableCell>
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
      {!rows.length && <p className="px-1 py-3 text-sm text-muted-foreground">No manual muscle testing recorded yet.</p>}
      {!disabled && (
        <Button type="button" variant="secondary" size="sm" className="mt-2 gap-1.5" onClick={() => onChange([...rows, { ...emptyRow }])}>
          <Plus className="h-3.5 w-3.5" /> Add movement
        </Button>
      )}
    </div>
  );
}
