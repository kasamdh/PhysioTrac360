import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { Patient, PrivilegedAccessGrant } from "../api/types";
import { formatDate } from "../lib/format";
import { ConfirmActionDialog } from "./ConfirmActionDialog";
import { PrivilegedPatientChartDialog } from "./PrivilegedPatientChartDialog";
import { RequestPrivilegedAccessDialog } from "./RequestPrivilegedAccessDialog";

interface PrivilegedAccessTabProps {
  clientNumber: number;
  clientName: string;
}

export function PrivilegedAccessTab({ clientNumber, clientName }: PrivilegedAccessTabProps) {
  const [grants, setGrants] = useState<PrivilegedAccessGrant[] | null>(null);
  const [patients, setPatients] = useState<Patient[] | null>(null);
  const [error, setError] = useState("");
  const [showRequest, setShowRequest] = useState(false);
  const [revokingGrant, setRevokingGrant] = useState<PrivilegedAccessGrant | null>(null);
  const [viewingPatient, setViewingPatient] = useState<Patient | null>(null);

  const activeGrant = grants?.find((grant) => grant.isActive) || null;

  async function loadGrants() {
    try {
      const result = await api.privilegedAccessGrants(clientNumber);
      setGrants(result.grants);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load privileged-access history.");
    }
  }
  useEffect(() => { void loadGrants(); }, [clientNumber]);

  useEffect(() => {
    if (!activeGrant) {
      setPatients(null);
      return;
    }
    let active = true;
    api
      .privilegedPatients(clientNumber)
      .then((result) => active && setPatients(result.patients))
      .catch((requestError) => active && setError(requestError instanceof ApiError ? requestError.message : "Unable to load patients."));
    return () => {
      active = false;
    };
  }, [clientNumber, activeGrant?.id]);

  return (
    <section className="surface-card">
      <div className="card-heading">
        <h2>Privileged clinical access</h2>
        {!activeGrant && <button className="primary-button" onClick={() => setShowRequest(true)}>Request access</button>}
      </div>
      <p className="muted">
        Platform administrators have no standing access to clinical records. Viewing this
        client's charts requires an explicit, reasoned, time-boxed grant — every request,
        revocation, and chart read is audited.
      </p>
      {error && <p className="form-error" role="alert">{error}</p>}

      {activeGrant && (
        <div className="form-notice" role="status">
          Active access granted {formatDate(activeGrant.requestedAt, { month: "short", day: "numeric", year: "numeric" })},
          expires {formatDate(activeGrant.expiresAt, { month: "short", day: "numeric", year: "numeric" })} — {activeGrant.reason}
          {" "}<button className="text-action" onClick={() => setRevokingGrant(activeGrant)}>Revoke now</button>
        </div>
      )}

      {activeGrant && (
        <>
          <h3>Patients</h3>
          {patients === null && <p className="muted">Loading patients...</p>}
          {patients && !patients.length && <p className="empty-copy">This client has no patients yet.</p>}
          {patients && patients.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Name</th><th>MRN</th><th>Status</th><th>Assigned therapist</th><th></th></tr></thead>
                <tbody>
                  {patients.map((patient) => (
                    <tr key={patient.id}>
                      <td>{patient.fullName}</td>
                      <td>{patient.medicalRecordNumber}</td>
                      <td>{patient.statusLabel}</td>
                      <td>{patient.assignedTherapist?.displayName || "Not assigned"}</td>
                      <td><button className="text-action" onClick={() => setViewingPatient(patient)}>View chart</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      <h3>Access history</h3>
      {grants === null && <p className="muted">Loading history...</p>}
      {grants && !grants.length && <p className="empty-copy">No privileged access has ever been requested for this client.</p>}
      {grants && grants.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Requested</th><th>Actor</th><th>Reason</th><th>Expires</th><th>Status</th></tr></thead>
            <tbody>
              {grants.map((grant) => (
                <tr key={grant.id}>
                  <td>{formatDate(grant.requestedAt, { month: "short", day: "numeric", year: "numeric" })}</td>
                  <td>{grant.actor}</td>
                  <td>{grant.reason}</td>
                  <td>{formatDate(grant.expiresAt, { month: "short", day: "numeric", year: "numeric" })}</td>
                  <td>{grant.isActive ? "Active" : grant.revokedAt ? `Revoked by ${grant.revokedBy}` : "Expired"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showRequest && (
        <RequestPrivilegedAccessDialog
          clientNumber={clientNumber}
          clientName={clientName}
          onClose={() => setShowRequest(false)}
          onGranted={async () => { setShowRequest(false); await loadGrants(); }}
        />
      )}
      {revokingGrant && (
        <ConfirmActionDialog
          eyebrow={`#${clientNumber} ${clientName}`}
          title="Revoke privileged access?"
          body="This immediately ends your ability to view this client's clinical records. This action is audited."
          confirmLabel="Revoke access"
          onClose={() => setRevokingGrant(null)}
          onConfirm={async () => { await api.revokePrivilegedAccess(clientNumber, revokingGrant.id); setRevokingGrant(null); await loadGrants(); }}
        />
      )}
      {viewingPatient && (
        <PrivilegedPatientChartDialog clientNumber={clientNumber} patient={viewingPatient} onClose={() => setViewingPatient(null)} />
      )}
    </section>
  );
}
