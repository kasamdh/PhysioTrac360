import { FormEvent, useState } from "react";

import { ApiError, api } from "@/api/client";
import type { Goal } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { formatDate } from "@/lib/format";

const emptyForm = {
  functionalLimitation: "", functionalTask: "", baselineValue: "", targetValue: "",
  unit: "", measurementMethod: "", targetDate: "", suggestedWording: "",
};

function statusTone(status: string): "success" | "warning" | "neutral" {
  if (status === "met") return "success";
  if (status === "active") return "warning";
  return "neutral";
}

function isShortTerm(targetDate: string): boolean {
  const weeksOut = (new Date(targetDate).getTime() - Date.now()) / (1000 * 60 * 60 * 24 * 7);
  return weeksOut <= 6;
}

function GoalRow({ goal, onApprove, canApprove }: { goal: Goal; onApprove: (id: string) => void; canApprove: boolean }) {
  return (
    <div className="rounded-md border border-border p-3">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <Badge tone={statusTone(goal.status)}>{goal.statusLabel}</Badge>
        <span className="text-xs text-muted-foreground">Target: {formatDate(goal.targetDate)}</span>
      </div>
      <p className="m-0 text-sm text-foreground">{goal.suggestedWording || goal.functionalTask}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Baseline {goal.baselineValue} → Target {goal.targetValue} {goal.unit}
        {goal.currentValue !== null && ` · Current ${goal.currentValue} ${goal.unit}`}
        {goal.progressPercent !== null && ` · ${Math.round(goal.progressPercent)}% progress`}
      </p>
      {goal.status === "draft" && canApprove && (
        <Button type="button" size="sm" variant="secondary" className="mt-2" onClick={() => onApprove(goal.id)}>
          Approve goal
        </Button>
      )}
    </div>
  );
}

interface GoalsSectionProps {
  patientId: string;
  goals: Goal[];
  canApprove: boolean;
  onRefresh: () => Promise<void>;
  disabled?: boolean;
}

export function GoalsSection({ patientId, goals, canApprove, onRefresh, disabled }: GoalsSectionProps) {
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const shortTerm = goals.filter((goal) => isShortTerm(goal.targetDate));
  const longTerm = goals.filter((goal) => !isShortTerm(goal.targetDate));

  async function addGoal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.createGoal(patientId, form);
      setForm(emptyForm);
      setAdding(false);
      await onRefresh();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to save this goal.");
    } finally {
      setBusy(false);
    }
  }

  async function approve(goalId: string) {
    try {
      await api.approveGoal(goalId);
      await onRefresh();
    } catch {
      setError("Unable to approve this goal.");
    }
  }

  return (
    <div>
      {error && (
        <p role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {error}
        </p>
      )}

      <h4 className="m-0 mb-2 text-xs font-bold uppercase tracking-wide text-muted-foreground">Short-Term Goals</h4>
      <div className="mb-4 grid gap-2">
        {shortTerm.map((goal) => <GoalRow key={goal.id} goal={goal} onApprove={approve} canApprove={canApprove} />)}
        {!shortTerm.length && <p className="text-sm text-muted-foreground">No short-term goals yet.</p>}
      </div>

      <h4 className="m-0 mb-2 text-xs font-bold uppercase tracking-wide text-muted-foreground">Long-Term Goals</h4>
      <div className="mb-4 grid gap-2">
        {longTerm.map((goal) => <GoalRow key={goal.id} goal={goal} onApprove={approve} canApprove={canApprove} />)}
        {!longTerm.length && <p className="text-sm text-muted-foreground">No long-term goals yet.</p>}
      </div>

      {!disabled && (
        adding ? (
          <form onSubmit={addGoal} className="rounded-lg border border-dashed border-border p-4">
            <div className="mb-3 grid grid-cols-2 gap-3 max-[560px]:grid-cols-1">
              <label className="text-sm">
                <span className="mb-1 block font-semibold text-foreground">Functional Limitation</span>
                <Input required value={form.functionalLimitation} onChange={(e) => setForm({ ...form, functionalLimitation: e.target.value })} />
              </label>
              <label className="text-sm">
                <span className="mb-1 block font-semibold text-foreground">Functional Task</span>
                <Input required value={form.functionalTask} onChange={(e) => setForm({ ...form, functionalTask: e.target.value })} />
              </label>
              <label className="text-sm">
                <span className="mb-1 block font-semibold text-foreground">Baseline</span>
                <Input required type="number" step="any" value={form.baselineValue} onChange={(e) => setForm({ ...form, baselineValue: e.target.value })} />
              </label>
              <label className="text-sm">
                <span className="mb-1 block font-semibold text-foreground">Target</span>
                <Input required type="number" step="any" value={form.targetValue} onChange={(e) => setForm({ ...form, targetValue: e.target.value })} />
              </label>
              <label className="text-sm">
                <span className="mb-1 block font-semibold text-foreground">Unit</span>
                <Input required value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} />
              </label>
              <label className="text-sm">
                <span className="mb-1 block font-semibold text-foreground">Target Date</span>
                <Input required type="date" value={form.targetDate} onChange={(e) => setForm({ ...form, targetDate: e.target.value })} />
              </label>
              <label className="text-sm">
                <span className="mb-1 block font-semibold text-foreground">Measurement Method</span>
                <Input required value={form.measurementMethod} onChange={(e) => setForm({ ...form, measurementMethod: e.target.value })} />
              </label>
            </div>
            <label className="mb-3 block text-sm">
              <span className="mb-1 block font-semibold text-foreground">Goal Wording</span>
              <Textarea required value={form.suggestedWording} onChange={(e) => setForm({ ...form, suggestedWording: e.target.value })} placeholder="Patient will ambulate 1 mile independently without increased knee pain." />
            </label>
            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={busy}>{busy ? "Saving..." : "Save goal"}</Button>
              <Button type="button" variant="secondary" size="sm" disabled={busy} onClick={() => { setAdding(false); setForm(emptyForm); }}>Cancel</Button>
            </div>
          </form>
        ) : (
          <Button type="button" variant="secondary" size="sm" onClick={() => setAdding(true)}>+ Add goal</Button>
        )
      )}
    </div>
  );
}
