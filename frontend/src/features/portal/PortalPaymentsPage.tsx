import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { PatientStatementData, PatientSuperbillData, PortalPayments } from "../../api/types";
import { formatDate } from "../../lib/format";

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function StatementDetail({ statementId, onClose }: { statementId: string; onClose: () => void }) {
  const [data, setData] = useState<PatientStatementData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api
      .portalStatementDetail(statementId)
      .then((result) => active && setData(result.statement))
      .catch((requestError) => active && setError(requestMessage(requestError, "Unable to load this statement.")));
    return () => {
      active = false;
    };
  }, [statementId]);

  if (error) return <p className="form-error" role="alert">{error}</p>;
  if (!data) return <p className="portal-empty">Loading...</p>;

  return (
    <div className="portal-card">
      <p className="eyebrow">{data.practice.name}</p>
      <h2>Statement — {formatDate(data.statementDate)}</h2>
      <p className="portal-empty">Due {formatDate(data.dueDate)}</p>

      {data.insuranceClaims.length > 0 && (
        <>
          <p className="portal-section-heading">Insurance claims</p>
          <ul className="record-list">
            {data.insuranceClaims.map((claim) => (
              <li key={claim.claimId}>
                <span><strong>{claim.payerName}</strong><small>{claim.statusLabel} · Billed ${claim.chargeTotal}</small></span>
                <span>Balance ${claim.balance}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {data.cashCharges.length > 0 && (
        <>
          <p className="portal-section-heading">Cash charges</p>
          <ul className="record-list">
            {data.cashCharges.map((charge) => (
              <li key={charge.superbillId}>
                <span><strong>{formatDate(charge.serviceDate)}</strong><small>Amount ${charge.amount}</small></span>
                <span>Balance ${charge.balance}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      <p style={{ fontWeight: 700, fontSize: "1.25rem" }}>Total balance: ${data.totalBalance}</p>
      <p className="portal-empty">{data.paymentInstructions}</p>
      <button className="secondary-button" onClick={onClose}>Back</button>
    </div>
  );
}

function SuperbillDetail({ superbillId, onClose }: { superbillId: string; onClose: () => void }) {
  const [data, setData] = useState<PatientSuperbillData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api
      .portalSuperbillDetail(superbillId)
      .then((result) => active && setData(result.superbill))
      .catch((requestError) => active && setError(requestMessage(requestError, "Unable to load this superbill.")));
    return () => {
      active = false;
    };
  }, [superbillId]);

  if (error) return <p className="form-error" role="alert">{error}</p>;
  if (!data) return <p className="portal-empty">Loading...</p>;

  return (
    <div className="portal-card">
      <p className="eyebrow">{data.practice.name}</p>
      <h2>Superbill — {formatDate(data.serviceDate)}</h2>
      <p className="portal-empty">
        {data.patient.fullName} · DOB {formatDate(data.patient.dateOfBirth)} · Provider {data.provider.name}
      </p>
      {data.diagnosisCodes.length > 0 && <p className="portal-empty">Diagnosis: {data.diagnosisCodes.join(", ")}</p>}
      <ul className="record-list">
        {data.lines.map((line, index) => (
          <li key={index}>
            <span><strong>{line.cptCode}</strong><small>{formatDate(line.serviceDate)}{line.units ? ` · ${line.units} unit(s)` : ""}</small></span>
            <span>{line.chargeAmount ? `$${line.chargeAmount}` : "—"}</span>
          </li>
        ))}
      </ul>
      <p style={{ fontWeight: 700, fontSize: "1.25rem" }}>Total: ${data.totalAmount}</p>
      <div className="button-row">
        <button className="secondary-button" onClick={() => window.print()}>Print</button>
        <button className="secondary-button" onClick={onClose}>Back</button>
      </div>
    </div>
  );
}

function PaymentsOverview({ onOpenStatement, onOpenSuperbill }: { onOpenStatement: (id: string) => void; onOpenSuperbill: (id: string) => void }) {
  const [payments, setPayments] = useState<PortalPayments | null>(null);
  const [superbills, setSuperbills] = useState<{ id: string; serviceDate: string; amount: string; statusLabel: string }[]>([]);
  const [amount, setAmount] = useState("");
  const [payError, setPayError] = useState("");
  const [payResult, setPayResult] = useState("");
  const [paying, setPaying] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    try {
      const [paymentsResult, superbillsResult] = await Promise.all([api.portalPayments(), api.portalSuperbills()]);
      setPayments(paymentsResult);
      setSuperbills(superbillsResult.superbills);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load your billing information."));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function pay(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPayError("");
    setPayResult("");
    setPaying(true);
    try {
      const result = await api.portalPaymentCharge(amount);
      setPayResult(result.message);
      if (result.succeeded) setAmount("");
      await load();
    } catch (requestError) {
      setPayError(requestMessage(requestError, "Unable to process this payment."));
    } finally {
      setPaying(false);
    }
  }

  if (error) return <p className="form-error" role="alert">{error}</p>;
  if (!payments) return <p className="portal-empty">Loading...</p>;

  return (
    <>
      <h1>Payments &amp; Billing</h1>

      <div className="portal-card">
        <p className="eyebrow">Outstanding balance</p>
        <p style={{ fontSize: "2rem", fontWeight: 700, margin: "0 0 .25rem" }}>${payments.totalBalance}</p>
        <p className="portal-empty">Insurance: ${payments.insuranceBalance} · Cash-pay: ${payments.cashBalance}</p>
        {Number(payments.totalBalance) > 0 && (
          <form onSubmit={pay} style={{ display: "flex", gap: ".5rem", alignItems: "flex-end", marginTop: ".75rem", flexWrap: "wrap" }}>
            <label style={{ flex: "1 1 160px" }}>
              <span>Amount to pay</span>
              <input type="number" step="0.01" min="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required />
            </label>
            <button className="primary-button" type="submit" disabled={paying}>{paying ? "Processing..." : "Pay now"}</button>
          </form>
        )}
        {payError && <p className="form-error" role="alert">{payError}</p>}
        {payResult && <p className="form-notice" role="status">{payResult}</p>}
      </div>

      <div>
        <p className="portal-section-heading">Statements</p>
        {payments.statements.length ? (
          <div style={{ display: "grid", gap: ".5rem", marginTop: ".5rem" }}>
            {payments.statements.map((statement) => (
              <div key={statement.id} className="portal-appointment-card">
                <header>
                  <div>
                    <strong>Statement — {formatDate(statement.statementDate)}</strong>
                    <div className="portal-empty">Due {formatDate(statement.dueDate)} · Balance ${statement.balanceAtGeneration}</div>
                  </div>
                </header>
                <div className="button-row">
                  <button className="secondary-button" onClick={() => onOpenStatement(statement.id)}>View</button>
                </div>
              </div>
            ))}
          </div>
        ) : <p className="portal-empty">No statements yet.</p>}
      </div>

      <div>
        <p className="portal-section-heading">Superbills</p>
        {superbills.length ? (
          <div style={{ display: "grid", gap: ".5rem", marginTop: ".5rem" }}>
            {superbills.map((superbill) => (
              <div key={superbill.id} className="portal-appointment-card">
                <header>
                  <div>
                    <strong>{formatDate(superbill.serviceDate)}</strong>
                    <div className="portal-empty">${superbill.amount} · {superbill.statusLabel}</div>
                  </div>
                </header>
                <div className="button-row">
                  <button className="secondary-button" onClick={() => onOpenSuperbill(superbill.id)}>View / Download</button>
                </div>
              </div>
            ))}
          </div>
        ) : <p className="portal-empty">No superbills yet.</p>}
      </div>

      <div>
        <p className="portal-section-heading">Payment history</p>
        {payments.receipts.length ? (
          <ul className="record-list" style={{ marginTop: ".5rem" }}>
            {payments.receipts.map((receipt) => (
              <li key={receipt.id}>
                <span><strong>${receipt.amount}</strong><small>{formatDate(receipt.receivedOn)}</small></span>
                <span className="status-pill completed">{receipt.statusLabel}</span>
              </li>
            ))}
          </ul>
        ) : <p className="portal-empty">No payments recorded yet.</p>}
      </div>
    </>
  );
}

export function PortalPaymentsPage() {
  const [openStatement, setOpenStatement] = useState<string | null>(null);
  const [openSuperbill, setOpenSuperbill] = useState<string | null>(null);

  if (openStatement) return <StatementDetail statementId={openStatement} onClose={() => setOpenStatement(null)} />;
  if (openSuperbill) return <SuperbillDetail superbillId={openSuperbill} onClose={() => setOpenSuperbill(null)} />;
  return <PaymentsOverview onOpenStatement={setOpenStatement} onOpenSuperbill={setOpenSuperbill} />;
}
