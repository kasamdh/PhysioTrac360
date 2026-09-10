import { useState } from "react";
import { Sparkles } from "lucide-react";

import { ApiError, api } from "@/api/client";
import type { CodingSuggestions } from "@/api/types";
import { Button } from "@/components/ui/button";

interface CodingSuggestionsPanelProps {
  noteId: string;
  disabled?: boolean;
}

export function CodingSuggestionsPanel({ noteId, disabled }: CodingSuggestionsPanelProps) {
  const [result, setResult] = useState<CodingSuggestions | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function generate() {
    setBusy(true);
    setError("");
    try {
      const response = await api.createCodingSuggestions(noteId);
      setResult(response.codingSuggestions);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to generate coding suggestions.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4 rounded-md border border-border p-3">
      <div className="flex items-center justify-between gap-3">
        <h4 className="m-0 text-xs font-bold uppercase tracking-wide text-muted-foreground">AI Coding Assistance</h4>
        <Button type="button" variant="secondary" size="sm" className="gap-1.5" disabled={disabled || busy} onClick={() => void generate()}>
          <Sparkles className="h-3.5 w-3.5" /> {busy ? "Generating..." : "Suggest CPT Coding"}
        </Button>
      </div>
      {error && <p className="mt-2 text-sm font-medium text-red-700">{error}</p>}
      {result && (
        <div className="mt-3">
          <p className="m-0 mb-2 rounded-md bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800">
            Suggested — Provider/Billing Review Required
          </p>
          {result.cptSuggestions.length > 0 ? (
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="py-1 pr-2 font-semibold">CPT Code</th>
                  <th className="py-1 pr-2 font-semibold">Category</th>
                  <th className="py-1 pr-2 font-semibold">Minutes</th>
                  <th className="py-1 font-semibold">Suggested Units</th>
                </tr>
              </thead>
              <tbody>
                {result.cptSuggestions.map((row) => (
                  <tr key={row.code} className="border-b border-border/50">
                    <td className="py-1 pr-2 font-medium text-foreground">{row.code}</td>
                    <td className="py-1 pr-2">{row.label}</td>
                    <td className="py-1 pr-2">{row.minutes}</td>
                    <td className="py-1">{row.suggestedUnits}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="m-0 text-sm text-muted-foreground">No codeable timed interventions are documented yet.</p>
          )}
          <p className="mt-2 text-sm font-semibold text-foreground">
            Total: {result.totalTimedMinutes} timed minute(s) → {result.totalSuggestedUnits} suggested unit(s)
          </p>
          {result.documentationGaps.length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-sm text-muted-foreground">
              {result.documentationGaps.map((gap) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-xs text-muted-foreground">{result.disclaimer}</p>
        </div>
      )}
    </div>
  );
}
