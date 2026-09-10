import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ArAgingReport, BillingSummaryReport, ClaimDenial, OperationalReport, Payer } from "../api/types";

const STATUS_LABELS: Record<string, string> = {
  scheduled: "Scheduled",
  checked_in: "Checked in",
  completed: "Completed",
  cancelled: "Cancelled",
  no_show: "No show",
};

type Tab = "operations" | "ar-aging" | "denials" | "billing-summary";

export function ReportsPage() {
  const [tab, setTab] = useState<Tab>("operations");
  return (
    <div className="page-content">
      <header className="page-header split-header">
        <div>
          <p className="eyebrow">Settings</p>
          <h1>Reports</h1>
          <p>Real counts and balances from your organization's own data — nothing fabricated.</p>
        </div>
      </header>
      <nav className="client-detail-tabs" aria-label="Report sections">
        <button className={tab === "operations" ? "active" : ""} onClick={() => setTab("operations")}>Operational report</button>
        <button className={tab === "billing-summary" ? "active" : ""} onClick={() => setTab("billing-summary")}>Billing summary</button>
        <button className={tab === "ar-aging" ? "active" : ""} onClick={() => setTab("ar-aging")}>AR aging</button>
        <button className={tab === "denials" ? "active" : ""} onClick={() => setTab("denials")}>Denial work queue</button>
      </nav>
      {tab === "operations" && <OperationalReportTab />}
      {tab === "billing-summary" && <BillingSummaryTab />}
      {tab === "ar-aging" && <ArAgingTab />}
      {tab === "denials" && <DenialWorkQueueTab />}
    </div>
  );
}

function OperationalReportTab() {
  const [report, setReport] = useState<OperationalReport | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api
      .operationalReport()
      .then((result) => active && setReport(result))
      .catch((requestError) => active && setError(requestError instanceof ApiError ? requestError.message : "Unable to load the report."));
    return () => {
      active = false;
    };
  }, []);

  return (
    <>
      {error && <p className="form-error" role="alert">{error}</p>}
      {!report && !error && <p className="muted">Loading report...</p>}
      {report && (
        <>
          <section className="metric-grid">
            <div className="surface-card"><p className="eyebrow">New patients</p><h2>{report.newPatients}</h2></div>
            <div className="surface-card"><p className="eyebrow">Notes signed</p><h2>{report.notes.signed}</h2></div>
            <div className="surface-card"><p className="eyebrow">Notes unsigned</p><h2>{report.notes.unsigned}</h2></div>
            <div className="surface-card"><p className="eyebrow">Outcomes recorded</p><h2>{report.outcomesRecorded}</h2></div>
          </section>

          <section className="surface-card">
            <div className="card-heading"><h2>Appointments by status (30 days)</h2></div>
            {Object.keys(report.appointmentsByStatus).length ? (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Status</th><th>Count</th></tr></thead>
                  <tbody>
                    {Object.entries(report.appointmentsByStatus).map(([status, count]) => (
                      <tr key={status}><td>{STATUS_LABELS[status] || status}</td><td>{count}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="empty-copy">No appointments in this window.</p>}
          </section>

          <section className="surface-card">
            <div className="card-heading"><h2>Reassessments overdue</h2></div>
            <p>{report.reassessmentsOverdue} patient{report.reassessmentsOverdue === 1 ? "" : "s"} with an overdue reassessment on an unsigned note.</p>
          </section>

          <section className="surface-card">
            <div className="card-heading"><h2>Active caseload by provider</h2></div>
            {report.caseloadByProvider.length ? (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Provider</th><th>Active patients</th></tr></thead>
                  <tbody>
                    {report.caseloadByProvider.map((row) => (
                      <tr key={row.id}><td>{row.displayName}</td><td>{row.activePatientCount}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="empty-copy">No active therapists or assistants yet.</p>}
          </section>
        </>
      )}
    </>
  );
}

const CLAIM_STATUS_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "submitted", label: "Submitted" },
  { value: "accepted", label: "Accepted" },
  { value: "processing", label: "Processing" },
  { value: "denied", label: "Denied" },
  { value: "partial_payment", label: "Partial Payment" },
  { value: "appealed", label: "Appealed" },
  { value: "corrected", label: "Corrected" },
];

function ArAgingTab() {
  const [report, setReport] = useState<ArAgingReport | null>(null);
  const [payers, setPayers] = useState<Payer[]>([]);
  const [payerId, setPayerId] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const filters: Record<string, string> = {};
      if (payerId) filters.payerId = payerId;
      if (status) filters.status = status;
      const [reportResult, payerResult] = await Promise.all([api.arAgingReport(filters), api.payers()]);
      setReport(reportResult);
      setPayers(payerResult.payers);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load the AR aging report.");
    }
  }
  useEffect(() => { void load(); }, [payerId, status]);

  return (
    <>
      <section className="surface-card">
        <div className="card-heading"><h2>Filters</h2></div>
        <div className="field-grid">
          <label>Payer
            <select value={payerId} onChange={(event) => setPayerId(event.target.value)}>
              <option value="">All payers</option>
              {payers.map((payer) => <option key={payer.id} value={payer.id}>{payer.name}</option>)}
            </select>
          </label>
          <label>Claim status
            <select value={status} onChange={(event) => setStatus(event.target.value)}>
              {CLAIM_STATUS_FILTER_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
        </div>
      </section>
      {error && <p className="form-error" role="alert">{error}</p>}
      {report && (
        <>
          <section className="metric-grid">
            {Object.entries(report.buckets).map(([bucket, amount]) => (
              <div className="surface-card" key={bucket}><p className="eyebrow">{bucket} days</p><h2>${amount}</h2></div>
            ))}
          </section>
          <section className="surface-card">
            <div className="card-heading"><h2>Outstanding claims — ${report.totalOutstanding}</h2></div>
            {report.claims.length ? (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Patient</th><th>Payer</th><th>Status</th><th>Age (days)</th><th>Bucket</th><th>Balance</th></tr></thead>
                  <tbody>
                    {report.claims.map((row) => (
                      <tr key={row.claimId}>
                        <td>{row.patientName}</td><td>{row.payerName}</td><td>{row.statusLabel}</td>
                        <td>{row.ageDays}</td><td>{row.bucket}</td><td>${row.balance}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="empty-copy">No outstanding balances match these filters.</p>}
          </section>
        </>
      )}
    </>
  );
}

const RESOLUTION_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All resolutions" },
  { value: "open", label: "Open" },
  { value: "resolved_paid", label: "Resolved — Paid" },
  { value: "resolved_written_off", label: "Resolved — Written Off" },
  { value: "resolved_patient_billed", label: "Resolved — Billed to Patient" },
];
const APPEAL_STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "not_appealed", label: "Not Appealed" },
  { value: "preparing", label: "Preparing Appeal" },
  { value: "submitted", label: "Appeal Submitted" },
  { value: "won", label: "Appeal Won" },
  { value: "lost", label: "Appeal Lost" },
];
const DENIAL_RESOLUTION_OPTIONS: { value: string; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "resolved_paid", label: "Resolved — Paid" },
  { value: "resolved_written_off", label: "Resolved — Written Off" },
  { value: "resolved_patient_billed", label: "Resolved — Billed to Patient" },
];

function DenialWorkQueueTab() {
  const [denials, setDenials] = useState<ClaimDenial[]>([]);
  const [resolution, setResolution] = useState("open");
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const filters: Record<string, string> = {};
      if (resolution) filters.resolution = resolution;
      if (overdueOnly) filters.overdue = "1";
      const result = await api.denialWorkQueue(filters);
      setDenials(result.denials);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load the denial work queue.");
    }
  }
  useEffect(() => { void load(); }, [resolution, overdueOnly]);

  async function updateField(denial: ClaimDenial, patch: Record<string, unknown>) {
    setBusy(denial.id); setError("");
    try {
      await api.updateDenial(denial.patientId, denial.id, patch);
      await load();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to update this denial.");
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <section className="surface-card">
        <div className="card-heading"><h2>Filters</h2></div>
        <div className="field-grid">
          <label>Resolution
            <select value={resolution} onChange={(event) => setResolution(event.target.value)}>
              {RESOLUTION_FILTER_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <label className="check-label"><input type="checkbox" checked={overdueOnly} onChange={(event) => setOverdueOnly(event.target.checked)} /> Overdue only</label>
        </div>
      </section>
      {error && <p className="form-error" role="alert">{error}</p>}
      <section className="surface-card">
        <div className="card-heading"><h2>Denial work queue ({denials.length})</h2></div>
        {denials.length ? (
          <ul className="record-list">
            {denials.map((denial) => (
              <li key={denial.id} style={{ flexDirection: "column", alignItems: "stretch" }}>
                <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
                  <span>
                    <strong>{denial.payerName} · {denial.denialReason}</strong>
                    <small>
                      {denial.denialCode && `Code ${denial.denialCode} · `}Denied {denial.deniedOn}
                      {denial.dueDate && ` · Due ${denial.dueDate}`}{denial.ownerName && ` · Owner: ${denial.ownerName}`}
                    </small>
                  </span>
                  <span className={`status-pill ${denial.isOverdue ? "critical" : denial.resolution}`}>
                    {denial.isOverdue ? "Overdue" : denial.resolutionLabel}
                  </span>
                </div>
                <div className="button-row" style={{ marginTop: ".4rem" }}>
                  <select
                    value={denial.appealStatus}
                    disabled={busy === denial.id}
                    onChange={(event) => void updateField(denial, { appealStatus: event.target.value })}
                  >
                    {APPEAL_STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                  <select
                    value={denial.resolution}
                    disabled={busy === denial.id}
                    onChange={(event) => void updateField(denial, { resolution: event.target.value })}
                  >
                    {DENIAL_RESOLUTION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                </div>
              </li>
            ))}
          </ul>
        ) : <p className="empty-copy">No denials match these filters.</p>}
      </section>
    </>
  );
}

function BillingSummaryTab() {
  const [report, setReport] = useState<BillingSummaryReport | null>(null);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      setReport(await api.billingSummaryReport());
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load the billing summary.");
    }
  }
  useEffect(() => { void load(); }, []);

  if (error) return <p className="form-error" role="alert">{error}</p>;
  if (!report) return <p className="muted">Loading report...</p>;

  return (
    <>
      <p className="muted">Window: {report.windowStart} to {report.windowEnd} (last 90 days by default)</p>
      <section className="metric-grid">
        <div className="surface-card"><p className="eyebrow">Charges billed</p><h2>${report.charges.totalAmount}</h2><small>{report.charges.count} charge{report.charges.count === 1 ? "" : "s"}</small></div>
        <div className="surface-card"><p className="eyebrow">Collections</p><h2>${report.collections.totalAmount}</h2></div>
        <div className="surface-card"><p className="eyebrow">Clean claim rate</p><h2>{report.cleanClaimRate ? `${report.cleanClaimRate}%` : "—"}</h2><small>{report.claimsSubmittedInWindow} submitted in window</small></div>
      </section>

      <section className="surface-card">
        <div className="card-heading"><h2>Payments breakdown</h2></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Insurance payments</th><th>Patient payments</th><th>Adjustments</th><th>Write-offs</th><th>Refunds</th></tr></thead>
            <tbody>
              <tr>
                <td>${report.payments.insurancePayments}</td><td>${report.payments.patientPayments}</td>
                <td>${report.payments.adjustments}</td><td>${report.payments.writeOffs}</td><td>${report.payments.refunds}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="surface-card">
        <div className="card-heading"><h2>Claims by status</h2></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Status</th><th>Count</th></tr></thead>
            <tbody>
              {Object.entries(report.claimsByStatus).filter(([, count]) => count > 0).map(([status, count]) => (
                <tr key={status}><td>{status.replace(/_/g, " ")}</td><td>{count}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="content-grid">
        <section className="surface-card">
          <div className="card-heading"><h2>Revenue by provider</h2></div>
          {report.revenueByProvider.length ? (
            <ul className="compact-list">{report.revenueByProvider.map((row) => <li key={row.id}><span>{row.name}</span><span>${row.amount}</span></li>)}</ul>
          ) : <p className="empty-copy">No billed charges in this window.</p>}
        </section>
        <section className="surface-card">
          <div className="card-heading"><h2>Revenue by location</h2></div>
          {report.revenueByLocation.length ? (
            <ul className="compact-list">{report.revenueByLocation.map((row) => <li key={row.id}><span>{row.name}</span><span>${row.amount}</span></li>)}</ul>
          ) : <p className="empty-copy">No billed charges with a location in this window.</p>}
        </section>
        <section className="surface-card">
          <div className="card-heading"><h2>Revenue by payer</h2></div>
          {report.revenueByPayer.length ? (
            <ul className="compact-list">{report.revenueByPayer.map((row) => <li key={row.id}><span>{row.name}</span><span>${row.amount}</span></li>)}</ul>
          ) : <p className="empty-copy">No claimed charges in this window.</p>}
        </section>
      </div>

      <section className="surface-card">
        <div className="card-heading"><h2>Patient balances</h2></div>
        {report.patientBalances.length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Patient</th><th>Balance</th></tr></thead>
              <tbody>
                {report.patientBalances.map((row) => <tr key={row.patientId}><td>{row.patientName}</td><td>${row.balance}</td></tr>)}
              </tbody>
            </table>
          </div>
        ) : <p className="empty-copy">No outstanding patient balances.</p>}
      </section>
    </>
  );
}
