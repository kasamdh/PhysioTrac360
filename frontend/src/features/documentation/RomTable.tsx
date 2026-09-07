import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeaderRow, TableHeader, TableRow } from "@/components/ui/table";

export interface RomRow {
  region: string;
  movement: string;
  left: string;
  right: string;
  normal: string;
  type: "AROM" | "PROM";
  pain: boolean;
  comments: string;
}

const emptyRow: RomRow = { region: "", movement: "", left: "", right: "", normal: "", type: "AROM", pain: false, comments: "" };

interface RomTableProps {
  rows: RomRow[];
  onChange: (rows: RomRow[]) => void;
  disabled?: boolean;
}

export function RomTable({ rows, onChange, disabled }: RomTableProps) {
  function updateRow(index: number, patch: Partial<RomRow>) {
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
            <TableHead>Region / Movement</TableHead>
            <TableHead className="w-24">Left</TableHead>
            <TableHead className="w-24">Right</TableHead>
            <TableHead className="w-24">Normal</TableHead>
            <TableHead className="w-24">Type</TableHead>
            <TableHead className="w-16">Pain</TableHead>
            <TableHead>Comments</TableHead>
            <TableHead className="w-10" />
          </TableHeaderRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={index}>
              <TableCell>
                <div className="grid grid-cols-2 gap-1.5">
                  <Input value={row.region} disabled={disabled} placeholder="Shoulder" onChange={(e) => updateRow(index, { region: e.target.value })} className="h-9 text-sm" />
                  <Input value={row.movement} disabled={disabled} placeholder="Flexion" onChange={(e) => updateRow(index, { movement: e.target.value })} className="h-9 text-sm" />
                </div>
              </TableCell>
              <TableCell><Input value={row.left} disabled={disabled} onChange={(e) => updateRow(index, { left: e.target.value })} className="h-9 text-sm" /></TableCell>
              <TableCell><Input value={row.right} disabled={disabled} onChange={(e) => updateRow(index, { right: e.target.value })} className="h-9 text-sm" /></TableCell>
              <TableCell><Input value={row.normal} disabled={disabled} onChange={(e) => updateRow(index, { normal: e.target.value })} className="h-9 text-sm" /></TableCell>
              <TableCell>
                <Select uiSize="sm" value={row.type} disabled={disabled} onChange={(e) => updateRow(index, { type: e.target.value as RomRow["type"] })} className="h-9 w-full">
                  <option value="AROM">AROM</option>
                  <option value="PROM">PROM</option>
                </Select>
              </TableCell>
              <TableCell>
                <input type="checkbox" checked={row.pain} disabled={disabled} onChange={(e) => updateRow(index, { pain: e.target.checked })} className="h-4 w-4" />
              </TableCell>
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
      {!rows.length && <p className="px-1 py-3 text-sm text-muted-foreground">No range-of-motion measurements recorded yet.</p>}
      {!disabled && (
        <Button type="button" variant="secondary" size="sm" className="mt-2 gap-1.5" onClick={() => onChange([...rows, { ...emptyRow }])}>
          <Plus className="h-3.5 w-3.5" /> Add measurement
        </Button>
      )}
    </div>
  );
}
