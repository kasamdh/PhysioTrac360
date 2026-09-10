import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { AppointmentType, ClinicLocation, Payer, ServicePrice } from "../api/types";
import { AppointmentTypeFormDialog } from "./AppointmentTypeFormDialog";
import { LocationFormDialog } from "./LocationFormDialog";
import { PayerFormDialog } from "./PayerFormDialog";

type Tab = "locations" | "appointment-types" | "payers" | "service-prices";

export function ClinicSettingsPage() {
  const [tab, setTab] = useState<Tab>("locations");
  return (
    <div className="page-content">
      <header className="page-header split-header">
        <div>
          <p className="eyebrow">Settings</p>
          <h1>Clinic settings</h1>
          <p>Configure locations, appointment types, the insurance payer directory, and cash-pay pricing for your organization.</p>
        </div>
      </header>
      <nav className="client-detail-tabs" aria-label="Clinic settings sections">
        <button className={tab === "locations" ? "active" : ""} onClick={() => setTab("locations")}>Locations</button>
        <button className={tab === "appointment-types" ? "active" : ""} onClick={() => setTab("appointment-types")}>Appointment types</button>
        <button className={tab === "payers" ? "active" : ""} onClick={() => setTab("payers")}>Payers</button>
        <button className={tab === "service-prices" ? "active" : ""} onClick={() => setTab("service-prices")}>Cash-pay prices</button>
      </nav>
      {tab === "locations" && <LocationsTab />}
      {tab === "appointment-types" && <AppointmentTypesTab />}
      {tab === "payers" && <PayersTab />}
      {tab === "service-prices" && <ServicePricesTab />}
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

function PayersTab() {
  const [payers, setPayers] = useState<Payer[]>([]);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Payer | null>(null);

  async function load() {
    try {
      setPayers((await api.payers()).payers);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load the payer directory.");
    }
  }
  useEffect(() => { void load(); }, []);

  async function toggleActive(payer: Payer) {
    setError("");
    try {
      if (payer.isActive) {
        await api.deactivatePayer(payer.id);
      } else {
        await api.updatePayer(payer.id, { isActive: true });
      }
      await load();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to update this payer.");
    }
  }

  return (
    <section className="surface-card">
      <div className="card-heading"><h2>Payer directory</h2><button className="primary-button" onClick={() => setOpen(true)}>+ Add payer</button></div>
      <p className="muted">Timely filing windows and authorization requirements live here as data — never hard-coded — so billing staff can maintain them directly.</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Payer</th><th>Electronic ID</th><th>Timely filing</th><th>Auth required</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {payers.map((payer) => (
              <tr key={payer.id}>
                <td><strong>{payer.name}</strong>{payer.phone && <small>{payer.phone}</small>}</td>
                <td>{payer.electronicPayerId || "—"}</td>
                <td>{payer.timelyFilingDays} days</td>
                <td>{payer.authorizationRequired ? "Yes" : "No"}</td>
                <td>{payer.isActive ? "Active" : "Inactive"}</td>
                <td>
                  <button className="text-action" onClick={() => setEditing(payer)}>Edit</button>{" "}
                  <button className="text-action" onClick={() => void toggleActive(payer)}>{payer.isActive ? "Deactivate" : "Reactivate"}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!payers.length && <p className="empty-copy">No payers configured yet.</p>}
      {open && <PayerFormDialog onClose={() => setOpen(false)} onSaved={async () => { setOpen(false); await load(); }} />}
      {editing && <PayerFormDialog payer={editing} onClose={() => setEditing(null)} onSaved={async () => { setEditing(null); await load(); }} />}
    </section>
  );
}

function ServicePricesTab() {
  const [prices, setPrices] = useState<ServicePrice[]>([]);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState({ cptCode: "", label: "", price: "" });
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setPrices((await api.servicePrices()).servicePrices);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load cash-pay prices.");
    }
  }
  useEffect(() => { void load(); }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await api.createServicePrice({ cptCode: draft.cptCode.toUpperCase(), label: draft.label, price: draft.price });
      setDraft({ cptCode: "", label: "", price: "" });
      await load();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to save this price.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(price: ServicePrice) {
    setError("");
    try {
      if (price.isActive) {
        await api.deactivateServicePrice(price.id);
      } else {
        await api.updateServicePrice(price.id, { isActive: true });
      }
      await load();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to update this price.");
    }
  }

  return (
    <section className="surface-card">
      <div className="card-heading"><h2>Cash-pay price list</h2></div>
      <p className="muted">Deliberately data-driven, not hard-coded — cash-pay charges look up a price here per CPT/HCPCS code.</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      <form className="inline-form" onSubmit={create}>
        <input placeholder="CPT code" value={draft.cptCode} onChange={(event) => setDraft({ ...draft, cptCode: event.target.value })} required />
        <input placeholder="Label" value={draft.label} onChange={(event) => setDraft({ ...draft, label: event.target.value })} required />
        <input type="number" step="0.01" min="0.01" placeholder="Price" value={draft.price} onChange={(event) => setDraft({ ...draft, price: event.target.value })} required />
        <button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving..." : "+ Add price"}</button>
      </form>
      <div className="table-wrap">
        <table>
          <thead><tr><th>CPT</th><th>Label</th><th>Price</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {prices.map((price) => (
              <tr key={price.id}>
                <td><strong>{price.cptCode}</strong></td>
                <td>{price.label}</td>
                <td>${price.price}</td>
                <td>{price.isActive ? "Active" : "Inactive"}</td>
                <td><button className="text-action" onClick={() => void toggleActive(price)}>{price.isActive ? "Deactivate" : "Reactivate"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!prices.length && <p className="empty-copy">No cash-pay prices configured yet.</p>}
    </section>
  );
}
