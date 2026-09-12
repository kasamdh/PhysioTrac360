import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { MobileCareRequestPayload } from "../api/client";
import type {
  Appointment,
  HomeVisitAvailability,
  MobileCareAssignment,
  MobileCareDashboardData,
  MobileCareOfferPreview,
  MobileCarePersistedMatch,
  MobileCareProviderMatch,
  MobileCareRequest,
  MobileCareServiceArea,
  MobileCareStatusHistoryEntry,
  Patient,
  WorkspaceUser,
} from "../api/types";
import { StartDocumentationDialog } from "./documentation/StartDocumentationDialog";
import { formatDate, formatTime } from "../lib/format";

const WEEKDAYS = [
  { value: 0, label: "Monday" },
  { value: 1, label: "Tuesday" },
  { value: 2, label: "Wednesday" },
  { value: 3, label: "Thursday" },
  { value: 4, label: "Friday" },
  { value: 5, label: "Saturday" },
  { value: 6, label: "Sunday" },
];

const REQUESTED_SERVICE_OPTIONS = [
  { value: "evaluation", label: "Initial evaluation" },
  { value: "follow_up", label: "Follow-up visit" },
  { value: "progress", label: "Progress visit" },
  { value: "discharge", label: "Discharge visit" },
];

const TIME_WINDOW_OPTIONS = [
  { value: "", label: "No preference" },
  { value: "morning", label: "Morning (8am–12pm)" },
  { value: "afternoon", label: "Afternoon (12pm–5pm)" },
  { value: "evening", label: "Evening (5pm–9pm)" },
  { value: "any", label: "Any time" },
];

const GENDER_PREFERENCE_OPTIONS = [
  { value: "no_preference", label: "No preference" },
  { value: "male", label: "Male" },
  { value: "female", label: "Female" },
];

const PAYMENT_METHOD_OPTIONS = [
  { value: "insurance", label: "Insurance" },
  { value: "self_pay", label: "Self-pay" },
];

function requestMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

/** Opens directions to `address` in whichever map vendor the backend
 * chooses (care/mapping.py's get_directions_service()) — this component
 * never builds a maps.google.com/etc. URL itself, so switching vendors
 * later needs no frontend change. Opens a blank tab synchronously on
 * click (before the fetch resolves) so browsers don't treat the
 * subsequent redirect as an unrequested popup. */
function DirectionsButton({ address }: { address: string }) {
  const [busy, setBusy] = useState(false);

  async function openDirections() {
    setBusy(true);
    const popup = window.open("", "_blank");
    try {
      const result = await api.mobileCareDirections(address);
      if (result.available && result.url && popup) {
        popup.location.href = result.url;
      } else {
        popup?.close();
      }
    } catch {
      popup?.close();
    } finally {
      setBusy(false);
    }
  }

  return (
    <button className="text-action" type="button" onClick={() => void openDirections()} disabled={busy}>
      Directions
    </button>
  );
}

const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: "", label: "Open" },
  { value: "pending", label: "Pending" },
  { value: "matched", label: "Matched" },
  { value: "scheduled", label: "Scheduled" },
  { value: "declined", label: "Declined" },
  { value: "cancelled", label: "Cancelled" },
];

type Tab = "home" | "requests" | "offers" | "availability" | "service-area";

export function MobileCarePage({ user }: { user: WorkspaceUser }) {
  const [tab, setTab] = useState<Tab>("home");
  return (
    <div className="page-content">
      <header className="page-header">
        <div>
          <p className="eyebrow">Mobile & in-home care</p>
          <h1>Mobile Care</h1>
          <p>Review requests, match a provider, schedule visits, and manage provider availability.</p>
        </div>
      </header>
      <nav className="client-detail-tabs" aria-label="Mobile care sections">
        <button className={tab === "home" ? "active" : ""} onClick={() => setTab("home")}>Home</button>
        <button className={tab === "requests" ? "active" : ""} onClick={() => setTab("requests")}>Requests</button>
        <button className={tab === "offers" ? "active" : ""} onClick={() => setTab("offers")}>Visit Offers</button>
        <button className={tab === "availability" ? "active" : ""} onClick={() => setTab("availability")}>Provider Availability</button>
        <button className={tab === "service-area" ? "active" : ""} onClick={() => setTab("service-area")}>Service Area</button>
      </nav>
      {tab === "home" && <MobileCareHomeTab onNavigate={setTab} />}
      {tab === "requests" && <RequestsTab user={user} />}
      {tab === "offers" && <VisitOffersTab />}
      {tab === "availability" && <ProviderAvailabilityTab user={user} />}
      {tab === "service-area" && <ServiceAreaTab user={user} />}
    </div>
  );
}

/** "Mobile Care Home" — the landing page for the whole Mobile Care area:
 * six at-a-glance metric cards plus the four sections a coordinator works
 * from all day. Reuses the exact same metric-card/content-grid/surface-card
 * primitives the platform DashboardPage already uses — deliberately no new
 * design system, just this module's own data behind the same visual
 * language, which also gives it the same responsive breakpoints for free.
 * `onNavigate` switches this page's own tabs; "View care episode" leaves
 * Mobile Care for the top-level Patients page, since there's no cross-page
 * deep link straight into one patient's chart today. Role-based visibility
 * (Super Admin never reaches this page; Patient gets the separate portal
 * view; Org Admin/PT/PTA/Front Desk all land here) is enforced by
 * App.tsx's nav gate and, authoritatively, by the backend's
 * organization_or_error(roles=SCHEDULING_ROLES) on every endpoint this
 * page calls — never only here in the UI. */
function MobileCareHomeTab({ onNavigate }: { onNavigate: (tab: Tab) => void }) {
  const [data, setData] = useState<MobileCareDashboardData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api.mobileCareDashboard()
      .then((payload) => { if (active) setData(payload); })
      .catch((requestError) => { if (active) setError(requestMessage(requestError, "Unable to load the Mobile Care dashboard.")); });
    return () => { active = false; };
  }, []);

  if (error) {
    return <p className="form-error" role="alert">{error}</p>;
  }
  if (!data) {
    return <p className="page-loading" aria-live="polite">Loading Mobile Care…</p>;
  }

  const cards: { icon: string; value: number; label: string; tone: string; onClick: () => void }[] = [
    { icon: "⌂", value: data.cardCounts.todaysHomeVisits, label: "Today's home visits", tone: "crimson", onClick: () => onNavigate("requests") },
    { icon: "⏳", value: data.cardCounts.pendingRequests, label: "Pending requests", tone: "amber", onClick: () => onNavigate("requests") },
    { icon: "✉", value: data.cardCounts.providerOffers, label: "Provider offers", tone: "purple", onClick: () => onNavigate("offers") },
    { icon: "❤", value: data.cardCounts.activeCareEpisodes, label: "Active care episodes", tone: "green", onClick: () => onNavigate("requests") },
    { icon: "⚠", value: data.cardCounts.visitsNeedingAssignment, label: "Visits needing assignment", tone: "amber", onClick: () => onNavigate("requests") },
    { icon: "⚑", value: data.cardCounts.licenseProviderIssues, label: "License/provider issues", tone: "crimson", onClick: () => onNavigate("availability") },
  ];

  return (
    <>
      <section className="metric-grid" aria-label="Mobile Care at a glance">
        {cards.map((card) => (
          <button
            key={card.label}
            type="button"
            className="metric-card"
            style={{ font: "inherit", textAlign: "left", width: "100%" }}
            onClick={card.onClick}
          >
            <span className={`metric-icon ${card.tone}`}>{card.icon}</span>
            <span><strong>{card.value}</strong><small>{card.label}</small></span>
          </button>
        ))}
      </section>

      <div className="button-row">
        <button className="primary-button" type="button" onClick={() => onNavigate("requests")}>+ New Service Request</button>
      </div>

      <section className="content-grid">
        <article className="surface-card">
          <header className="card-heading"><div><p className="eyebrow">In-home PT</p><h2>Pending service requests</h2></div></header>
          {data.pendingRequests.length ? (
            <ul className="compact-list">
              {data.pendingRequests.map((entry) => (
                <li key={entry.id}>
                  <span><strong>{entry.patient.fullName}</strong><small>{entry.city}, {entry.state} · from {formatDate(entry.earliestDate)}</small></span>
                  <button className="text-action" type="button" onClick={() => onNavigate("requests")}>Match provider</button>
                </li>
              ))}
            </ul>
          ) : <p className="empty-copy positive">No open requests right now.</p>}
        </article>

        <article className="surface-card">
          <header className="card-heading"><div><p className="eyebrow">Today</p><h2>Today's home visits</h2></div></header>
          {data.todaysHomeVisits.length ? (
            <ul className="appointment-list">
              {data.todaysHomeVisits.map((visit) => (
                <li key={visit.id}>
                  <time>{formatTime(visit.startsAt)}</time>
                  <span><strong>{visit.patient.fullName}</strong><small>{visit.kindLabel}</small></span>
                  <span className={`status-pill ${visit.status}`}>{visit.statusLabel}</span>
                </li>
              ))}
            </ul>
          ) : <p className="empty-copy">No home visits scheduled today.</p>}
        </article>
      </section>

      <section className="content-grid">
        <article className="surface-card">
          <header className="card-heading"><div><p className="eyebrow">Needs a provider</p><h2>Unassigned requests</h2></div></header>
          {data.unassignedRequests.length ? (
            <ul className="compact-list">
              {data.unassignedRequests.map((entry) => (
                <li key={entry.id}>
                  <span><strong>{entry.patient.fullName}</strong><small>{entry.zipCode} · from {formatDate(entry.earliestDate)}</small></span>
                  <button className="text-action" type="button" onClick={() => onNavigate("requests")}>Assign provider</button>
                </li>
              ))}
            </ul>
          ) : <p className="empty-copy positive">Every open request has a provider assigned.</p>}
        </article>

        <article className="surface-card">
          <header className="card-heading"><div><p className="eyebrow">Continuity</p><h2>Active care episodes</h2></div></header>
          {data.activeCareEpisodes.length ? (
            <ul className="compact-list">
              {data.activeCareEpisodes.map((episode) => (
                <li key={episode.id}>
                  <span>
                    <strong>{episode.primaryTherapistName || "Unassigned PT"}</strong>
                    <small>{episode.condition || episode.diagnosis || "Care episode"} · {episode.visitsCompleted}{episode.expectedVisitCount ? `/${episode.expectedVisitCount}` : ""} visits</small>
                  </span>
                  <button className="text-action" type="button" onClick={() => { window.location.hash = "patients"; }}>View care episode</button>
                </li>
              ))}
            </ul>
          ) : <p className="empty-copy">No active mobile care episodes.</p>}
        </article>
      </section>
    </>
  );
}

/** Staff review queue for in-home PT requests: preview which providers cover
 * the visit ZIP, assign one, then convert the request into a real home-visit
 * appointment. Mirrors the staff-facing half of WaitlistPanel, but as a full
 * page rather than a collapsible panel since matching/scheduling is a
 * multi-step workflow per request. */
function RequestsTab({ user }: { user: WorkspaceUser }) {
  const [statusFilter, setStatusFilter] = useState("");
  const [requests, setRequests] = useState<MobileCareRequest[] | null>(null);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [matches, setMatches] = useState<MobileCareProviderMatch[] | null>(null);
  const [matchesError, setMatchesError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [scheduleTarget, setScheduleTarget] = useState<MobileCareRequest | null>(null);
  const [travelChargeTarget, setTravelChargeTarget] = useState<MobileCareRequest | null>(null);
  const [offersExpandedId, setOffersExpandedId] = useState<string | null>(null);
  const [offers, setOffers] = useState<MobileCarePersistedMatch[] | null>(null);
  const [offersError, setOffersError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<MobileCareRequest | null>(null);
  const [cancelTarget, setCancelTarget] = useState<MobileCareRequest | null>(null);
  const [historyExpandedId, setHistoryExpandedId] = useState<string | null>(null);
  const [history, setHistory] = useState<MobileCareStatusHistoryEntry[] | null>(null);
  const [historyError, setHistoryError] = useState("");

  async function load() {
    try {
      setRequests((await api.mobileCareRequestList(statusFilter || undefined)).requests);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load in-home PT requests."));
    }
  }

  useEffect(() => {
    setRequests(null);
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  async function viewMatches(request: MobileCareRequest) {
    if (expandedId === request.id) {
      setExpandedId(null);
      setMatches(null);
      return;
    }
    setExpandedId(request.id);
    setMatches(null);
    setMatchesError("");
    try {
      setMatches((await api.mobileCareRequestMatches(request.id)).providers);
    } catch (requestError) {
      setMatchesError(requestMessage(requestError, "Unable to load matching providers."));
    }
  }

  async function findMatches(requestId: string) {
    setBusyId(requestId);
    setError("");
    try {
      await api.mobileCareGenerateMatches(requestId);
      setOffersExpandedId(requestId);
      setOffers((await api.mobileCareProviderMatches(requestId)).matches);
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to find matching providers."));
    } finally {
      setBusyId(null);
    }
  }

  async function viewOffers(request: MobileCareRequest) {
    if (offersExpandedId === request.id) {
      setOffersExpandedId(null);
      setOffers(null);
      return;
    }
    setOffersExpandedId(request.id);
    setOffers(null);
    setOffersError("");
    try {
      setOffers((await api.mobileCareProviderMatches(request.id)).matches);
    } catch (requestError) {
      setOffersError(requestMessage(requestError, "Unable to load ranked candidates."));
    }
  }

  async function offerMatch(matchId: string, requestId: string) {
    setBusyId(matchId);
    setOffersError("");
    try {
      await api.mobileCareOfferMatch(matchId);
      setOffers((await api.mobileCareProviderMatches(requestId)).matches);
    } catch (requestError) {
      setOffersError(requestMessage(requestError, "Unable to offer this candidate."));
    } finally {
      setBusyId(null);
    }
  }

  async function matchProvider(requestId: string, providerId: string) {
    setBusyId(requestId);
    setError("");
    try {
      await api.mobileCareRequestMatch(requestId, providerId);
      setExpandedId(null);
      setMatches(null);
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to match this provider."));
    } finally {
      setBusyId(null);
    }
  }

  async function decline(requestId: string) {
    setBusyId(requestId);
    setError("");
    try {
      await api.mobileCareRequestDecline(requestId);
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to decline this request."));
    } finally {
      setBusyId(null);
    }
  }

  async function addServiceCharge(requestId: string) {
    setBusyId(requestId);
    setError("");
    try {
      await api.mobileCareRequestAddServiceCharge(requestId);
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to add this charge — check that a home-visit price is configured for this visit type."));
    } finally {
      setBusyId(null);
    }
  }

  async function viewHistory(request: MobileCareRequest) {
    if (historyExpandedId === request.id) {
      setHistoryExpandedId(null);
      setHistory(null);
      return;
    }
    setHistoryExpandedId(request.id);
    setHistory(null);
    setHistoryError("");
    try {
      setHistory((await api.mobileCareRequestStatusHistory(request.id)).history);
    } catch (requestError) {
      setHistoryError(requestMessage(requestError, "Unable to load status history."));
    }
  }

  return (
    <>
      <TodaysHomeVisits />
      <MyAssignments />
      <MyHomeVisitQueue />

      <div className="card-heading">
        <div>
          <p className="eyebrow">In-home PT</p>
          <h2>Service requests</h2>
        </div>
        <button className="primary-button" type="button" onClick={() => setCreateOpen(true)}>
          + New Service Request
        </button>
      </div>

      <div className="button-row" role="tablist" aria-label="Filter by status">
        {STATUS_FILTERS.map((filter) => (
          <button
            key={filter.value}
            className={statusFilter === filter.value ? "primary-button" : "secondary-button"}
            type="button"
            onClick={() => setStatusFilter(filter.value)}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {error && <p className="form-error" role="alert">{error}</p>}

      {requests === null ? (
        <p className="empty-copy">Loading…</p>
      ) : requests.length === 0 ? (
        <p className="empty-copy">No requests in this view.</p>
      ) : (
        <div style={{ display: "grid", gap: ".75rem" }}>
          {requests.map((request) => (
            <section className="surface-card" key={request.id}>
              <header className="card-heading">
                <div>
                  <p className="eyebrow">{request.statusLabel} · {request.sourceLabel}</p>
                  <h2>{request.patient.fullName}</h2>
                  <p className="muted">
                    {request.addressLine1}{request.addressLine2 ? `, ${request.addressLine2}` : ""}, {request.city}, {request.state} {request.zipCode}
                  </p>
                  <p className="muted">
                    From {formatDate(request.earliestDate)}{request.latestDate ? ` to ${formatDate(request.latestDate)}` : ""}
                  </p>
                  <p className="muted">
                    {request.requestedServiceLabel || "Service not specified"}
                    {request.preferredTimeWindowLabel ? ` · ${request.preferredTimeWindowLabel}` : ""}
                    {" · "}{request.isNewPatient ? "New patient" : "Existing patient"}
                    {" · "}{request.paymentMethodLabel}
                    {request.providerGenderPreference !== "no_preference" ? ` · Prefers ${request.providerGenderPreferenceLabel.toLowerCase()} provider` : ""}
                  </p>
                  {request.primaryCondition && <p className="muted"><strong>Condition:</strong> {request.primaryCondition}</p>}
                  {request.specialtyRequested && <p className="muted"><strong>Specialty:</strong> {request.specialtyRequested}</p>}
                  {request.reasonForVisit && <p className="muted">{request.reasonForVisit}</p>}
                  {request.mobilityNotes && <p className="muted"><strong>Mobility/access:</strong> {request.mobilityNotes}</p>}
                  {request.homeAccessNotes && <p className="muted"><strong>Home access:</strong> {request.homeAccessNotes}</p>}
                  {request.notes && <p className="muted">{request.notes}</p>}
                  {request.preferredProviderName && <p><strong>Preferred provider:</strong> {request.preferredProviderName}</p>}
                  {request.matchedProviderName && <p><strong>Matched provider:</strong> {request.matchedProviderName}</p>}
                </div>
              </header>

              <div className="button-row">
                {request.canEdit && (
                  <button className="text-action" type="button" onClick={() => setEditTarget(request)}>
                    Edit
                  </button>
                )}
                {request.canCancel && (
                  <button className="text-action" type="button" onClick={() => setCancelTarget(request)}>
                    Cancel request
                  </button>
                )}
                <button className="text-action" type="button" onClick={() => void viewHistory(request)}>
                  {historyExpandedId === request.id ? "Hide status history" : "View status history"}
                </button>
              </div>

              {historyExpandedId === request.id && (
                <div className="compact-subsection">
                  {historyError && <p className="form-error" role="alert">{historyError}</p>}
                  {history === null && !historyError && <p className="empty-copy">Loading status history…</p>}
                  {history !== null && history.length === 0 && <p className="empty-copy">No history yet.</p>}
                  {history !== null && history.length > 0 && (
                    <ul className="summary-list">
                      {history.map((event) => (
                        <li key={event.id}>
                          <span>
                            <strong>{event.action.replace("mobile_care_request.", "").replace(/_/g, " ")}</strong>
                            <small>{event.actorName || "System"} · {formatDate(event.createdAt)}</small>
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {(request.status === "pending" || request.status === "matched") && (
                <div className="button-row">
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => void viewMatches(request)}
                    disabled={busyId === request.id}
                  >
                    {expandedId === request.id ? "Hide matching providers" : "View matching providers"}
                  </button>
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => void findMatches(request.id)}
                    disabled={busyId === request.id}
                  >
                    Find ranked matches
                  </button>
                  <button
                    className="text-action"
                    type="button"
                    onClick={() => void viewOffers(request)}
                    disabled={busyId === request.id}
                  >
                    {offersExpandedId === request.id ? "Hide ranked candidates" : "View ranked candidates"}
                  </button>
                  {request.matchedProviderId && (
                    <button
                      className="primary-button"
                      type="button"
                      onClick={() => setScheduleTarget(request)}
                      disabled={busyId === request.id}
                    >
                      Schedule visit
                    </button>
                  )}
                  <button
                    className="text-action"
                    type="button"
                    onClick={() => void decline(request.id)}
                    disabled={busyId === request.id}
                  >
                    Decline
                  </button>
                </div>
              )}

              {request.status === "scheduled" && request.appointmentStatus === "completed" && user.capabilities.canManageBilling && (
                <div className="button-row">
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => void addServiceCharge(request.id)}
                    disabled={busyId === request.id}
                  >
                    Add service charge
                  </button>
                  <button className="secondary-button" type="button" onClick={() => setTravelChargeTarget(request)}>
                    Add travel charge
                  </button>
                </div>
              )}

              {expandedId === request.id && (
                <div className="compact-subsection">
                  {matchesError && <p className="form-error" role="alert">{matchesError}</p>}
                  {matches === null && !matchesError && <p className="empty-copy">Loading matching providers…</p>}
                  {matches !== null && matches.length === 0 && (
                    <p className="empty-copy">No provider's service area covers ZIP {request.zipCode} yet.</p>
                  )}
                  {matches !== null && matches.length > 0 && (
                    <ul className="summary-list">
                      {matches.map((provider) => (
                        <li key={provider.id}>
                          <span>
                            <strong>{provider.displayName}{provider.isContinuity ? " · Continuing provider" : ""}</strong>
                            <small>{provider.credentials}{provider.specialty ? ` · ${provider.specialty}` : ""}</small>
                          </span>
                          <button
                            className="secondary-button"
                            type="button"
                            onClick={() => void matchProvider(request.id, provider.id)}
                            disabled={busyId === request.id}
                          >
                            Match
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {offersExpandedId === request.id && (
                <div className="compact-subsection">
                  {offersError && <p className="form-error" role="alert">{offersError}</p>}
                  {offers === null && !offersError && <p className="empty-copy">Loading ranked candidates…</p>}
                  {offers !== null && offers.length === 0 && (
                    <p className="empty-copy">No candidates yet — use "Find ranked matches" to start.</p>
                  )}
                  {offers !== null && offers.length > 0 && (
                    <ul className="summary-list">
                      {offers.map((offer) => (
                        <li key={offer.id}>
                          <span>
                            <strong>#{offer.rank} {offer.providerName}{offer.score !== null ? ` · Score ${offer.score}` : ""}</strong>
                            <small>
                              {offer.statusLabel}{offer.declineReason ? ` — ${offer.declineReason}` : ""}
                              {offer.reasons.length > 0 ? ` · ${offer.reasons.join(", ")}` : ""}
                            </small>
                          </span>
                          {offer.status === "pending" && (
                            <button
                              className="secondary-button"
                              type="button"
                              onClick={() => void offerMatch(offer.id, request.id)}
                              disabled={busyId === offer.id}
                            >
                              Offer to provider
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </section>
          ))}
        </div>
      )}

      {scheduleTarget && (
        <ScheduleDialog
          request={scheduleTarget}
          onClose={() => setScheduleTarget(null)}
          onScheduled={async () => {
            setScheduleTarget(null);
            await load();
          }}
        />
      )}

      {travelChargeTarget && (
        <TravelChargeDialog
          request={travelChargeTarget}
          onClose={() => setTravelChargeTarget(null)}
          onAdded={async () => {
            setTravelChargeTarget(null);
            await load();
          }}
        />
      )}

      {createOpen && (
        <ServiceRequestFormDialog
          request={null}
          onClose={() => setCreateOpen(false)}
          onSaved={async () => {
            setCreateOpen(false);
            await load();
          }}
        />
      )}

      {editTarget && (
        <ServiceRequestFormDialog
          request={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={async () => {
            setEditTarget(null);
            await load();
          }}
        />
      )}

      {cancelTarget && (
        <CancelServiceRequestDialog
          request={cancelTarget}
          onClose={() => setCancelTarget(null)}
          onCancelled={async () => {
            setCancelTarget(null);
            await load();
          }}
        />
      )}
    </>
  );
}

const HOME_VISIT_ACTIONS: Record<string, { status: "checked_in" | "completed" | "no_show"; label: string; tone: "primary" | "text" }[]> = {
  scheduled: [
    { status: "checked_in", label: "Check in", tone: "primary" },
    { status: "no_show", label: "No-show", tone: "text" },
  ],
  checked_in: [
    { status: "completed", label: "Complete visit", tone: "primary" },
    { status: "no_show", label: "No-show", tone: "text" },
  ],
};

/** A provider's own pending visit offers from the accept-first matching
 * pipeline ("Mobile Care -> Visit Offers"). Deliberately shows only a
 * limited field set — general area, service type, estimated duration, and
 * so on — never the patient's name or exact street address, which only
 * become visible once the provider accepts (see MyAssignments, which reads
 * from the resulting HomeVisitAssignment instead). Most staff roles have no
 * Provider profile at all, so a 403 here is treated the same as "no
 * offers," not an error. */
function VisitOffersTab() {
  const [offers, setOffers] = useState<MobileCareOfferPreview[] | null>(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    try {
      setOffers((await api.mobileCareMyOffers()).offers);
    } catch {
      setOffers([]);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function respond(matchId: string, accept: boolean) {
    setBusyId(matchId);
    setError("");
    try {
      await api.mobileCareRespondToMatch(matchId, { accept });
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to respond to this offer."));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="surface-card">
      <header className="card-heading">
        <div>
          <p className="eyebrow">Awaiting your response</p>
          <h2>Visit offers</h2>
        </div>
      </header>
      <p className="muted">Patient name and exact address are shown only after you accept.</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      {offers === null ? (
        <p className="empty-copy">Loading…</p>
      ) : offers.length === 0 ? (
        <p className="empty-copy">No visit offers right now.</p>
      ) : (
        <ul className="summary-list">
          {offers.map((offer) => (
            <li key={offer.id}>
              <span>
                <strong>
                  {offer.serviceTypeLabel || "In-home visit"} · {formatDate(offer.requestedDate)}
                  {offer.preferredTimeWindowLabel ? ` · ${offer.preferredTimeWindowLabel}` : ""}
                </strong>
                <small>
                  {offer.generalArea} · ~{offer.estimatedDurationMinutes} min · {offer.patientStatus} · {offer.paymentMethodLabel}
                  {offer.specialtyRequested ? ` · ${offer.specialtyRequested}` : ""}
                  {offer.distanceLabel ? ` · ${offer.distanceLabel}` : ""}
                  {offer.expiresAt ? ` · Expires ${formatDate(offer.expiresAt)}` : ""}
                </small>
              </span>
              <span className="button-row">
                <button
                  className="primary-button"
                  type="button"
                  onClick={() => void respond(offer.id, true)}
                  disabled={busyId === offer.id}
                >
                  Accept
                </button>
                <button
                  className="text-action"
                  type="button"
                  onClick={() => void respond(offer.id, false)}
                  disabled={busyId === offer.id}
                >
                  Decline
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// The provider field-day state machine, mirroring
// ASSIGNMENT_STATUS_TRANSITIONS in care/mobile_care.py exactly — this map
// only drives which buttons render; the server independently rejects any
// transition not in that table, so this can never be the actual guard.
const ASSIGNMENT_ACTIONS: Record<string, { status: "en_route" | "arrived" | "in_progress" | "completed" | "cancelled"; label: string; tone: "primary" | "text" }[]> = {
  scheduled: [{ status: "en_route", label: "Start travel", tone: "primary" }, { status: "cancelled", label: "Cancel", tone: "text" }],
  en_route: [{ status: "arrived", label: "Arrived", tone: "primary" }, { status: "cancelled", label: "Cancel", tone: "text" }],
  arrived: [{ status: "in_progress", label: "Start visit", tone: "primary" }, { status: "cancelled", label: "Cancel", tone: "text" }],
  in_progress: [{ status: "completed", label: "Complete visit", tone: "primary" }, { status: "cancelled", label: "Cancel", tone: "text" }],
};

/** Provider Home Visit workflow — "Today's Home Visits": the accept-first
 * pipeline's field-day queue for today, manually stepped through
 * SCHEDULED -> EN_ROUTE -> ARRIVED -> IN_PROGRESS -> COMPLETED (or
 * CANCELLED from any of those) by explicit button press. No continuous GPS
 * tracking — every step is a deliberate action, and the server independently
 * enforces the same state machine (ASSIGNMENT_STATUS_TRANSITIONS), auditing
 * every transition, so this UI can't put a visit in an invalid state even
 * if a stale page allows clicking a stale button. */
function TodaysHomeVisits() {
  const [visits, setVisits] = useState<MobileCareAssignment[] | null>(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [documentationTarget, setDocumentationTarget] = useState<MobileCareAssignment | null>(null);

  async function load() {
    try {
      setVisits((await api.mobileCareTodaysHomeVisits()).visits);
    } catch {
      setVisits([]);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function updateStatus(visitId: string, status: "en_route" | "arrived" | "in_progress" | "completed" | "cancelled") {
    setBusyId(visitId);
    setError("");
    try {
      await api.mobileCareAssignmentStatusUpdate(visitId, status);
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to update this visit."));
    } finally {
      setBusyId(null);
    }
  }

  if (visits !== null && visits.length === 0) return null;

  return (
    <section className="surface-card">
      <header className="card-heading">
        <div>
          <p className="eyebrow">Field workflow</p>
          <h2>Today's Home Visits</h2>
        </div>
      </header>
      {error && <p className="form-error" role="alert">{error}</p>}
      {visits === null ? (
        <p className="empty-copy">Loading…</p>
      ) : (
        <ul className="summary-list">
          {visits.map((visit) => (
            <li key={visit.id}>
              <span>
                <strong>{visit.visitStartsAt ? formatTime(visit.visitStartsAt) : "—"} · {visit.patient.fullName}</strong>
                <small>
                  {visit.addressLine1}{visit.addressLine2 ? `, ${visit.addressLine2}` : ""}, {visit.city}, {visit.state} {visit.zipCode}
                  {visit.visitKindLabel ? ` · ${visit.visitKindLabel}` : ""}
                </small>
              </span>
              <span className="button-row">
                <span className={`status-pill ${visit.status}`}>{visit.statusLabel}</span>
                <button className="text-action" type="button" onClick={() => setExpandedId(expandedId === visit.id ? null : visit.id)}>
                  {expandedId === visit.id ? "Hide visit" : "View visit"}
                </button>
                <button className="text-action" type="button" onClick={() => setDocumentationTarget(visit)}>
                  Start Documentation
                </button>
                {(ASSIGNMENT_ACTIONS[visit.status] || []).map((action) => (
                  <button
                    key={action.status}
                    className={action.tone === "primary" ? "primary-button" : "text-action"}
                    type="button"
                    onClick={() => void updateStatus(visit.id, action.status)}
                    disabled={busyId === visit.id}
                  >
                    {action.label}
                  </button>
                ))}
              </span>
              {expandedId === visit.id && (
                <div className="compact-subsection">
                  <p className="muted">
                    {visit.visitKindLabel || "In-home visit"}
                    {visit.visitStartsAt && visit.visitEndsAt ? ` · ${formatTime(visit.visitStartsAt)} – ${formatTime(visit.visitEndsAt)}` : ""}
                  </p>
                  <DirectionsButton address={`${visit.addressLine1}, ${visit.city}, ${visit.state} ${visit.zipCode}`} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {documentationTarget && (
        <StartDocumentationDialog
          initialPatient={{ id: documentationTarget.patient.id, fullName: documentationTarget.patient.fullName }}
          appointmentId={documentationTarget.appointmentId || undefined}
          defaultNoteType="home_visit"
          onClose={() => setDocumentationTarget(null)}
          onCreated={(note) => {
            const patientId = documentationTarget.patient.id;
            setDocumentationTarget(null);
            window.location.hash = `documentation/${patientId}/${note.id}`;
          }}
        />
      )}
    </section>
  );
}

/** A provider's own accepted assignments from the accept-first pipeline —
 * accepted-but-not-scheduled ones get a Schedule action here; scheduled ones
 * get the same travel/visit-day actions as MyHomeVisitQueue below, just
 * against the HomeVisitAssignment record instead of the Appointment. */
function MyAssignments() {
  const [assignments, setAssignments] = useState<MobileCareAssignment[] | null>(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [scheduleTarget, setScheduleTarget] = useState<MobileCareAssignment | null>(null);
  const [delayTargetId, setDelayTargetId] = useState<string | null>(null);
  const [delayNote, setDelayNote] = useState("");

  async function load() {
    try {
      setAssignments((await api.mobileCareMyAssignments()).assignments);
    } catch {
      setAssignments([]);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function updateStatus(assignmentId: string, status: "en_route" | "arrived" | "in_progress" | "completed" | "cancelled") {
    setBusyId(assignmentId);
    setError("");
    try {
      await api.mobileCareAssignmentStatusUpdate(assignmentId, status);
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to update this assignment."));
    } finally {
      setBusyId(null);
    }
  }

  async function submitDelay(assignmentId: string) {
    try {
      await api.mobileCareLogDelay(assignmentId, delayNote.trim() || undefined);
      setDelayTargetId(null);
      setDelayNote("");
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to log a delay."));
    }
  }

  if (assignments !== null && assignments.length === 0) return null;

  return (
    <section className="surface-card">
      <header className="card-heading">
        <div>
          <p className="eyebrow">Accepted</p>
          <h2>My in-home PT assignments</h2>
        </div>
      </header>
      {error && <p className="form-error" role="alert">{error}</p>}
      {assignments === null ? (
        <p className="empty-copy">Loading…</p>
      ) : (
        <ul className="summary-list">
          {assignments.map((assignment) => (
            <li key={assignment.id}>
              <span>
                <strong>{assignment.patient.fullName} · {assignment.statusLabel}</strong>
                <small>{assignment.addressLine1}{assignment.addressLine2 ? `, ${assignment.addressLine2}` : ""}, {assignment.city}, {assignment.state} {assignment.zipCode}</small>
              </span>
              <span className="button-row">
                {!assignment.appointmentId && assignment.status === "accepted" && (
                  <button className="primary-button" type="button" onClick={() => setScheduleTarget(assignment)}>
                    Schedule
                  </button>
                )}
                {assignment.status === "en_route" && (
                  <button className="text-action" type="button" onClick={() => setDelayTargetId(assignment.id)}>
                    Log delay
                  </button>
                )}
                {(ASSIGNMENT_ACTIONS[assignment.status] || []).map((action) => (
                  <button
                    key={action.status}
                    className={action.tone === "primary" ? "primary-button" : "text-action"}
                    type="button"
                    onClick={() => void updateStatus(assignment.id, action.status)}
                    disabled={busyId === assignment.id}
                  >
                    {action.label}
                  </button>
                ))}
              </span>
            </li>
          ))}
        </ul>
      )}

      {scheduleTarget && (
        <AssignmentScheduleDialog
          assignment={scheduleTarget}
          onClose={() => setScheduleTarget(null)}
          onScheduled={async () => {
            setScheduleTarget(null);
            await load();
          }}
        />
      )}

      {delayTargetId && (
        <div className="modal-backdrop" role="presentation">
          <section className="move-dialog" role="dialog" aria-modal="true" aria-labelledby="delay-dialog-title">
            <button className="dialog-close" onClick={() => setDelayTargetId(null)} aria-label="Close">×</button>
            <p className="eyebrow">Travel update</p>
            <h2 id="delay-dialog-title">Log a delay</h2>
            <div style={{ display: "grid", gap: ".85rem", marginTop: "1.25rem" }}>
              <label>
                Note (optional)
                <input value={delayNote} onChange={(event) => setDelayNote(event.target.value)} placeholder="e.g. traffic" />
              </label>
              <div className="button-row">
                <button className="secondary-button" type="button" onClick={() => setDelayTargetId(null)}>Cancel</button>
                <button className="primary-button" type="button" onClick={() => void submitDelay(delayTargetId)}>Log delay</button>
              </div>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}

function AssignmentScheduleDialog({
  assignment,
  onClose,
  onScheduled,
}: {
  assignment: MobileCareAssignment;
  onClose: () => void;
  onScheduled: () => Promise<void>;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [startsAt, setStartsAt] = useState(`${today}T09:00`);
  const [endsAt, setEndsAt] = useState(`${today}T09:45`);
  const [kind, setKind] = useState("follow_up");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.mobileCareScheduleAssignment(assignment.id, {
        startsAt: new Date(startsAt).toISOString(),
        endsAt: new Date(endsAt).toISOString(),
        kind,
      });
      await onScheduled();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to schedule this visit."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="move-dialog" role="dialog" aria-modal="true" aria-labelledby="assignment-schedule-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">×</button>
        <p className="eyebrow">Schedule home visit</p>
        <h2 id="assignment-schedule-title">{assignment.patient.fullName}</h2>
        <p className="muted">
          {assignment.addressLine1}{assignment.addressLine2 ? `, ${assignment.addressLine2}` : ""}, {assignment.city}, {assignment.state} {assignment.zipCode}
        </p>
        <form onSubmit={submit}>
          <div className="field-grid">
            <label>Start<input type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} required /></label>
            <label>End<input type="datetime-local" value={endsAt} onChange={(event) => setEndsAt(event.target.value)} required /></label>
          </div>
          <label>
            Visit type
            <select value={kind} onChange={(event) => setKind(event.target.value)}>
              <option value="evaluation">Initial evaluation</option>
              <option value="follow_up">Follow-up visit</option>
              <option value="progress">Progress visit</option>
              <option value="discharge">Discharge visit</option>
            </select>
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
            <button className="primary-button" type="submit" disabled={busy}>{busy ? "Scheduling…" : "Schedule visit"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}

/** "My" home visits for today, regardless of how they were booked (the
 * MobileCareRequest flow above, or the older direct home-visit checkbox in
 * SchedulePage/PatientWorkspace) — always scoped server-side to the calling
 * clinician, so this renders the same for every role without a filter UI. */
function MyHomeVisitQueue() {
  const [visits, setVisits] = useState<Appointment[] | null>(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    try {
      setVisits((await api.homeVisitQueue()).visits);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load today's home visits."));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function updateStatus(appointmentId: string, status: "checked_in" | "completed" | "no_show") {
    setBusyId(appointmentId);
    setError("");
    try {
      await api.homeVisitStatusUpdate(appointmentId, status);
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to update this visit."));
    } finally {
      setBusyId(null);
    }
  }

  if (visits !== null && visits.length === 0) return null;

  return (
    <section className="surface-card">
      <header className="card-heading">
        <div>
          <p className="eyebrow">Today</p>
          <h2>My home visits</h2>
        </div>
      </header>
      {error && <p className="form-error" role="alert">{error}</p>}
      {visits === null ? (
        <p className="empty-copy">Loading…</p>
      ) : (
        <ul className="summary-list">
          {visits.map((visit) => (
            <li key={visit.id}>
              <span>
                <strong>{formatTime(visit.startsAt)} · {visit.patient.fullName}</strong>
                <small>{visit.location || "Address on file"} · {visit.statusLabel}</small>
              </span>
              <span className="button-row">
                {visit.location && <DirectionsButton address={visit.location} />}
                {(HOME_VISIT_ACTIONS[visit.status] || []).map((action) => (
                  <button
                    key={action.status}
                    className={action.tone === "primary" ? "primary-button" : "text-action"}
                    type="button"
                    onClick={() => void updateStatus(visit.id, action.status)}
                    disabled={busyId === visit.id}
                  >
                    {action.label}
                  </button>
                ))}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ScheduleDialog({
  request,
  onClose,
  onScheduled,
}: {
  request: MobileCareRequest;
  onClose: () => void;
  onScheduled: () => Promise<void>;
}) {
  const today = request.earliestDate;
  const [startsAt, setStartsAt] = useState(`${today}T09:00`);
  const [endsAt, setEndsAt] = useState(`${today}T09:45`);
  const [kind, setKind] = useState("follow_up");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.mobileCareRequestSchedule(request.id, {
        startsAt: new Date(startsAt).toISOString(),
        endsAt: new Date(endsAt).toISOString(),
        kind,
      });
      await onScheduled();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to schedule this visit."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="move-dialog" role="dialog" aria-modal="true" aria-labelledby="mobile-care-schedule-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">×</button>
        <p className="eyebrow">Schedule home visit</p>
        <h2 id="mobile-care-schedule-title">{request.patient.fullName} — {request.matchedProviderName}</h2>
        <p className="muted">
          {request.addressLine1}{request.addressLine2 ? `, ${request.addressLine2}` : ""}, {request.city}, {request.state} {request.zipCode}
        </p>
        <form onSubmit={submit}>
          <div className="field-grid">
            <label>Start<input type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} required /></label>
            <label>End<input type="datetime-local" value={endsAt} onChange={(event) => setEndsAt(event.target.value)} required /></label>
          </div>
          <label>
            Visit type
            <select value={kind} onChange={(event) => setKind(event.target.value)}>
              <option value="evaluation">Initial evaluation</option>
              <option value="follow_up">Follow-up visit</option>
              <option value="progress">Progress visit</option>
              <option value="discharge">Discharge visit</option>
            </select>
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
            <button className="primary-button" type="submit" disabled={busy}>{busy ? "Scheduling…" : "Schedule visit"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}

function TravelChargeDialog({
  request,
  onClose,
  onAdded,
}: {
  request: MobileCareRequest;
  onClose: () => void;
  onAdded: () => Promise<void>;
}) {
  const [cptCode, setCptCode] = useState("");
  const [chargeAmount, setChargeAmount] = useState("");
  const [configuredLabel, setConfiguredLabel] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api
      .mobileCareRequestBillingEstimate(request.id)
      .then((result) => {
        if (!active) return;
        const { travelFeeLabel, travelFeeAmount } = result.estimate;
        setConfiguredLabel(travelFeeAmount ? `${travelFeeLabel} — $${travelFeeAmount}` : null);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [request.id]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.mobileCareRequestAddTravelCharge(request.id, {
        cptCode: cptCode || undefined,
        chargeAmount: chargeAmount || undefined,
      });
      await onAdded();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to add this charge."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="move-dialog" role="dialog" aria-modal="true" aria-labelledby="travel-charge-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">×</button>
        <p className="eyebrow">Billing</p>
        <h2 id="travel-charge-title">Add travel charge — {request.patient.fullName}</h2>
        <p className="empty-copy">
          {configuredLabel
            ? `Leave blank to use this organization's configured travel fee (${configuredLabel}).`
            : "This organization has no configured travel fee yet — enter a CPT code and amount to bill one for this visit."}
        </p>
        <form onSubmit={submit}>
          <div className="field-grid">
            <label>
              CPT/HCPCS code
              <input value={cptCode} onChange={(event) => setCptCode(event.target.value.toUpperCase())} maxLength={5} placeholder="e.g. 99082" />
            </label>
            <label>
              Amount ($)
              <input type="number" min="0" step="0.01" value={chargeAmount} onChange={(event) => setChargeAmount(event.target.value)} />
            </label>
          </div>
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
            <button className="primary-button" type="submit" disabled={busy}>{busy ? "Adding…" : "Add charge"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}

/** Create/edit a Patient Service Request. Create mode requires picking a
 * patient first (the create endpoint is patient-scoped); edit mode reuses
 * the same field set against an existing request and is only reachable
 * while `request.canEdit` is true (pre-assignment) — the backend enforces
 * that same rule independently. The visit address is always typed/edited
 * here as its own fields — "use existing patient address" is offered as a
 * one-time copy-in convenience from the chart's freeform address, not a
 * live link, so the request never duplicates or depends on chart data. */
function ServiceRequestFormDialog({
  request,
  onClose,
  onSaved,
}: {
  request: MobileCareRequest | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const isEdit = request !== null;
  const [patient, setPatient] = useState<{ id: string; fullName: string } | null>(
    request ? request.patient : null,
  );
  const [patientQuery, setPatientQuery] = useState("");
  const [patientResults, setPatientResults] = useState<Patient[]>([]);
  const [chartAddress, setChartAddress] = useState("");

  const [addressLine1, setAddressLine1] = useState(request?.addressLine1 || "");
  const [addressLine2, setAddressLine2] = useState(request?.addressLine2 || "");
  const [city, setCity] = useState(request?.city || "");
  const [state, setState] = useState(request?.state || "");
  const [zipCode, setZipCode] = useState(request?.zipCode || "");
  const [earliestDate, setEarliestDate] = useState(request?.earliestDate || new Date().toISOString().slice(0, 10));
  const [latestDate, setLatestDate] = useState(request?.latestDate || "");
  const [requestedService, setRequestedService] = useState(request?.requestedService || "");
  const [preferredTimeWindow, setPreferredTimeWindow] = useState(request?.preferredTimeWindow || "");
  const [reasonForVisit, setReasonForVisit] = useState(request?.reasonForVisit || "");
  const [primaryCondition, setPrimaryCondition] = useState(request?.primaryCondition || "");
  const [specialtyRequested, setSpecialtyRequested] = useState(request?.specialtyRequested || "");
  const [providerGenderPreference, setProviderGenderPreference] = useState(request?.providerGenderPreference || "no_preference");
  const [isNewPatient, setIsNewPatient] = useState(request?.isNewPatient ?? false);
  const [paymentMethod, setPaymentMethod] = useState(request?.paymentMethod || "insurance");
  const [mobilityNotes, setMobilityNotes] = useState(request?.mobilityNotes || "");
  const [homeAccessNotes, setHomeAccessNotes] = useState(request?.homeAccessNotes || "");
  const [notes, setNotes] = useState(request?.notes || "");
  const [preferredProviderId, setPreferredProviderId] = useState(request?.preferredProviderId || "");
  const [providers, setProviders] = useState<MobileCareProviderMatch[]>([]);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.mobileCareProviders().then((result) => setProviders(result.providers)).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (isEdit || !patient) {
      setChartAddress("");
      return;
    }
    let active = true;
    api.patient(patient.id).then((result) => {
      if (active) setChartAddress(result.patient.address || "");
    }).catch(() => undefined);
    return () => {
      active = false;
    };
  }, [isEdit, patient]);

  async function searchPatients(value: string) {
    setPatientQuery(value);
    if (value.trim().length < 2) {
      setPatientResults([]);
      return;
    }
    try {
      setPatientResults((await api.patients(value)).patients);
    } catch {
      setPatientResults([]);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!patient) return;
    setBusy(true);
    setError("");
    const body: Partial<MobileCareRequestPayload> = {
      addressLine1,
      addressLine2,
      city,
      state,
      zipCode,
      reasonForVisit,
      notes,
      earliestDate,
      latestDate: latestDate || null,
      requestedService,
      specialtyRequested,
      preferredTimeWindow,
      primaryCondition,
      providerGenderPreference,
      isNewPatient,
      paymentMethod,
      mobilityNotes,
      homeAccessNotes,
      preferredProviderId: preferredProviderId || null,
    };
    try {
      if (isEdit && request) {
        await api.mobileCareRequestUpdate(request.id, body);
      } else {
        await api.mobileCareRequestCreate(patient.id, body as MobileCareRequestPayload);
      }
      await onSaved();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to save this service request."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="move-dialog" role="dialog" aria-modal="true" aria-labelledby="service-request-form-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">×</button>
        <p className="eyebrow">In-home PT</p>
        <h2 id="service-request-form-title">{isEdit ? "Edit service request" : "New service request"}</h2>
        <form onSubmit={submit}>
          {!isEdit && (
            <label>
              Patient
              {patient ? (
                <div className="button-row" style={{ alignItems: "center" }}>
                  <strong>{patient.fullName}</strong>
                  <button type="button" className="text-action" onClick={() => { setPatient(null); setPatientResults([]); }}>
                    Change
                  </button>
                </div>
              ) : (
                <>
                  <input
                    value={patientQuery}
                    onChange={(event) => void searchPatients(event.target.value)}
                    placeholder="Search by name or MRN"
                  />
                  {patientResults.length > 0 && (
                    <ul className="summary-list">
                      {patientResults.map((candidate) => (
                        <li key={candidate.id}>
                          <button
                            type="button"
                            className="text-action"
                            onClick={() => { setPatient({ id: candidate.id, fullName: candidate.fullName }); setPatientResults([]); setPatientQuery(""); }}
                          >
                            {candidate.fullName} — MRN {candidate.medicalRecordNumber}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </label>
          )}

          {chartAddress && !isEdit && (
            <p className="muted">
              Chart address: {chartAddress}{" "}
              <button type="button" className="text-action" onClick={() => setAddressLine1(chartAddress)}>
                Use this address
              </button>
            </p>
          )}

          <label>
            Address line 1
            <input value={addressLine1} onChange={(event) => setAddressLine1(event.target.value)} required maxLength={200} />
          </label>
          <label>
            Address line 2 (optional)
            <input value={addressLine2} onChange={(event) => setAddressLine2(event.target.value)} maxLength={200} />
          </label>
          <div className="field-grid">
            <label>City<input value={city} onChange={(event) => setCity(event.target.value)} required maxLength={120} /></label>
            <label>State<input value={state} onChange={(event) => setState(event.target.value)} required maxLength={80} placeholder="NC" /></label>
            <label>ZIP<input value={zipCode} onChange={(event) => setZipCode(event.target.value)} required maxLength={5} /></label>
          </div>

          <div className="field-grid">
            <label>Preferred date<input type="date" value={earliestDate} onChange={(event) => setEarliestDate(event.target.value)} required /></label>
            <label>Latest date (optional)<input type="date" value={latestDate} onChange={(event) => setLatestDate(event.target.value)} /></label>
          </div>

          <div className="field-grid">
            <label>
              Requested service
              <select value={requestedService} onChange={(event) => setRequestedService(event.target.value)}>
                <option value="">Not specified</option>
                {REQUESTED_SERVICE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label>
              Preferred time window
              <select value={preferredTimeWindow} onChange={(event) => setPreferredTimeWindow(event.target.value)}>
                {TIME_WINDOW_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
          </div>

          <label>
            Reason for visit (optional)
            <input value={reasonForVisit} onChange={(event) => setReasonForVisit(event.target.value)} maxLength={240} />
          </label>
          <label>
            Primary condition (optional)
            <input value={primaryCondition} onChange={(event) => setPrimaryCondition(event.target.value)} maxLength={240} />
          </label>
          <label>
            Specialty requested (optional)
            <input value={specialtyRequested} onChange={(event) => setSpecialtyRequested(event.target.value)} maxLength={120} />
          </label>

          <div className="field-grid">
            <label>
              Preferred provider (optional)
              <select value={preferredProviderId} onChange={(event) => setPreferredProviderId(event.target.value)}>
                <option value="">No preference</option>
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id}>{provider.displayName}</option>
                ))}
              </select>
            </label>
            <label>
              Provider gender preference
              <select value={providerGenderPreference} onChange={(event) => setProviderGenderPreference(event.target.value)}>
                {GENDER_PREFERENCE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="field-grid">
            <label>
              New or existing patient
              <select value={isNewPatient ? "new" : "existing"} onChange={(event) => setIsNewPatient(event.target.value === "new")}>
                <option value="existing">Existing patient</option>
                <option value="new">New patient</option>
              </select>
            </label>
            <label>
              Insurance or self-pay
              <select value={paymentMethod} onChange={(event) => setPaymentMethod(event.target.value)}>
                {PAYMENT_METHOD_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
          </div>

          <label>
            Mobility / access notes (optional)
            <input value={mobilityNotes} onChange={(event) => setMobilityNotes(event.target.value)} maxLength={500} placeholder="e.g. uses a walker, second-floor apartment" />
          </label>
          <label>
            Home access notes (optional)
            <input value={homeAccessNotes} onChange={(event) => setHomeAccessNotes(event.target.value)} maxLength={500} placeholder="e.g. gate code, parking instructions" />
          </label>
          <label>
            Additional comments (optional)
            <input value={notes} onChange={(event) => setNotes(event.target.value)} maxLength={500} />
          </label>

          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
            <button className="primary-button" type="submit" disabled={busy || !patient}>
              {busy ? "Saving…" : isEdit ? "Save changes" : "Create request"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

function CancelServiceRequestDialog({
  request,
  onClose,
  onCancelled,
}: {
  request: MobileCareRequest;
  onClose: () => void;
  onCancelled: () => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await api.mobileCareRequestCancel(request.id, reason.trim() || undefined);
      await onCancelled();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to cancel this request."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="move-dialog" role="dialog" aria-modal="true" aria-labelledby="cancel-request-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">×</button>
        <p className="eyebrow">In-home PT</p>
        <h2 id="cancel-request-title">Cancel service request — {request.patient.fullName}</h2>
        <div style={{ display: "grid", gap: ".85rem", marginTop: "1.25rem" }}>
          <label>
            Reason (optional)
            <input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={240} />
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Keep request</button>
            <button className="primary-button" type="button" onClick={() => void confirm()} disabled={busy}>
              {busy ? "Cancelling…" : "Cancel request"}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

/** PT/PTA availability for in-home visits. A plain provider only ever sees
 * and manages their own rows (the backend enforces this regardless of what
 * this UI shows); admin/director additionally get a provider picker/filter
 * and may manage anyone's within the organization. */
function ProviderAvailabilityTab({ user }: { user: WorkspaceUser }) {
  const isAdmin = user.role === "admin" || user.role === "director";
  const [rows, setRows] = useState<HomeVisitAvailability[] | null>(null);
  const [providers, setProviders] = useState<MobileCareProviderMatch[]>([]);
  const [providerFilter, setProviderFilter] = useState("");
  const [error, setError] = useState("");
  const [formTarget, setFormTarget] = useState<HomeVisitAvailability | "new" | null>(null);

  async function load() {
    try {
      const result = await api.mobileCareAvailabilityList(providerFilter ? { providerId: providerFilter } : undefined);
      setRows(result.availability);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load provider availability."));
    }
  }

  useEffect(() => {
    void load();
    if (isAdmin) {
      api.mobileCareProviders().then((result) => setProviders(result.providers)).catch(() => undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerFilter]);

  async function toggleActive(row: HomeVisitAvailability) {
    setError("");
    try {
      if (row.isActive) {
        await api.deactivateMobileCareAvailability(row.id);
      } else {
        await api.updateMobileCareAvailability(row.id, { isActive: true });
      }
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to update this availability window."));
    }
  }

  return (
    <section className="surface-card">
      <div className="card-heading">
        <div>
          <p className="eyebrow">In-home visits</p>
          <h2>Provider availability</h2>
        </div>
        <button className="primary-button" onClick={() => setFormTarget("new")}>+ Add availability</button>
      </div>
      <p className="muted">When a PT/PTA is available (or explicitly not) for in-home visits — day, time, type, and optional region.</p>
      {isAdmin && (
        <label style={{ display: "block", maxWidth: "320px", marginBottom: "1rem" }}>
          <span>Provider</span>
          <select value={providerFilter} onChange={(event) => setProviderFilter(event.target.value)}>
            <option value="">All providers</option>
            {providers.map((provider) => (
              <option key={provider.id} value={provider.id}>{provider.displayName}</option>
            ))}
          </select>
        </label>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {isAdmin && <th>Provider</th>}
              <th>Day / Date</th>
              <th>Time</th>
              <th>Type</th>
              <th>Region</th>
              <th>Effective</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {(rows || []).map((row) => (
              <tr key={row.id}>
                {isAdmin && <td>{row.providerName}</td>}
                <td>
                  {row.isRecurring ? (
                    <strong>{row.dayOfWeekLabel} <small>(weekly)</small></strong>
                  ) : (
                    <strong>{row.specificDate ? formatDate(row.specificDate) : "—"} <small>(one-time)</small></strong>
                  )}
                </td>
                <td>{row.startTime} – {row.endTime}</td>
                <td>{row.availabilityTypeLabel}</td>
                <td>{row.serviceAreaName || "—"}</td>
                <td>
                  {row.effectiveFrom || row.effectiveUntil
                    ? `${row.effectiveFrom ? formatDate(row.effectiveFrom) : "…"} – ${row.effectiveUntil ? formatDate(row.effectiveUntil) : "…"}`
                    : "—"}
                </td>
                <td>{row.isActive ? "Active" : "Inactive"}</td>
                <td>
                  <button className="text-action" onClick={() => setFormTarget(row)}>Edit</button>{" "}
                  <button className="text-action" onClick={() => void toggleActive(row)}>{row.isActive ? "Deactivate" : "Reactivate"}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows === null && <p className="empty-copy">Loading…</p>}
      {rows !== null && rows.length === 0 && <p className="empty-copy">No availability windows configured yet.</p>}
      {formTarget && (
        <AvailabilityFormDialog
          availability={formTarget === "new" ? null : formTarget}
          isAdmin={isAdmin}
          providers={providers}
          onClose={() => setFormTarget(null)}
          onSaved={async () => {
            setFormTarget(null);
            await load();
          }}
        />
      )}
    </section>
  );
}

function AvailabilityFormDialog({
  availability,
  isAdmin,
  providers,
  onClose,
  onSaved,
}: {
  availability: HomeVisitAvailability | null;
  isAdmin: boolean;
  providers: MobileCareProviderMatch[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [providerId, setProviderId] = useState(availability?.providerId || providers[0]?.id || "");
  const [availabilityType, setAvailabilityType] = useState(availability?.availabilityType || "available");
  const [isRecurring, setIsRecurring] = useState(availability?.isRecurring ?? true);
  const [dayOfWeek, setDayOfWeek] = useState(availability?.dayOfWeek ?? 0);
  const [specificDate, setSpecificDate] = useState(availability?.specificDate || new Date().toISOString().slice(0, 10));
  const [startTime, setStartTime] = useState(availability?.startTime || "09:00");
  const [endTime, setEndTime] = useState(availability?.endTime || "17:00");
  const [serviceAreaId, setServiceAreaId] = useState(availability?.serviceAreaId || "");
  const [serviceAreas, setServiceAreas] = useState<MobileCareServiceArea[]>([]);
  const [effectiveFrom, setEffectiveFrom] = useState(availability?.effectiveFrom || "");
  const [effectiveUntil, setEffectiveUntil] = useState(availability?.effectiveUntil || "");
  const [notes, setNotes] = useState(availability?.notes || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.mobileCareServiceAreas().then((result) => setServiceAreas(result.serviceAreas)).catch(() => undefined);
  }, []);

  const availableServiceAreas = serviceAreas.filter((area) => !isAdmin || !providerId || area.providerId === providerId);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const body: Record<string, unknown> = {
      availabilityType,
      isRecurring,
      dayOfWeek: isRecurring ? dayOfWeek : null,
      specificDate: isRecurring ? null : specificDate,
      startTime,
      endTime,
      serviceAreaId: serviceAreaId || null,
      effectiveFrom: effectiveFrom || null,
      effectiveUntil: effectiveUntil || null,
      notes,
    };
    if (isAdmin && providerId) {
      body.providerId = providerId;
    }
    try {
      if (availability) {
        await api.updateMobileCareAvailability(availability.id, body);
      } else {
        await api.createMobileCareAvailability(body);
      }
      await onSaved();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to save this availability window."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="move-dialog" role="dialog" aria-modal="true" aria-labelledby="availability-form-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">×</button>
        <p className="eyebrow">In-home visits</p>
        <h2 id="availability-form-title">{availability ? "Edit availability" : "Add availability"}</h2>
        <form onSubmit={submit}>
          {isAdmin && (
            <label>
              Provider
              <select value={providerId} onChange={(event) => setProviderId(event.target.value)} required>
                <option value="" disabled>Select provider</option>
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id}>{provider.displayName}</option>
                ))}
              </select>
            </label>
          )}
          <div className="field-grid">
            <label>
              Availability type
              <select value={availabilityType} onChange={(event) => setAvailabilityType(event.target.value)}>
                <option value="available">Available</option>
                <option value="unavailable">Unavailable</option>
                <option value="blocked">Blocked</option>
              </select>
            </label>
            <label>
              Recurrence
              <select value={isRecurring ? "recurring" : "one_time"} onChange={(event) => setIsRecurring(event.target.value === "recurring")}>
                <option value="recurring">Recurring (weekly)</option>
                <option value="one_time">One-time</option>
              </select>
            </label>
          </div>
          {isRecurring ? (
            <label>
              Day of week
              <select value={dayOfWeek} onChange={(event) => setDayOfWeek(Number(event.target.value))}>
                {WEEKDAYS.map((day) => (
                  <option key={day.value} value={day.value}>{day.label}</option>
                ))}
              </select>
            </label>
          ) : (
            <label>
              Date
              <input type="date" value={specificDate} onChange={(event) => setSpecificDate(event.target.value)} required />
            </label>
          )}
          <div className="field-grid">
            <label>Start time<input type="time" value={startTime} onChange={(event) => setStartTime(event.target.value)} required /></label>
            <label>End time<input type="time" value={endTime} onChange={(event) => setEndTime(event.target.value)} required /></label>
          </div>
          <label>
            Region / service area (optional)
            <select value={serviceAreaId} onChange={(event) => setServiceAreaId(event.target.value)}>
              <option value="">No specific region</option>
              {availableServiceAreas.map((area) => (
                <option key={area.id} value={area.id}>{area.name}</option>
              ))}
            </select>
          </label>
          <div className="field-grid">
            <label>Effective from (optional)<input type="date" value={effectiveFrom} onChange={(event) => setEffectiveFrom(event.target.value)} /></label>
            <label>Effective until (optional)<input type="date" value={effectiveUntil} onChange={(event) => setEffectiveUntil(event.target.value)} /></label>
          </div>
          <label>
            Notes (optional)
            <input value={notes} onChange={(event) => setNotes(event.target.value)} maxLength={500} placeholder="e.g. evenings only, no weekends" />
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
            <button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}

/** Where a provider is willing to perform home visits: a primary ZIP,
 * optional city/state, and a configurable radius/max-travel-distance — no
 * map or actual radius geometry yet (see the component docstrings in
 * care/models.py's ServiceArea). Read is open to any scheduling-capable
 * role; add/edit/deactivate is admin/director only, matching the backend's
 * SERVICE_AREA_ADMIN_ROLES gate exactly. */
function ServiceAreaTab({ user }: { user: WorkspaceUser }) {
  const isAdmin = user.role === "admin" || user.role === "director";
  const [rows, setRows] = useState<MobileCareServiceArea[] | null>(null);
  const [providers, setProviders] = useState<MobileCareProviderMatch[]>([]);
  const [error, setError] = useState("");
  const [formTarget, setFormTarget] = useState<MobileCareServiceArea | "new" | null>(null);

  async function load() {
    try {
      setRows((await api.mobileCareServiceAreas()).serviceAreas);
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to load service areas."));
    }
  }

  useEffect(() => {
    void load();
    if (isAdmin) {
      api.mobileCareProviders().then((result) => setProviders(result.providers)).catch(() => undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function toggleActive(row: MobileCareServiceArea) {
    setError("");
    try {
      if (row.isActive) {
        await api.deactivateMobileCareServiceArea(row.id);
      } else {
        await api.updateMobileCareServiceArea(row.id, { isActive: true });
      }
      await load();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to update this service area."));
    }
  }

  return (
    <section className="surface-card">
      <div className="card-heading">
        <div>
          <p className="eyebrow">In-home visits</p>
          <h2>Service area</h2>
        </div>
        {isAdmin && <button className="primary-button" onClick={() => setFormTarget("new")}>+ Add service area</button>}
      </div>
      <p className="muted">
        Where each provider is willing to travel for in-home visits — ZIP, region, and radius. A provider must hold an
        active license for the area's state to be eligible; expired or suspended providers are flagged automatically.
      </p>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Provider</th>
              <th>ZIP</th>
              <th>City</th>
              <th>State</th>
              <th>Radius</th>
              <th>Status</th>
              {isAdmin && <th>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {(rows || []).map((row) => (
              <tr key={row.id}>
                <td><strong>{row.providerName}</strong>{row.name && <small>{row.name}</small>}</td>
                <td>{row.primaryZipCode || "—"}</td>
                <td>{row.city || "—"}</td>
                <td>{row.state || "—"}</td>
                <td>{row.radiusMiles ? `${row.radiusMiles} mi` : "—"}</td>
                <td>
                  {row.isActive ? "Active" : "Inactive"}
                  {row.isActive && !row.isEligible && (
                    <div><small className="form-error" style={{ margin: 0 }}>Not eligible{row.ineligibilityReason ? ` — ${row.ineligibilityReason}` : ""}</small></div>
                  )}
                </td>
                {isAdmin && (
                  <td>
                    <button className="text-action" onClick={() => setFormTarget(row)}>Edit</button>{" "}
                    <button className="text-action" onClick={() => void toggleActive(row)}>{row.isActive ? "Deactivate" : "Reactivate"}</button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows === null && <p className="empty-copy">Loading…</p>}
      {rows !== null && rows.length === 0 && <p className="empty-copy">No service areas configured yet.</p>}
      {formTarget && (
        <ServiceAreaFormDialog
          serviceArea={formTarget === "new" ? null : formTarget}
          providers={providers}
          onClose={() => setFormTarget(null)}
          onSaved={async () => {
            setFormTarget(null);
            await load();
          }}
        />
      )}
    </section>
  );
}

function ServiceAreaFormDialog({
  serviceArea,
  providers,
  onClose,
  onSaved,
}: {
  serviceArea: MobileCareServiceArea | null;
  providers: MobileCareProviderMatch[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [providerId, setProviderId] = useState(serviceArea?.providerId || providers[0]?.id || "");
  const [name, setName] = useState(serviceArea?.name || "");
  const [primaryZipCode, setPrimaryZipCode] = useState(serviceArea?.primaryZipCode || "");
  const [city, setCity] = useState(serviceArea?.city || "");
  const [state, setState] = useState(serviceArea?.state || "");
  const [radiusMiles, setRadiusMiles] = useState(serviceArea?.radiusMiles ? String(serviceArea.radiusMiles) : "");
  const [maxTravelDistanceMiles, setMaxTravelDistanceMiles] = useState(
    serviceArea?.maxTravelDistanceMiles ? String(serviceArea.maxTravelDistanceMiles) : "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const body: Record<string, unknown> = {
      name,
      primaryZipCode: primaryZipCode || null,
      city: city || null,
      state: state || null,
      radiusMiles: radiusMiles ? Number(radiusMiles) : null,
      maxTravelDistanceMiles: maxTravelDistanceMiles ? Number(maxTravelDistanceMiles) : null,
    };
    try {
      if (serviceArea) {
        await api.updateMobileCareServiceArea(serviceArea.id, body);
      } else {
        await api.createMobileCareServiceArea({ ...body, providerId } as { name: string; providerId: string });
      }
      await onSaved();
    } catch (requestError) {
      setError(requestMessage(requestError, "Unable to save this service area."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="move-dialog" role="dialog" aria-modal="true" aria-labelledby="service-area-form-title">
        <button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">×</button>
        <p className="eyebrow">In-home visits</p>
        <h2 id="service-area-form-title">{serviceArea ? "Edit service area" : "Add service area"}</h2>
        <form onSubmit={submit}>
          {!serviceArea && (
            <label>
              Provider
              <select value={providerId} onChange={(event) => setProviderId(event.target.value)} required>
                <option value="" disabled>Select provider</option>
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id}>{provider.displayName}</option>
                ))}
              </select>
            </label>
          )}
          <label>
            Name
            <input value={name} onChange={(event) => setName(event.target.value)} required placeholder="e.g. Primary coverage" maxLength={120} />
          </label>
          <div className="field-grid">
            <label>Primary ZIP<input value={primaryZipCode} onChange={(event) => setPrimaryZipCode(event.target.value)} placeholder="27526" maxLength={5} /></label>
            <label>Service radius (miles)<input type="number" min="1" value={radiusMiles} onChange={(event) => setRadiusMiles(event.target.value)} placeholder="15" /></label>
          </div>
          <div className="field-grid">
            <label>City (optional)<input value={city} onChange={(event) => setCity(event.target.value)} maxLength={120} /></label>
            <label>State (optional)<input value={state} onChange={(event) => setState(event.target.value)} placeholder="NC" maxLength={80} /></label>
          </div>
          <label>
            Maximum travel distance (miles, optional)
            <input type="number" min="1" value={maxTravelDistanceMiles} onChange={(event) => setMaxTravelDistanceMiles(event.target.value)} />
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button>
            <button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
