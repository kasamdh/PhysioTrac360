import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type {
  AppointmentType,
  ClinicLocation,
  MobileCareConfiguration,
  MobileCareProviderMatch,
  MobileCareServiceArea,
  Payer,
  ServicePrice,
} from "../api/types";
import { AppointmentTypeFormDialog } from "./AppointmentTypeFormDialog";
import { LocationFormDialog } from "./LocationFormDialog";
import { PayerFormDialog } from "./PayerFormDialog";

type Tab = "locations" | "appointment-types" | "payers" | "service-prices" | "service-areas" | "mobile-care-settings";

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
        <button className={tab === "service-areas" ? "active" : ""} onClick={() => setTab("service-areas")}>In-home PT areas</button>
        <button className={tab === "mobile-care-settings" ? "active" : ""} onClick={() => setTab("mobile-care-settings")}>Mobile Care settings</button>
      </nav>
      {tab === "locations" && <LocationsTab />}
      {tab === "appointment-types" && <AppointmentTypesTab />}
      {tab === "payers" && <PayersTab />}
      {tab === "service-prices" && <ServicePricesTab />}
      {tab === "service-areas" && <ServiceAreasTab />}
      {tab === "mobile-care-settings" && <MobileCareSettingsTab />}
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

const HOME_VISIT_KIND_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Not a home-visit price" },
  { value: "evaluation", label: "Home visit — Initial evaluation" },
  { value: "follow_up", label: "Home visit — Follow-up" },
  { value: "progress", label: "Home visit — Progress visit" },
  { value: "discharge", label: "Home visit — Discharge visit" },
];

function ServicePricesTab() {
  const [prices, setPrices] = useState<ServicePrice[]>([]);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState({
    cptCode: "", label: "", price: "", homeVisitKind: "", isHomeVisitTravelFee: false, depositAmount: "",
  });
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
      await api.createServicePrice({
        cptCode: draft.cptCode.toUpperCase(),
        label: draft.label,
        price: draft.price,
        homeVisitKind: draft.homeVisitKind || undefined,
        isHomeVisitTravelFee: draft.isHomeVisitTravelFee,
        depositAmount: draft.depositAmount || undefined,
      });
      setDraft({ cptCode: "", label: "", price: "", homeVisitKind: "", isHomeVisitTravelFee: false, depositAmount: "" });
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
      <p className="muted">
        Deliberately data-driven, not hard-coded — cash-pay charges look up a price here per CPT/HCPCS code. Tag a row as a
        Mobile Care home-visit price (e.g. "Home PT Initial Evaluation") or as the org's optional home-visit travel fee so
        Mobile Care billing uses it automatically instead of a hard-coded amount.
      </p>
      {error && <p className="form-error" role="alert">{error}</p>}
      <form className="inline-form" onSubmit={create}>
        <input placeholder="CPT code" value={draft.cptCode} onChange={(event) => setDraft({ ...draft, cptCode: event.target.value })} required />
        <input placeholder="Label (e.g. Home PT Initial Evaluation)" value={draft.label} onChange={(event) => setDraft({ ...draft, label: event.target.value })} required />
        <input type="number" step="0.01" min="0.01" placeholder="Price" value={draft.price} onChange={(event) => setDraft({ ...draft, price: event.target.value })} required />
        <select
          value={draft.homeVisitKind}
          onChange={(event) => setDraft({ ...draft, homeVisitKind: event.target.value, isHomeVisitTravelFee: false })}
        >
          {HOME_VISIT_KIND_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
        <label style={{ display: "flex", alignItems: "center", gap: ".5rem" }}>
          <input
            type="checkbox"
            checked={draft.isHomeVisitTravelFee}
            onChange={(event) => setDraft({ ...draft, isHomeVisitTravelFee: event.target.checked, homeVisitKind: "" })}
          />
          Home visit travel fee
        </label>
        {draft.homeVisitKind && (
          <input
            type="number"
            step="0.01"
            min="0.01"
            placeholder="Deposit ($, optional)"
            value={draft.depositAmount}
            onChange={(event) => setDraft({ ...draft, depositAmount: event.target.value })}
          />
        )}
        <button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving..." : "+ Add price"}</button>
      </form>
      <div className="table-wrap">
        <table>
          <thead><tr><th>CPT</th><th>Label</th><th>Price</th><th>Mobile Care tag</th><th>Deposit</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {prices.map((price) => (
              <tr key={price.id}>
                <td><strong>{price.cptCode}</strong></td>
                <td>{price.label}</td>
                <td>${price.price}</td>
                <td>{price.isHomeVisitTravelFee ? "Travel fee" : price.homeVisitKindLabel || "—"}</td>
                <td>{price.depositAmount ? `$${price.depositAmount}` : "—"}</td>
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

function parseZipCodes(raw: string): string[] {
  return Array.from(new Set(raw.split(/[\s,]+/).map((value) => value.trim()).filter(Boolean)));
}

function ServiceAreasTab() {
  const [areas, setAreas] = useState<MobileCareServiceArea[]>([]);
  const [providers, setProviders] = useState<MobileCareProviderMatch[]>([]);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState({ providerId: "", name: "", zipCodes: "" });
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingZipCodes, setEditingZipCodes] = useState("");

  async function load() {
    try {
      const [areasResult, providersResult] = await Promise.all([api.mobileCareServiceAreas(), api.mobileCareProviders()]);
      setAreas(areasResult.serviceAreas);
      setProviders(providersResult.providers);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load in-home PT service areas.");
    }
  }
  useEffect(() => { void load(); }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.createMobileCareServiceArea({
        providerId: draft.providerId,
        name: draft.name,
        zipCodes: parseZipCodes(draft.zipCodes),
      });
      setDraft({ providerId: "", name: "", zipCodes: "" });
      await load();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to save this service area.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(area: MobileCareServiceArea) {
    setError("");
    try {
      if (area.isActive) {
        await api.deactivateMobileCareServiceArea(area.id);
      } else {
        await api.updateMobileCareServiceArea(area.id, { isActive: true });
      }
      await load();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to update this service area.");
    }
  }

  async function saveZipCodes(areaId: string) {
    setError("");
    try {
      await api.updateMobileCareServiceArea(areaId, { zipCodes: parseZipCodes(editingZipCodes) });
      setEditingId(null);
      await load();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to update the ZIP codes.");
    }
  }

  return (
    <section className="surface-card">
      <div className="card-heading"><h2>In-home PT service areas</h2></div>
      <p className="muted">Each provider's covered ZIP codes for in-home visits — used to match new in-home PT requests to a provider.</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      <form className="inline-form" onSubmit={create}>
        <select value={draft.providerId} onChange={(event) => setDraft({ ...draft, providerId: event.target.value })} required>
          <option value="" disabled>Select provider</option>
          {providers.map((provider) => (
            <option key={provider.id} value={provider.id}>{provider.displayName}</option>
          ))}
        </select>
        <input placeholder="Area name" value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} required />
        <input
          placeholder="ZIP codes (comma-separated)"
          value={draft.zipCodes}
          onChange={(event) => setDraft({ ...draft, zipCodes: event.target.value })}
          required
        />
        <button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving..." : "+ Add service area"}</button>
      </form>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Provider</th><th>Area</th><th>ZIP codes</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {areas.map((area) => (
              <tr key={area.id}>
                <td><strong>{area.providerName}</strong></td>
                <td>{area.name}</td>
                <td>
                  {editingId === area.id ? (
                    <input value={editingZipCodes} onChange={(event) => setEditingZipCodes(event.target.value)} />
                  ) : (
                    area.zipCodes.join(", ")
                  )}
                </td>
                <td>{area.isActive ? "Active" : "Inactive"}</td>
                <td>
                  {editingId === area.id ? (
                    <>
                      <button className="text-action" onClick={() => void saveZipCodes(area.id)}>Save</button>{" "}
                      <button className="text-action" onClick={() => setEditingId(null)}>Cancel</button>
                    </>
                  ) : (
                    <>
                      <button className="text-action" onClick={() => { setEditingId(area.id); setEditingZipCodes(area.zipCodes.join(", ")); }}>
                        Edit ZIPs
                      </button>{" "}
                      <button className="text-action" onClick={() => void toggleActive(area)}>{area.isActive ? "Deactivate" : "Reactivate"}</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!areas.length && <p className="empty-copy">No in-home PT service areas configured yet.</p>}
    </section>
  );
}

const AVAILABLE_SERVICE_OPTIONS: { value: string; label: string }[] = [
  { value: "evaluation", label: "Initial evaluation" },
  { value: "follow_up", label: "Follow-up visit" },
  { value: "progress", label: "Progress visit" },
  { value: "discharge", label: "Discharge visit" },
];

const PROVIDER_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "therapist", label: "Physical therapist" },
  { value: "assistant", label: "PTA / therapy assistant" },
];

const MATCH_WEIGHT_DIMENSIONS: { key: string; label: string }[] = [
  { key: "continuity", label: "Continuity of care" },
  { key: "specialty", label: "Specialty match" },
  { key: "availability", label: "Availability" },
  { key: "distance", label: "Distance / service area" },
  { key: "preference", label: "Patient preference" },
  { key: "caseload", label: "Existing caseload" },
];

const NOTIFICATION_EVENT_OPTIONS: { code: string; label: string }[] = [
  { code: "SERVICE_REQUEST_CREATED", label: "Request received" },
  { code: "PROVIDER_MATCH_FOUND", label: "Provider match found" },
  { code: "PROVIDER_OFFER_CREATED", label: "Provider offer created" },
  { code: "PROVIDER_OFFER_ACCEPTED", label: "Provider offer accepted" },
  { code: "PROVIDER_OFFER_DECLINED", label: "Provider offer declined" },
  { code: "VISIT_SCHEDULED", label: "Visit scheduled" },
  { code: "VISIT_REMINDER", label: "Visit reminder" },
  { code: "PROVIDER_EN_ROUTE", label: "Provider en route" },
  { code: "PROVIDER_ARRIVED", label: "Provider arrived" },
  { code: "VISIT_COMPLETED", label: "Visit completed" },
  { code: "VISIT_CANCELLED", label: "Visit cancelled" },
];

function toggleInList(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((entry) => entry !== value) : [...list, value];
}

function MobileCareSettingsTab() {
  const [config, setConfig] = useState<MobileCareConfiguration | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setConfig((await api.mobileCareConfiguration()).configuration);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load Mobile Care settings.");
    }
  }
  useEffect(() => { void load(); }, []);

  function update<K extends keyof MobileCareConfiguration>(key: K, value: MobileCareConfiguration[K]) {
    setConfig((current) => (current ? { ...current, [key]: value } : current));
    setSaved(false);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!config) return;
    setBusy(true); setError(""); setSaved(false);
    try {
      const result = await api.updateMobileCareConfiguration({
        mobileCareEnabled: config.mobileCareEnabled,
        defaultVisitDurationMinutes: config.defaultVisitDurationMinutes,
        availableServices: config.availableServices,
        allowedProviderRoles: config.allowedProviderRoles,
        maxTravelRadiusMiles: config.maxTravelRadiusMiles,
        offerExpirationHours: config.offerExpirationHours,
        patientCancellationWindowHours: config.patientCancellationWindowHours,
        providerCancellationNoticeHours: config.providerCancellationNoticeHours,
        providerCancellationRequiresReason: config.providerCancellationRequiresReason,
        sameProviderContinuityPreferred: config.sameProviderContinuityPreferred,
        matchWeightOverrides: config.matchWeightOverrides,
        serviceHoursStart: config.serviceHoursStart,
        serviceHoursEnd: config.serviceHoursEnd,
        disabledNotificationEvents: config.disabledNotificationEvents,
      });
      setConfig(result.configuration);
      setSaved(true);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to save these settings.");
    } finally {
      setBusy(false);
    }
  }

  if (!config) {
    return (
      <section className="surface-card">
        {error ? <p className="form-error" role="alert">{error}</p> : <p className="empty-copy">Loading…</p>}
      </section>
    );
  }

  return (
    <section className="surface-card">
      <div className="card-heading"><h2>Mobile Care settings</h2></div>
      <p className="muted">
        Configure how Mobile Care (in-home PT) works for your organization. Service Areas and Self-Pay Pricing/the
        Travel Fee are configured on their own tabs above.
      </p>
      {error && <p className="form-error" role="alert">{error}</p>}
      {saved && <p className="empty-copy">Saved.</p>}
      <form onSubmit={save}>
        <label style={{ display: "flex", alignItems: "center", gap: ".5rem" }}>
          <input type="checkbox" checked={config.mobileCareEnabled} onChange={(event) => update("mobileCareEnabled", event.target.checked)} />
          Enable Mobile Care for this organization
        </label>

        <div className="field-grid">
          <label>
            Default visit duration (minutes)
            <input
              type="number" min="1" placeholder="Platform default"
              value={config.defaultVisitDurationMinutes ?? ""}
              onChange={(event) => update("defaultVisitDurationMinutes", event.target.value ? Number(event.target.value) : null)}
            />
          </label>
          <label>
            Maximum travel radius (miles)
            <input
              type="number" min="1" placeholder="Platform default"
              value={config.maxTravelRadiusMiles ?? ""}
              onChange={(event) => update("maxTravelRadiusMiles", event.target.value ? Number(event.target.value) : null)}
            />
          </label>
          <label>
            Offer expiration time (hours)
            <input
              type="number" min="1" placeholder="Platform default"
              value={config.offerExpirationHours ?? ""}
              onChange={(event) => update("offerExpirationHours", event.target.value ? Number(event.target.value) : null)}
            />
          </label>
          <label>
            Patient cancellation window (hours)
            <input
              type="number" min="0" placeholder="Platform default"
              value={config.patientCancellationWindowHours ?? ""}
              onChange={(event) => update("patientCancellationWindowHours", event.target.value ? Number(event.target.value) : null)}
            />
          </label>
          <label>
            Provider cancellation notice (hours)
            <input
              type="number" min="0" placeholder="Platform default"
              value={config.providerCancellationNoticeHours ?? ""}
              onChange={(event) => update("providerCancellationNoticeHours", event.target.value ? Number(event.target.value) : null)}
            />
          </label>
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: ".5rem" }}>
          <input
            type="checkbox" checked={config.providerCancellationRequiresReason}
            onChange={(event) => update("providerCancellationRequiresReason", event.target.checked)}
          />
          Require a reason when a provider cancels within the notice window
        </label>

        <h3>Available services</h3>
        <p className="muted">Which visit types this organization offers via Mobile Care. Leave all unchecked to offer every type.</p>
        <div className="field-grid">
          {AVAILABLE_SERVICE_OPTIONS.map((option) => (
            <label key={option.value} style={{ display: "flex", alignItems: "center", gap: ".5rem" }}>
              <input
                type="checkbox" checked={config.availableServices.includes(option.value)}
                onChange={() => update("availableServices", toggleInList(config.availableServices, option.value))}
              />
              {option.label}
            </label>
          ))}
        </div>

        <h3>Provider types</h3>
        <p className="muted">Which provider types may be assigned Mobile Care visits. Leave all unchecked to allow every type.</p>
        <div className="field-grid">
          {PROVIDER_TYPE_OPTIONS.map((option) => (
            <label key={option.value} style={{ display: "flex", alignItems: "center", gap: ".5rem" }}>
              <input
                type="checkbox" checked={config.allowedProviderRoles.includes(option.value)}
                onChange={() => update("allowedProviderRoles", toggleInList(config.allowedProviderRoles, option.value))}
              />
              {option.label}
            </label>
          ))}
        </div>

        <h3>Same-provider continuity preference</h3>
        <select
          value={config.sameProviderContinuityPreferred === null ? "" : String(config.sameProviderContinuityPreferred)}
          onChange={(event) => update("sameProviderContinuityPreferred", event.target.value === "" ? null : event.target.value === "true")}
        >
          <option value="">Use platform default</option>
          <option value="true">Prefer the patient's existing provider</option>
          <option value="false">Off — rank purely on the other dimensions</option>
        </select>

        <h3>Matching settings</h3>
        <p className="muted">Optional per-dimension ranking weight overrides. Leave blank to keep the platform default weight.</p>
        <div className="field-grid">
          {MATCH_WEIGHT_DIMENSIONS.map((dimension) => (
            <label key={dimension.key}>
              {dimension.label}
              <input
                type="number" min="0" step="0.1" placeholder="Default"
                value={config.matchWeightOverrides[dimension.key] ?? ""}
                onChange={(event) => {
                  const next = { ...config.matchWeightOverrides };
                  if (event.target.value) {
                    next[dimension.key] = Number(event.target.value);
                  } else {
                    delete next[dimension.key];
                  }
                  update("matchWeightOverrides", next);
                }}
              />
            </label>
          ))}
        </div>

        <h3>Service hours</h3>
        <p className="muted">The org-wide window a home visit's scheduled time must fall within. Leave blank for no restriction.</p>
        <div className="field-grid">
          <label>
            Starts no earlier than
            <input type="time" value={config.serviceHoursStart ?? ""} onChange={(event) => update("serviceHoursStart", event.target.value || null)} />
          </label>
          <label>
            Ends no later than
            <input type="time" value={config.serviceHoursEnd ?? ""} onChange={(event) => update("serviceHoursEnd", event.target.value || null)} />
          </label>
        </div>

        <h3>Notification settings</h3>
        <p className="muted">Turn off any Mobile Care event this organization doesn't want sent, in any channel.</p>
        <div className="field-grid">
          {NOTIFICATION_EVENT_OPTIONS.map((event_) => (
            <label key={event_.code} style={{ display: "flex", alignItems: "center", gap: ".5rem" }}>
              <input
                type="checkbox"
                checked={!config.disabledNotificationEvents.includes(event_.code)}
                onChange={() =>
                  update("disabledNotificationEvents", toggleInList(config.disabledNotificationEvents, event_.code))
                }
              />
              {event_.label}
            </label>
          ))}
        </div>

        <div className="button-row">
          <button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving..." : "Save Mobile Care settings"}</button>
        </div>
      </form>
    </section>
  );
}
