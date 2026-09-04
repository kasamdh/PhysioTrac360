import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { OperationalReport } from "../api/types";

const STATUS_LABELS: Record<string, string> = {
  scheduled: "Scheduled",
  checked_in: "Checked in",
  completed: "Completed",
  cancelled: "Cancelled",
  no_show: "No show",
};

export function ReportsPage() {
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
    <div className="page-content">
      <header className="page-header split-header">
        <div>
          <p className="eyebrow">Settings</p>
          <h1>Operational report</h1>
          <p>Real counts from your organization's own data over the last 30 days — nothing fabricated.</p>
        </div>
      </header>
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
    </div>
  );
}
