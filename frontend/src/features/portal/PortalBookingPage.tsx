import { useEffect, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { PortalAppointmentType, PublicLocation, PublicProvider, PublicProviderSlots } from "../../api/types";

type Step = "location" | "service" | "provider" | "datetime" | "review" | "confirmation";

const STEPS: { key: Step; label: string }[] = [
  { key: "location", label: "Location" },
  { key: "service", label: "Service" },
  { key: "provider", label: "Therapist" },
  { key: "datetime", label: "Date & Time" },
  { key: "review", label: "Confirm" },
];

const ANY_PROVIDER_ID = "";

interface SelectedSlot {
  start: string;
  end: string;
  providerId: string;
  providerName: string;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00`);
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

function formatTime(iso: string): string {
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(new Date(iso));
}

function formatDateHeading(iso: string): string {
  return new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric" }).format(new Date(`${iso}T12:00:00`));
}

function hourOf(iso: string): number {
  return new Date(iso).getHours();
}

function groupSlotsByPeriod(entry: PublicProviderSlots) {
  const morning = entry.slots.filter((slot) => hourOf(slot.start) < 12);
  const afternoon = entry.slots.filter((slot) => hourOf(slot.start) >= 12 && hourOf(slot.start) < 17);
  const evening = entry.slots.filter((slot) => hourOf(slot.start) >= 17);
  return [
    { label: "Morning", slots: morning },
    { label: "Afternoon", slots: afternoon },
    { label: "Evening", slots: evening },
  ].filter((group) => group.slots.length > 0);
}

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

interface PortalBookingPageProps {
  onBooked: () => void;
}

export function PortalBookingPage({ onBooked }: PortalBookingPageProps) {
  const [step, setStep] = useState<Step>("location");

  const [locations, setLocations] = useState<PublicLocation[]>([]);
  const [selectedLocation, setSelectedLocation] = useState<PublicLocation | null>(null);
  const [loadingLocations, setLoadingLocations] = useState(true);
  const [loadError, setLoadError] = useState("");

  const [appointmentTypes, setAppointmentTypes] = useState<PortalAppointmentType[]>([]);
  const [selectedAppointmentType, setSelectedAppointmentType] = useState<PortalAppointmentType | null>(null);

  const [providers, setProviders] = useState<PublicProvider[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState(ANY_PROVIDER_ID);

  const [date, setDate] = useState(todayIso());
  const [availabilityGroups, setAvailabilityGroups] = useState<PublicProviderSlots[]>([]);
  const [loadingSlots, setLoadingSlots] = useState(false);
  const [selectedSlot, setSelectedSlot] = useState<SelectedSlot | null>(null);
  const [reasonForVisit, setReasonForVisit] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [confirmedTime, setConfirmedTime] = useState("");

  useEffect(() => {
    let active = true;
    api
      .portalBookingLocations()
      .then((result) => {
        if (!active) return;
        setLocations(result.locations);
        if (result.locations.length === 1) {
          setSelectedLocation(result.locations[0]);
          setStep("service");
        }
      })
      .catch((error) => active && setLoadError(requestMessage(error, "Online scheduling isn't available right now.")))
      .finally(() => active && setLoadingLocations(false));
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedLocation) return;
    let active = true;
    api.portalBookingAppointmentTypes(selectedLocation.id).then((result) => active && setAppointmentTypes(result.appointmentTypes));
    return () => {
      active = false;
    };
  }, [selectedLocation]);

  useEffect(() => {
    if (!selectedLocation || !selectedAppointmentType) return;
    let active = true;
    api.portalBookingProviders(selectedLocation.id, selectedAppointmentType.id).then((result) => active && setProviders(result.providers));
    return () => {
      active = false;
    };
  }, [selectedLocation, selectedAppointmentType]);

  useEffect(() => {
    if (step !== "datetime" || !selectedLocation || !selectedAppointmentType) return;
    let active = true;
    setLoadingSlots(true);
    api
      .portalBookingAvailability(selectedLocation.id, selectedAppointmentType.id, date, selectedProviderId)
      .then((result) => active && setAvailabilityGroups(result.providers))
      .finally(() => active && setLoadingSlots(false));
    return () => {
      active = false;
    };
  }, [step, selectedLocation, selectedAppointmentType, selectedProviderId, date]);

  const stepIndex = STEPS.findIndex((entry) => entry.key === step);

  function chooseLocation(location: PublicLocation) {
    setSelectedLocation(location);
    setSelectedAppointmentType(null);
    setSelectedProviderId(ANY_PROVIDER_ID);
    setSelectedSlot(null);
    setStep("service");
  }

  function chooseAppointmentType(appointmentType: PortalAppointmentType) {
    setSelectedAppointmentType(appointmentType);
    setSelectedProviderId(ANY_PROVIDER_ID);
    setSelectedSlot(null);
    setStep("provider");
  }

  function chooseProvider(providerId: string) {
    setSelectedProviderId(providerId);
    setSelectedSlot(null);
    setStep("datetime");
  }

  function chooseSlot(entry: PublicProviderSlots, start: string, end: string) {
    setSelectedSlot({ start, end, providerId: entry.provider.id, providerName: entry.provider.displayName });
  }

  async function confirmBooking() {
    if (!selectedLocation || !selectedAppointmentType || !selectedSlot) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      await api.portalCreateBooking({
        locationId: selectedLocation.id,
        appointmentTypeId: selectedAppointmentType.id,
        providerId: selectedSlot.providerId,
        startDatetime: selectedSlot.start,
        reasonForVisit,
      });
      setConfirmedTime(selectedSlot.start);
      setStep("confirmation");
    } catch (error) {
      setSubmitError(requestMessage(error, "We couldn't complete this booking. Please try again."));
      if (error instanceof ApiError && error.status === 409) {
        setSelectedSlot(null);
        setStep("datetime");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (loadingLocations) return <p className="portal-empty">Loading scheduling options...</p>;
  if (loadError) return <p className="form-error" role="alert">{loadError}</p>;

  if (step === "confirmation") {
    return (
      <div className="booking-card">
        <div className="booking-step booking-confirmation">
          <div className="booking-confirmation-mark" aria-hidden="true">✓</div>
          <h2>You're booked!</h2>
          <p>{formatDateHeading(confirmedTime.slice(0, 10))} at {formatTime(confirmedTime)}</p>
          <button className="primary-button" onClick={onBooked}>View my appointments</button>
        </div>
      </div>
    );
  }

  return (
    <>
      <h1>Book a Visit</h1>
      <ol className="booking-stepper">
        {STEPS.map((entry, index) => (
          <li key={entry.key} className={index === stepIndex ? "active" : index < stepIndex ? "done" : ""}>
            <span className="booking-step-dot">{index < stepIndex ? "✓" : index + 1}</span>
            {entry.label}
          </li>
        ))}
      </ol>

      <section className="booking-card">
        {step === "location" && (
          <div className="booking-step">
            <h2>Choose a location</h2>
            <div className="booking-option-grid">
              {locations.map((location) => (
                <button key={location.id} className="booking-option-card" onClick={() => chooseLocation(location)}>
                  <strong>{location.name}</strong>
                  <small>{location.city}{location.city && location.state ? ", " : ""}{location.state}</small>
                </button>
              ))}
              {locations.length === 0 && <p className="portal-empty">No locations are currently open for online scheduling.</p>}
            </div>
          </div>
        )}

        {step === "service" && (
          <div className="booking-step">
            <h2>Choose a service</h2>
            <div className="booking-option-grid">
              {appointmentTypes.map((appointmentType) => (
                <button key={appointmentType.id} className="booking-option-card" onClick={() => chooseAppointmentType(appointmentType)}>
                  <strong>{appointmentType.name}</strong>
                  {appointmentType.description && <p>{appointmentType.description}</p>}
                  <small>{appointmentType.durationMinutes} min</small>
                </button>
              ))}
              {appointmentTypes.length === 0 && <p className="portal-empty">No services are available for online scheduling at this location.</p>}
            </div>
            <button className="secondary-button booking-back" onClick={() => setStep("location")}>Back</button>
          </div>
        )}

        {step === "provider" && (
          <div className="booking-step">
            <h2>Choose a therapist</h2>
            <div className="booking-option-grid">
              <button className="booking-option-card" onClick={() => chooseProvider(ANY_PROVIDER_ID)}>
                <strong>Any available therapist</strong>
                <small>See the soonest appointment with any qualified therapist</small>
              </button>
              {providers.map((provider) => (
                <button key={provider.id} className="booking-option-card" onClick={() => chooseProvider(provider.id)}>
                  <strong>{provider.displayName}{provider.credentials ? `, ${provider.credentials}` : ""}</strong>
                  {provider.specialty && <small>{provider.specialty}</small>}
                </button>
              ))}
            </div>
            <button className="secondary-button booking-back" onClick={() => setStep("service")}>Back</button>
          </div>
        )}

        {step === "datetime" && (
          <div className="booking-step">
            <h2>Pick a date &amp; time</h2>
            <div className="booking-date-nav">
              <button className="secondary-button" onClick={() => setDate((current) => addDays(current, -1))} disabled={date <= todayIso()}>← Earlier</button>
              <div className="booking-date-current">
                <strong>{formatDateHeading(date)}</strong>
                <input type="date" value={date} min={todayIso()} onChange={(event) => setDate(event.target.value)} />
              </div>
              <button className="secondary-button" onClick={() => setDate((current) => addDays(current, 1))}>Later →</button>
            </div>

            {loadingSlots && <p className="portal-empty">Loading available times…</p>}
            {!loadingSlots && availabilityGroups.every((entry) => entry.slots.length === 0) && (
              <p className="portal-empty">No open times on this date. Try another day.</p>
            )}

            <div className="booking-slot-groups">
              {availabilityGroups.map((entry) => (
                <div key={entry.provider.id} className="booking-provider-slots">
                  {(selectedProviderId === ANY_PROVIDER_ID || availabilityGroups.length > 1) && <h3>{entry.provider.displayName}</h3>}
                  {groupSlotsByPeriod(entry).map((group) => (
                    <div key={group.label} className="booking-slot-period">
                      <p className="booking-slot-period-label">{group.label}</p>
                      <div className="booking-slot-grid">
                        {group.slots.map((slot) => (
                          <button
                            key={slot.start}
                            className={`booking-slot-chip${selectedSlot?.start === slot.start && selectedSlot?.providerId === entry.provider.id ? " selected" : ""}`}
                            onClick={() => chooseSlot(entry, slot.start, slot.end)}
                          >
                            {formatTime(slot.start)}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>

            <div className="booking-step-actions">
              <button className="secondary-button" onClick={() => setStep("provider")}>Back</button>
              <button className="primary-button" disabled={!selectedSlot} onClick={() => setStep("review")}>Continue</button>
            </div>
          </div>
        )}

        {step === "review" && selectedLocation && selectedAppointmentType && selectedSlot && (
          <div className="booking-step">
            <h2>Confirm your appointment</h2>
            <dl className="booking-review-list">
              <div><dt>Location</dt><dd>{selectedLocation.name}</dd></div>
              <div><dt>Service</dt><dd>{selectedAppointmentType.name}</dd></div>
              <div><dt>Therapist</dt><dd>{selectedSlot.providerName}</dd></div>
              <div><dt>Date &amp; time</dt><dd>{formatDateHeading(date)} at {formatTime(selectedSlot.start)}</dd></div>
            </dl>
            <label>
              <span>Reason for visit (optional)</span>
              <textarea value={reasonForVisit} onChange={(event) => setReasonForVisit(event.target.value)} />
            </label>
            {submitError && <p className="form-error" role="alert">{submitError}</p>}
            <div className="booking-step-actions">
              <button className="secondary-button" onClick={() => setStep("datetime")} disabled={submitting}>Back</button>
              <button className="primary-button" onClick={() => void confirmBooking()} disabled={submitting}>
                {submitting ? "Booking…" : "Confirm booking"}
              </button>
            </div>
          </div>
        )}
      </section>
    </>
  );
}
