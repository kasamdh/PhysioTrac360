import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type {
  PublicAppointmentType,
  PublicBookingConfirmation,
  PublicLocation,
  PublicOrganization,
  PublicProvider,
  PublicProviderSlots,
} from "../api/types";

type Step = "location" | "service" | "provider" | "datetime" | "info" | "review" | "confirmation";

const STEPS: { key: Step; label: string }[] = [
  { key: "location", label: "Location" },
  { key: "service", label: "Service" },
  { key: "provider", label: "Therapist" },
  { key: "datetime", label: "Date & Time" },
  { key: "info", label: "Your info" },
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

function formatTime(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", timeZone }).format(new Date(iso));
}

function formatDateHeading(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone,
  }).format(new Date(`${iso}T12:00:00`));
}

function hourOf(iso: string, timeZone: string): number {
  return Number(new Intl.DateTimeFormat("en-US", { hour: "numeric", hour12: false, timeZone }).format(new Date(iso)));
}

function groupSlotsByPeriod(entry: PublicProviderSlots, timeZone: string) {
  const morning = entry.slots.filter((slot) => hourOf(slot.start, timeZone) < 12);
  const afternoon = entry.slots.filter((slot) => {
    const hour = hourOf(slot.start, timeZone);
    return hour >= 12 && hour < 17;
  });
  const evening = entry.slots.filter((slot) => hourOf(slot.start, timeZone) >= 17);
  return [
    { label: "Morning", slots: morning },
    { label: "Afternoon", slots: afternoon },
    { label: "Evening", slots: evening },
  ].filter((group) => group.slots.length > 0);
}

interface PublicBookingPageProps {
  slug: string;
}

export function PublicBookingPage({ slug }: PublicBookingPageProps) {
  const [organization, setOrganization] = useState<PublicOrganization | null>(null);
  const [loadingOrganization, setLoadingOrganization] = useState(true);
  const [loadError, setLoadError] = useState("");

  const [step, setStep] = useState<Step>("location");

  const [locations, setLocations] = useState<PublicLocation[]>([]);
  const [selectedLocation, setSelectedLocation] = useState<PublicLocation | null>(null);

  const [appointmentTypes, setAppointmentTypes] = useState<PublicAppointmentType[]>([]);
  const [selectedAppointmentType, setSelectedAppointmentType] = useState<PublicAppointmentType | null>(null);

  const [providers, setProviders] = useState<PublicProvider[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState<string>(ANY_PROVIDER_ID);

  const [date, setDate] = useState(todayIso());
  const [availabilityGroups, setAvailabilityGroups] = useState<PublicProviderSlots[]>([]);
  const [loadingSlots, setLoadingSlots] = useState(false);
  const [selectedSlot, setSelectedSlot] = useState<SelectedSlot | null>(null);

  const [isNewPatient, setIsNewPatient] = useState(true);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [dateOfBirth, setDateOfBirth] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [reasonForVisit, setReasonForVisit] = useState("");
  const [infoError, setInfoError] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [confirmation, setConfirmation] = useState<PublicBookingConfirmation | null>(null);

  const timeZone = selectedLocation?.timezone || organization?.timezone || "America/New_York";

  useEffect(() => {
    let active = true;
    api
      .publicOrganization(slug)
      .then((org) => {
        if (!active) return;
        setOrganization(org);
        return api.publicLocations(slug).then((result) => {
          if (!active) return;
          setLocations(result.locations);
          if (result.locations.length === 1) {
            setSelectedLocation(result.locations[0]);
            setStep("service");
          }
        });
      })
      .catch((error) => {
        if (!active) return;
        setLoadError(
          error instanceof ApiError ? error.message : "This booking page is not available right now.",
        );
      })
      .finally(() => active && setLoadingOrganization(false));
    return () => {
      active = false;
    };
  }, [slug]);

  useEffect(() => {
    if (!selectedLocation) return;
    let active = true;
    api.publicAppointmentTypes(slug, selectedLocation.id).then((result) => {
      if (active) setAppointmentTypes(result.appointmentTypes);
    });
    return () => {
      active = false;
    };
  }, [slug, selectedLocation]);

  useEffect(() => {
    if (!selectedLocation || !selectedAppointmentType) return;
    let active = true;
    api.publicProviders(slug, selectedLocation.id, selectedAppointmentType.id).then((result) => {
      if (active) setProviders(result.providers);
    });
    return () => {
      active = false;
    };
  }, [slug, selectedLocation, selectedAppointmentType]);

  useEffect(() => {
    if (step !== "datetime" || !selectedLocation || !selectedAppointmentType) return;
    let active = true;
    setLoadingSlots(true);
    api
      .publicAvailability(slug, selectedLocation.id, selectedAppointmentType.id, date, selectedProviderId)
      .then((result) => {
        if (active) setAvailabilityGroups(result.providers);
      })
      .finally(() => active && setLoadingSlots(false));
    return () => {
      active = false;
    };
  }, [step, slug, selectedLocation, selectedAppointmentType, selectedProviderId, date]);

  const stepIndex = STEPS.findIndex((entry) => entry.key === step);

  function goTo(next: Step) {
    setStep(next);
  }

  function chooseLocation(location: PublicLocation) {
    setSelectedLocation(location);
    setSelectedAppointmentType(null);
    setSelectedProviderId(ANY_PROVIDER_ID);
    setSelectedSlot(null);
    goTo("service");
  }

  function chooseAppointmentType(appointmentType: PublicAppointmentType) {
    setSelectedAppointmentType(appointmentType);
    setSelectedProviderId(ANY_PROVIDER_ID);
    setSelectedSlot(null);
    goTo("provider");
  }

  function chooseProvider(providerId: string) {
    setSelectedProviderId(providerId);
    setSelectedSlot(null);
    goTo("datetime");
  }

  function chooseSlot(entry: PublicProviderSlots, slotStart: string, slotEnd: string) {
    setSelectedSlot({
      start: slotStart,
      end: slotEnd,
      providerId: entry.provider.id,
      providerName: entry.provider.displayName,
    });
  }

  function handleInfoSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setInfoError("");
    if (!firstName.trim() || !lastName.trim() || !dateOfBirth) {
      setInfoError("First name, last name, and date of birth are required.");
      return;
    }
    if (!email.trim() && !phone.trim()) {
      setInfoError("Provide an email or phone number so we can reach you about this appointment.");
      return;
    }
    goTo("review");
  }

  async function confirmBooking() {
    if (!selectedLocation || !selectedAppointmentType || !selectedSlot) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      const result = await api.publicCreateBooking({
        organizationSlug: slug,
        locationId: selectedLocation.id,
        appointmentTypeId: selectedAppointmentType.id,
        providerId: selectedSlot.providerId,
        startDatetime: selectedSlot.start,
        isNewPatient,
        patient: { firstName, lastName, dateOfBirth, email, phone },
        reasonForVisit,
      });
      setConfirmation(result);
      goTo("confirmation");
    } catch (error) {
      setSubmitError(
        error instanceof ApiError
          ? error.message
          : "We couldn't complete this booking. Please try again.",
      );
      if (error instanceof ApiError && error.status === 409) {
        setSelectedSlot(null);
        goTo("datetime");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (loadingOrganization) {
    return <main className="booking-loading">Loading booking page…</main>;
  }
  if (loadError || !organization) {
    return (
      <main className="booking-loading">
        <div className="booking-unavailable">
          <h1>Booking unavailable</h1>
          <p>{loadError || "This booking page is not available."}</p>
        </div>
      </main>
    );
  }

  return (
    <main className="booking-page">
      <header className="booking-header">
        <div className="booking-brand">
          {organization.logoUrl ? (
            <img src={organization.logoUrl} alt="" />
          ) : (
            <span className="booking-brand-mark" aria-hidden="true">
              {organization.name.slice(0, 2).toUpperCase()}
            </span>
          )}
          <div>
            <strong>{organization.name}</strong>
            <small>Book an appointment online</small>
          </div>
        </div>
      </header>

      {step !== "confirmation" && (
        <ol className="booking-stepper">
          {STEPS.map((entry, index) => (
            <li
              key={entry.key}
              className={index === stepIndex ? "active" : index < stepIndex ? "done" : ""}
            >
              <span className="booking-step-dot">{index < stepIndex ? "✓" : index + 1}</span>
              {entry.label}
            </li>
          ))}
        </ol>
      )}

      <section className="booking-card">
        {step === "location" && (
          <div className="booking-step">
            <h2>Choose a location</h2>
            <div className="booking-option-grid">
              {locations.map((location) => (
                <button key={location.id} className="booking-option-card" onClick={() => chooseLocation(location)}>
                  <strong>{location.name}</strong>
                  <small>
                    {location.city}
                    {location.city && location.state ? ", " : ""}
                    {location.state}
                  </small>
                </button>
              ))}
              {locations.length === 0 && <p className="muted">No locations are currently open for online booking.</p>}
            </div>
          </div>
        )}

        {step === "service" && (
          <div className="booking-step">
            <h2>Choose a service</h2>
            <div className="booking-option-grid">
              {appointmentTypes.map((appointmentType) => (
                <button
                  key={appointmentType.id}
                  className="booking-option-card"
                  onClick={() => chooseAppointmentType(appointmentType)}
                >
                  <strong>{appointmentType.name}</strong>
                  {appointmentType.description && <p>{appointmentType.description}</p>}
                  <small>
                    {appointmentType.durationMinutes} min
                    {appointmentType.price !== null ? ` · $${appointmentType.price.toFixed(2)}` : ""}
                    {appointmentType.requiresNewPatient ? " · New patients" : ""}
                  </small>
                </button>
              ))}
              {appointmentTypes.length === 0 && (
                <p className="muted">No services are available for online booking at this location.</p>
              )}
            </div>
            <button className="secondary-button booking-back" onClick={() => goTo("location")}>
              Back
            </button>
          </div>
        )}

        {step === "provider" && (
          <div className="booking-step">
            <h2>Choose a therapist</h2>
            <div className="booking-option-grid">
              <button
                className="booking-option-card"
                onClick={() => chooseProvider(ANY_PROVIDER_ID)}
              >
                <strong>Any available therapist</strong>
                <small>See the soonest appointment with any qualified therapist</small>
              </button>
              {providers.map((provider) => (
                <button key={provider.id} className="booking-option-card" onClick={() => chooseProvider(provider.id)}>
                  <strong>
                    {provider.displayName}
                    {provider.credentials ? `, ${provider.credentials}` : ""}
                  </strong>
                  {provider.specialty && <small>{provider.specialty}</small>}
                  {provider.bio && <p>{provider.bio}</p>}
                </button>
              ))}
            </div>
            <button className="secondary-button booking-back" onClick={() => goTo("service")}>
              Back
            </button>
          </div>
        )}

        {step === "datetime" && (
          <div className="booking-step">
            <h2>Pick a date &amp; time</h2>
            <div className="booking-date-nav">
              <button className="secondary-button" onClick={() => setDate((current) => addDays(current, -1))} disabled={date <= todayIso()}>
                ← Earlier
              </button>
              <div className="booking-date-current">
                <strong>{formatDateHeading(date, timeZone)}</strong>
                <input type="date" value={date} min={todayIso()} onChange={(event) => setDate(event.target.value)} />
              </div>
              <button className="secondary-button" onClick={() => setDate((current) => addDays(current, 1))}>
                Later →
              </button>
            </div>

            {loadingSlots && <p className="muted">Loading available times…</p>}
            {!loadingSlots && availabilityGroups.every((entry) => entry.slots.length === 0) && (
              <p className="muted">No open times on this date. Try another day.</p>
            )}

            <div className="booking-slot-groups">
              {availabilityGroups.map((entry) => (
                <div key={entry.provider.id} className="booking-provider-slots">
                  {(selectedProviderId === ANY_PROVIDER_ID || availabilityGroups.length > 1) && (
                    <h3>{entry.provider.displayName}</h3>
                  )}
                  {groupSlotsByPeriod(entry, timeZone).map((group) => (
                    <div key={group.label} className="booking-slot-period">
                      <p className="booking-slot-period-label">{group.label}</p>
                      <div className="booking-slot-grid">
                        {group.slots.map((slot) => (
                          <button
                            key={slot.start}
                            className={
                              "booking-slot-chip" +
                              (selectedSlot?.start === slot.start && selectedSlot?.providerId === entry.provider.id
                                ? " selected"
                                : "")
                            }
                            onClick={() => chooseSlot(entry, slot.start, slot.end)}
                          >
                            {formatTime(slot.start, timeZone)}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>

            <div className="booking-step-actions">
              <button className="secondary-button" onClick={() => goTo("provider")}>
                Back
              </button>
              <button className="primary-button" disabled={!selectedSlot} onClick={() => goTo("info")}>
                Continue
              </button>
            </div>
          </div>
        )}

        {step === "info" && (
          <div className="booking-step">
            <h2>Your information</h2>
            <div className="booking-patient-toggle">
              <button
                className={isNewPatient ? "active" : ""}
                onClick={() => setIsNewPatient(true)}
                type="button"
              >
                New patient
              </button>
              <button
                className={!isNewPatient ? "active" : ""}
                onClick={() => setIsNewPatient(false)}
                type="button"
              >
                Returning patient
              </button>
            </div>
            <form className="stack-form" onSubmit={handleInfoSubmit}>
              <div className="field-grid">
                <label>
                  <span>First name</span>
                  <input value={firstName} onChange={(event) => setFirstName(event.target.value)} required />
                </label>
                <label>
                  <span>Last name</span>
                  <input value={lastName} onChange={(event) => setLastName(event.target.value)} required />
                </label>
              </div>
              <div className="field-grid">
                <label>
                  <span>Date of birth</span>
                  <input type="date" value={dateOfBirth} onChange={(event) => setDateOfBirth(event.target.value)} required />
                </label>
                <label>
                  <span>Phone</span>
                  <input type="tel" value={phone} onChange={(event) => setPhone(event.target.value)} />
                </label>
              </div>
              <label>
                <span>Email</span>
                <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
              </label>
              <label>
                <span>Reason for visit (optional)</span>
                <textarea value={reasonForVisit} onChange={(event) => setReasonForVisit(event.target.value)} />
              </label>
              {infoError && <p className="form-error" role="alert">{infoError}</p>}
              <div className="booking-step-actions">
                <button className="secondary-button" type="button" onClick={() => goTo("datetime")}>
                  Back
                </button>
                <button className="primary-button" type="submit">
                  Continue
                </button>
              </div>
            </form>
          </div>
        )}

        {step === "review" && selectedLocation && selectedAppointmentType && selectedSlot && (
          <div className="booking-step">
            <h2>Confirm your appointment</h2>
            <dl className="booking-review-list">
              <div>
                <dt>Location</dt>
                <dd>{selectedLocation.name}</dd>
              </div>
              <div>
                <dt>Service</dt>
                <dd>{selectedAppointmentType.name}</dd>
              </div>
              <div>
                <dt>Therapist</dt>
                <dd>{selectedSlot.providerName}</dd>
              </div>
              <div>
                <dt>Date &amp; time</dt>
                <dd>
                  {formatDateHeading(date, timeZone)} at {formatTime(selectedSlot.start, timeZone)}
                </dd>
              </div>
              <div>
                <dt>Patient</dt>
                <dd>
                  {firstName} {lastName} ({isNewPatient ? "New patient" : "Returning patient"})
                </dd>
              </div>
            </dl>
            {submitError && <p className="form-error" role="alert">{submitError}</p>}
            <div className="booking-step-actions">
              <button className="secondary-button" onClick={() => goTo("info")} disabled={submitting}>
                Back
              </button>
              <button className="primary-button" onClick={() => void confirmBooking()} disabled={submitting}>
                {submitting ? "Booking…" : "Confirm booking"}
              </button>
            </div>
          </div>
        )}

        {step === "confirmation" && confirmation && (
          <div className="booking-step booking-confirmation">
            <div className="booking-confirmation-mark" aria-hidden="true">✓</div>
            <h2>You're booked!</h2>
            <p className="booking-confirmation-number">Confirmation #{confirmation.confirmationNumber}</p>
            <dl className="booking-review-list">
              <div>
                <dt>Provider</dt>
                <dd>{confirmation.appointment.provider}</dd>
              </div>
              <div>
                <dt>Location</dt>
                <dd>{confirmation.appointment.location}</dd>
              </div>
              <div>
                <dt>Service</dt>
                <dd>{confirmation.appointment.appointmentType}</dd>
              </div>
              <div>
                <dt>Date &amp; time</dt>
                <dd>
                  {formatDateHeading(confirmation.appointment.startsAt.slice(0, 10), timeZone)} at{" "}
                  {formatTime(confirmation.appointment.startsAt, timeZone)}
                </dd>
              </div>
            </dl>
            <p className="muted">A member of the {organization.name} team may follow up to confirm details.</p>
          </div>
        )}
      </section>
    </main>
  );
}
