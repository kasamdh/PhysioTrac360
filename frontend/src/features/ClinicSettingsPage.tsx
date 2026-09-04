import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { AppointmentType, ClinicLocation } from "../api/types";
import { AppointmentTypeFormDialog } from "./AppointmentTypeFormDialog";
import { LocationFormDialog } from "./LocationFormDialog";

type Tab = "locations" | "appointment-types";

export function ClinicSettingsPage() {
  const [tab, setTab] = useState<Tab>("locations");
  return (
    <div className="page-content">
      <header className="page-header split-header">
        <div>
          <p className="eyebrow">Settings</p>
          <h1>Clinic settings</h1>
          <p>Configure locations and appointment types for your organization.</p>
        </div>
      </header>
      <nav className="client-detail-tabs" aria-label="Clinic settings sections">
        <button className={tab === "locations" ? "active" : ""} onClick={() => setTab("locations")}>Locations</button>
        <button className={tab === "appointment-types" ? "active" : ""} onClick={() => setTab("appointment-types")}>Appointment types</button>
      </nav>
      {tab === "locations" && <LocationsTab />}
      {tab === "appointment-types" && <AppointmentTypesTab />}
    </div>
  );
}

function LocationsTab() {
  const [locations, setLocations] = useState<ClinicLocation[]>([]);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<ClinicLocation | null>(null);

  async function load() {
    try {
      setLocations((await api.locations()).locations);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load locations.");
    }
  }
  useEffect(() => { void load(); }, []);

  async function toggleActive(location: ClinicLocation) {
    setError("");
    try {
      if (location.isActive) {
        await api.deactivateLocation(location.id);
      } else {
        await api.updateLocation(location.id, { isActive: true });
      }
      await load();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to update this location.");
    }
  }

  return (
    <section className="surface-card">
      <div className="card-heading"><h2>Locations</h2><button className="primary-button" onClick={() => setOpen(true)}>+ Add location</button></div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Name</th><th>City / State</th><th>Timezone</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {locations.map((location) => (
              <tr key={location.id}>
                <td><strong>{location.name}</strong>{location.phone && <small>{location.phone}</small>}</td>
                <td>{location.city}{location.city && location.state ? ", " : ""}{location.state}</td>
                <td><small>{location.timezone}</small></td>
                <td>{location.isActive ? "Active" : "Inactive"}</td>
                <td>
                  <button className="text-action" onClick={() => setEditing(location)}>Edit</button>{" "}
                  <button className="text-action" onClick={() => void toggleActive(location)}>{location.isActive ? "Deactivate" : "Reactivate"}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!locations.length && <p className="empty-copy">No locations configured yet.</p>}
      {open && <LocationFormDialog onClose={() => setOpen(false)} onSaved={async () => { setOpen(false); await load(); }} />}
      {editing && <LocationFormDialog location={editing} onClose={() => setEditing(null)} onSaved={async () => { setEditing(null); await load(); }} />}
    </section>
  );
}

function AppointmentTypesTab() {
  const [types, setTypes] = useState<AppointmentType[]>([]);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<AppointmentType | null>(null);

  async function load() {
    try {
      setTypes((await api.appointmentTypes()).appointmentTypes);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load appointment types.");
    }
  }
  useEffect(() => { void load(); }, []);

  async function toggleActive(appointmentType: AppointmentType) {
    setError("");
    try {
      if (appointmentType.isActive) {
        await api.deactivateAppointmentType(appointmentType.id);
      } else {
        await api.updateAppointmentType(appointmentType.id, { isActive: true });
      }
      await load();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to update this appointment type.");
    }
  }

  return (
    <section className="surface-card">
      <div className="card-heading"><h2>Appointment types</h2><button className="primary-button" onClick={() => setOpen(true)}>+ Add type</button></div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Name</th><th>Default duration</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {types.map((appointmentType) => (
              <tr key={appointmentType.id}>
                <td><strong>{appointmentType.name}</strong></td>
                <td>{appointmentType.defaultDurationMinutes} min</td>
                <td>{appointmentType.isActive ? "Active" : "Inactive"}</td>
                <td>
                  <button className="text-action" onClick={() => setEditing(appointmentType)}>Edit</button>{" "}
                  <button className="text-action" onClick={() => void toggleActive(appointmentType)}>{appointmentType.isActive ? "Deactivate" : "Reactivate"}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!types.length && <p className="empty-copy">No appointment types configured yet.</p>}
      {open && <AppointmentTypeFormDialog onClose={() => setOpen(false)} onSaved={async () => { setOpen(false); await load(); }} />}
      {editing && <AppointmentTypeFormDialog appointmentType={editing} onClose={() => setEditing(null)} onSaved={async () => { setEditing(null); await load(); }} />}
    </section>
  );
}
