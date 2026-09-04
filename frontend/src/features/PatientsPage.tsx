import { FormEvent, useCallback, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { Patient, WorkspaceUser } from "../api/types";
import { formatDate } from "../lib/format";
import { PatientFormDialog } from "./PatientFormDialog";
import { PatientWorkspace } from "./PatientWorkspace";

interface PatientsPageProps {
  user: WorkspaceUser;
}

export function PatientsPage({ user }: PatientsPageProps) {
  const [query, setQuery] = useState("");
  const [patients, setPatients] = useState<Patient[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [selectedPatientId, setSelectedPatientId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const loadPatients = useCallback(async (search: string) => {
    setLoading(true);
    setError("");
    try {
      const payload = await api.patients(search);
      setPatients(payload.patients);
      setTruncated(payload.truncated);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load patients.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPatients("");
  }, [loadPatients]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void loadPatients(query);
  }

  return (
    <div className="page-content">
      <header className="page-header split-header">
        <div><p className="eyebrow">Patient workspaces</p><h1>Patients</h1><p>Search is limited to your organization and role scope. Each workspace returns only the panels your role is allowed to access.</p></div>
        {user.capabilities.canManageSchedule && <button className="primary-button" onClick={() => setShowCreate(true)}>+ New patient</button>}
      </header>
      <section className="surface-card">
        <form className="search-form" onSubmit={submitSearch}>
          <label className="sr-only" htmlFor="patient-search">Search patients</label>
          <input id="patient-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search name or medical record number" />
          <button className="secondary-button" type="submit">Search</button>
        </form>
        {error && <p className="form-error" role="alert">{error}</p>}
        {loading ? <p className="empty-copy">Loading patients...</p> : patients.length ? (
          <div className="table-wrap"><table><thead><tr><th>Patient</th><th>MRN</th><th>Assigned therapist</th><th>Status</th><th /></tr></thead><tbody>
            {patients.map((patient) => <tr key={patient.id}>
              <td><strong>{patient.fullName}</strong><small>DOB {formatDate(patient.dateOfBirth)}</small></td>
              <td>{patient.medicalRecordNumber}</td>
              <td>{patient.assignedTherapist?.displayName || "Unassigned"}</td>
              <td><span className={`status-pill ${patient.status}`}>{patient.statusLabel}</span></td>
              <td><button className="text-action" onClick={() => setSelectedPatientId(patient.id)}>Open workspace</button></td>
            </tr>)}
          </tbody></table></div>
        ) : <p className="empty-copy">No patients match your search or access scope.</p>}
        {truncated && <p className="muted">Showing the first 100 matching patients. Refine your search to narrow results.</p>}
      </section>

      {selectedPatientId && <PatientWorkspace patientId={selectedPatientId} user={user} onClose={() => setSelectedPatientId(null)} />}
      {!user.capabilities.canAccessClinical && <p className="muted workspace-scope-copy">Your operational workspace intentionally excludes clinical narratives unless your role has clinical authorization.</p>}

      {showCreate && (
        <PatientFormDialog
          canEditClinicalFields={user.capabilities.canAccessClinical}
          onClose={() => setShowCreate(false)}
          onSave={(body) => api.createPatient(body)}
          onSaved={async () => { setShowCreate(false); await loadPatients(query); }}
        />
      )}
    </div>
  );
}
