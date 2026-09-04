import { DragEvent, FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";

import { ApiError, api } from "../api/client";
import type { Appointment, Patient, ScheduleData, WorkspaceUser } from "../api/types";
import { formatDate, formatTime, monthLabel } from "../lib/format";

type ViewMode = "day" | "week" | "workWeek" | "month";

function localMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function shiftMonth(month: string, amount: number) {
  const [year, value] = month.split("-").map(Number);
  const date = new Date(year, value - 1 + amount, 1, 12);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function addDays(dateValue: string, amount: number) {
  const date = new Date(`${dateValue}T12:00:00`);
  date.setDate(date.getDate() + amount);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function startOfWeek(dateValue: string) {
  const date = new Date(`${dateValue}T12:00:00`);
  const dow = date.getDay();
  const diff = dow === 0 ? -6 : 1 - dow;
  date.setDate(date.getDate() + diff);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function dateRange(start: string, end: string) {
  const result: string[] = [];
  const cursor = new Date(`${start}T12:00:00`);
  const last = new Date(`${end}T12:00:00`);
  while (cursor <= last) {
    result.push(`${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, "0")}-${String(cursor.getDate()).padStart(2, "0")}`);
    cursor.setDate(cursor.getDate() + 1);
  }
  return result;
}

function visibleDaysFor(mode: ViewMode, selectedDate: string, monthRange?: { start: string; end: string }) {
  if (mode === "day") return [selectedDate];
  if (mode === "week") {
    const start = startOfWeek(selectedDate);
    return Array.from({ length: 7 }, (_, index) => addDays(start, index));
  }
  if (mode === "workWeek") {
    const start = startOfWeek(selectedDate);
    return Array.from({ length: 5 }, (_, index) => addDays(start, index));
  }
  if (!monthRange) return [selectedDate];
  return dateRange(monthRange.start, monthRange.end);
}

function minutesFromMidnight(value: string) {
  const date = new Date(value);
  return date.getHours() * 60 + date.getMinutes();
}

function timeLabel(hour: number) {
  const date = new Date(2020, 0, 1, hour);
  return date.toLocaleTimeString([], { hour: "numeric" });
}

export function SchedulePage({ user }: { user: WorkspaceUser }) {
  const [month, setMonth] = useState(localMonth);
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().slice(0, 10));
  const [viewMode, setViewMode] = useState<ViewMode>("workWeek");
  const [eventQuery, setEventQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [therapistFilter, setTherapistFilter] = useState("all");
  const [data, setData] = useState<ScheduleData | null>(null);
  const [patients, setPatients] = useState<Patient[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [moveTarget, setMoveTarget] = useState<Appointment | null>(null);
  const [moving, setMoving] = useState(false);
  const [newEventOpen, setNewEventOpen] = useState(false);

  const loadSchedule = useCallback(async () => {
    setError("");
    try {
      const payload = await api.schedule(month);
      setData(payload);
      if (selectedDate < payload.visibleStart || selectedDate > payload.visibleEnd) {
        setSelectedDate(payload.month + "-01");
      }
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to load the schedule.");
    }
  }, [month, selectedDate]);

  const loadPatients = useCallback(async () => {
    try {
      const payload = await api.patients();
      setPatients(payload.patients);
    } catch {
      setPatients([]);
    }
  }, []);

  useEffect(() => {
    void loadSchedule();
  }, [loadSchedule]);

  useEffect(() => {
    void loadPatients();
  }, [loadPatients]);

  const therapistOptions = useMemo(() => {
    const seen = new Map<string, string>();
    data?.events.forEach((event) => {
      if (!seen.has(event.therapist.id)) {
        seen.set(event.therapist.id, event.therapist.displayName);
      }
    });
    return [...seen.entries()].map(([id, label]) => ({ id, label }));
  }, [data]);

  const filteredEvents = useMemo(() => {
    const query = eventQuery.trim().toLowerCase();
    const list = data?.events ?? [];
    return list.filter((event) => {
      if (statusFilter !== "all" && event.status !== statusFilter) return false;
      if (therapistFilter !== "all" && event.therapist.id !== therapistFilter) return false;
      if (!query) return true;
      const haystack = [
        event.patient.fullName,
        event.kindLabel,
        event.therapist.displayName,
        event.location || "",
        event.statusLabel,
      ].join(" ").toLowerCase();
      return haystack.includes(query);
    });
  }, [data, eventQuery, statusFilter, therapistFilter]);

  const eventsByDate = useMemo(() => {
    const grouped = new Map<string, Appointment[]>();
    filteredEvents.forEach((event) => grouped.set(event.date, [...(grouped.get(event.date) || []), event]));
    return grouped;
  }, [filteredEvents]);

  const visibleDays = useMemo(() => {
    if (!data) return [selectedDate];
    return visibleDaysFor(viewMode, selectedDate, { start: data.visibleStart, end: data.visibleEnd });
  }, [data, selectedDate, viewMode]);

  const selectedEvents = eventsByDate.get(selectedDate) || [];

  function stepView(direction: number) {
    if (viewMode === "month") {
      const nextMonth = shiftMonth(month, direction);
      setMonth(nextMonth);
      setSelectedDate(`${nextMonth}-01`);
      return;
    }
    const slice = viewMode === "day" ? 1 : viewMode === "workWeek" ? 5 : 7;
    setSelectedDate(addDays(selectedDate, direction * slice));
  }

  async function moveAppointment(appointment: Appointment, targetDate: string, targetStart = "") {
    if (appointment.date === targetDate) {
      setNotice("This appointment is already scheduled on that date.");
      return;
    }
    setMoving(true);
    setError("");
    setNotice("Moving appointment…");
    try {
      const result = await api.moveAppointment(appointment.id, targetDate, targetStart);
      setNotice(result.detail);
      if (result.moved) {
        setSelectedDate(targetDate);
        setMoveTarget(null);
        await loadSchedule();
      }
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "The appointment could not be moved.");
    } finally {
      setMoving(false);
      setDraggedId(null);
    }
  }

  async function cancelAppointment(appointment: Appointment) {
    if (!window.confirm(`Cancel ${appointment.patient.fullName}'s appointment?`)) return;
    setMoving(true);
    setError("");
    try {
      const result = await api.cancelAppointment(appointment.id);
      setNotice(result.detail);
      setMoveTarget(null);
      await loadSchedule();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "The appointment could not be cancelled.");
    } finally {
      setMoving(false);
    }
  }

  function handleDrop(event: DragEvent<HTMLElement>, date: string) {
    event.preventDefault();
    const appointment = filteredEvents.find((item) => item.id === draggedId);
    if (appointment && appointment.status === "scheduled") {
      void moveAppointment(appointment, date);
    }
  }

  if (error && !data) {
    return <section className="page-error" role="alert"><h1>Schedule unavailable</h1><p>{error}</p></section>;
  }
  if (!data) {
    return <section className="page-loading" aria-live="polite">Loading calendar…</section>;
  }

  return (
    <div className="page-content">
      <header className="page-header split-header">
        <div>
          <p className="eyebrow">Schedule · {viewMode === "day" ? "day view" : viewMode === "week" ? "week view" : viewMode === "workWeek" ? "work week view" : "month view"}</p>
          <h1>{viewMode === "month" ? monthLabel(data.month) : formatDate(selectedDate, { month: "long", year: "numeric" })}</h1>
          <p>Drag a scheduled visit to another date, or select it to choose a date. The server retains its local time and duration.</p>
        </div>
        <div className="button-row">
          <div className="segmented-control" aria-label="Calendar view selector">
            {(["day", "week", "workWeek", "month"] as const).map((mode) => (
              <button
                key={mode}
                className={viewMode === mode ? "active" : ""}
                onClick={() => setViewMode(mode)}
                type="button"
              >
                {mode === "day" ? "Day" : mode === "week" ? "Week" : mode === "workWeek" ? "Work week" : "Month"}
              </button>
            ))}
          </div>
          <button className="primary-button" type="button" onClick={() => setNewEventOpen(true)}>+ New event</button>
          <button className="secondary-button" type="button" onClick={() => stepView(-1)}>← Previous</button>
          <button className="secondary-button" type="button" onClick={() => {
            const today = new Date().toISOString().slice(0, 10);
            setSelectedDate(today);
            setMonth(localMonth());
          }}>Today</button>
          <button className="secondary-button" type="button" onClick={() => stepView(1)}>Next →</button>
        </div>
      </header>

      <div className="schedule-toolbar">
        <label className="field-inline">
          <span>Search</span>
          <input value={eventQuery} onChange={(event) => setEventQuery(event.target.value)} placeholder="Patient, provider, type…" />
        </label>
        <label className="field-inline">
          <span>Status</span>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="all">All</option>
            <option value="scheduled">Scheduled</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
            <option value="no_show">No show</option>
          </select>
        </label>
        <label className="field-inline">
          <span>Therapist</span>
          <select value={therapistFilter} onChange={(event) => setTherapistFilter(event.target.value)}>
            <option value="all">All</option>
            {therapistOptions.map((therapist) => (
              <option value={therapist.id} key={therapist.id}>{therapist.label}</option>
            ))}
          </select>
        </label>
      </div>

      {error && <p className="form-error" role="alert">{error}</p>}
      {notice && <p className="form-notice" role="status">{notice}</p>}

      <section className="surface-card calendar-surface" aria-labelledby="react-calendar-title">
        <header className="card-heading">
          <div>
            <p className="eyebrow">Calendar</p>
            <h2 id="react-calendar-title">{viewMode === "month" ? `${monthLabel(data.month)} appointments` : `${formatDate(visibleDays[0], { month: "short", day: "numeric" })} – ${formatDate(visibleDays[visibleDays.length - 1], { month: "short", day: "numeric" })}`}</h2>
          </div>
          <span className="calendar-help">{viewMode === "month" ? "Drag or select scheduled visits to move" : "Overview of the active schedule range"}</span>
        </header>

        <div className="calendar-scroll">
          {viewMode !== "month" && (
            <TimeGrid
              days={visibleDays}
              events={filteredEvents}
              moving={moving}
              draggedId={draggedId}
              onSelectDate={setSelectedDate}
              onDragStart={setDraggedId}
              onDragEnd={() => setDraggedId(null)}
              onDrop={handleDrop}
              onSelect={(appointment) => appointment.status === "scheduled" && setMoveTarget(appointment)}
            />
          )}
          {viewMode === "month" && (
          <div className={`react-calendar ${moving ? "is-saving" : ""}`} role="grid" aria-label={`${viewMode} appointment calendar`} style={{ gridTemplateColumns: `repeat(${Math.min(visibleDays.length, 7)}, minmax(0, 1fr))` }}>
            {visibleDays.map((date) => {
              const events = eventsByDate.get(date) || [];
              const inMonth = viewMode === "month" ? date.startsWith(data.month) : true;
              const isSelected = date === selectedDate;
              const isToday = date === new Date().toISOString().slice(0, 10);
              return (
                <div
                  className={`react-calendar-day ${!inMonth ? "outside" : ""} ${isSelected ? "selected" : ""} ${isToday ? "today" : ""}`}
                  key={date}
                  role="gridcell"
                  onDragOver={(event) => draggedId && event.preventDefault()}
                  onDrop={(event) => handleDrop(event, date)}
                >
                  <button className="calendar-date-button" onClick={() => setSelectedDate(date)} aria-label={`View ${formatDate(date, { weekday: "long" })} agenda`}>
                    <span>{Number(date.slice(-2))}</span>
                  </button>
                  <div className="react-calendar-events">
                    {events.slice(0, viewMode === "month" ? 3 : 4).map((appointment) => (
                      <AppointmentChip
                        appointment={appointment}
                        key={appointment.id}
                        onDragStart={() => setDraggedId(appointment.id)}
                        onDragEnd={() => setDraggedId(null)}
                        onSelect={() => appointment.status === "scheduled" && setMoveTarget(appointment)}
                      />
                    ))}
                    {events.length > (viewMode === "month" ? 3 : 4) && (
                      <button className="more-events" onClick={() => setSelectedDate(date)}>+{events.length - (viewMode === "month" ? 3 : 4)} more</button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          )}
        </div>
      </section>

      <section className="surface-card agenda-surface" aria-labelledby="agenda-title">
        <header className="card-heading">
          <div>
            <p className="eyebrow">Selected day</p>
            <h2 id="agenda-title">{formatDate(selectedDate, { weekday: "long" })}</h2>
          </div>
          <span className="agenda-count">{selectedEvents.length} visit{selectedEvents.length === 1 ? "" : "s"}</span>
        </header>
        {selectedEvents.length ? (
          <ul className="agenda-list">
            {selectedEvents.map((appointment) => (
              <li key={appointment.id}>
                <time>
                  <strong>{formatTime(appointment.startsAt)}</strong>
                  <small>{formatTime(appointment.endsAt)}</small>
                </time>
                <span>
                  <strong>{appointment.patient.fullName}</strong>
                  <small>{appointment.kindLabel} · {appointment.therapist.displayName} · {appointment.isHomeVisit ? "Home visit" : appointment.location || "Location pending"}</small>
                </span>
                <div>
                  {appointment.status === "scheduled" && <button className="secondary-button" onClick={() => setMoveTarget(appointment)}>Move</button>}
                  {appointment.status === "scheduled" && <button className="secondary-button danger-button" onClick={() => void cancelAppointment(appointment)}>Cancel</button>}
                  <span className={`status-pill ${appointment.status}`}>{appointment.statusLabel}</span>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="empty-copy">No appointments scheduled for this day.</p>
        )}
      </section>

      {moveTarget && <MoveDialog appointment={moveTarget} busy={moving} onClose={() => !moving && setMoveTarget(null)} onMove={(targetDate, targetStart) => void moveAppointment(moveTarget, targetDate, targetStart)} onCancel={() => void cancelAppointment(moveTarget)} />}
      {newEventOpen && (
        <NewEventDialog
          user={user}
          patients={patients}
          selectedDate={selectedDate}
          onClose={() => setNewEventOpen(false)}
          onCreated={async () => {
            setNewEventOpen(false);
            await loadSchedule();
            setNotice("Appointment created.");
          }}
        />
      )}
    </div>
  );
}

function TimeGrid({
  days,
  events,
  moving,
  draggedId,
  onSelectDate,
  onDragStart,
  onDragEnd,
  onDrop,
  onSelect,
}: {
  days: string[];
  events: Appointment[];
  moving: boolean;
  draggedId: string | null;
  onSelectDate: (date: string) => void;
  onDragStart: (id: string) => void;
  onDragEnd: () => void;
  onDrop: (event: DragEvent<HTMLElement>, date: string) => void;
  onSelect: (appointment: Appointment) => void;
}) {
  const hours = Array.from({ length: 11 }, (_, index) => index + 7);
  const eventsByDate = new Map<string, Appointment[]>();
  events.forEach((event) => eventsByDate.set(event.date, [...(eventsByDate.get(event.date) || []), event]));
  return <div className={`time-grid ${moving ? "is-saving" : ""}`} style={{ "--day-count": days.length } as CSSProperties}>
    <div className="time-grid-corner" />
    {days.map((date) => <button className={`time-grid-day-heading ${date === new Date().toISOString().slice(0, 10) ? "today" : ""}`} key={date} onClick={() => onSelectDate(date)} type="button"><strong>{formatDate(date, { weekday: "short" })}</strong><span>{Number(date.slice(-2))}</span></button>)}
    <div className="time-grid-hours">{hours.map((hour) => <span key={hour}>{timeLabel(hour)}</span>)}</div>
    {days.map((date) => <div className="time-grid-column" key={date} onDragOver={(event) => draggedId && event.preventDefault()} onDrop={(event) => onDrop(event, date)}>{hours.slice(0, -1).map((hour) => <span className="time-grid-slot" key={hour} />)}{(eventsByDate.get(date) || []).map((appointment) => { const start = Math.max(7 * 60, minutesFromMidnight(appointment.startsAt)); const end = Math.min(18 * 60, minutesFromMidnight(appointment.endsAt)); const top = ((start - 7 * 60) / (11 * 60)) * 100; const height = Math.max(5, ((end - start) / (11 * 60)) * 100); return <button className={`time-grid-event ${appointment.status}`} key={appointment.id} type="button" draggable={appointment.status === "scheduled"} onDragStart={() => onDragStart(appointment.id)} onDragEnd={onDragEnd} onClick={() => onSelect(appointment)} style={{ top: `${top}%`, height: `${height}%` }}><time>{formatTime(appointment.startsAt)} – {formatTime(appointment.endsAt)}</time><strong>{appointment.patient.fullName}</strong><small>{appointment.kindLabel}</small></button>; })}</div>)}
  </div>;
}

function AppointmentChip({ appointment, onDragStart, onDragEnd, onSelect }: { appointment: Appointment; onDragStart: () => void; onDragEnd: () => void; onSelect: () => void }) {
  const movable = appointment.status === "scheduled";
  return <button
    className={`appointment-chip ${appointment.status}`}
    type="button"
    draggable={movable}
    onDragStart={onDragStart}
    onDragEnd={onDragEnd}
    onClick={onSelect}
    aria-label={movable ? `Move ${appointment.patient.fullName} at ${formatTime(appointment.startsAt)}` : `${appointment.patient.fullName} at ${formatTime(appointment.startsAt)}`}
  >
    <time>{formatTime(appointment.startsAt)}</time>
    <strong>{appointment.patient.fullName}</strong>
  </button>;
}

function NewEventDialog({
  user,
  patients,
  selectedDate,
  onClose,
  onCreated,
}: {
  user: WorkspaceUser;
  patients: Patient[];
  selectedDate: string;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [patientId, setPatientId] = useState(patients[0]?.id ?? "");
  const [startsAt, setStartsAt] = useState(`${selectedDate}T09:00`);
  const [endsAt, setEndsAt] = useState(`${selectedDate}T10:00`);
  const [kind, setKind] = useState("follow_up");
  const [location, setLocation] = useState("Clinic");
  const [isHomeVisit, setIsHomeVisit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!patientId && patients.length) setPatientId(patients[0].id);
  }, [patientId, patients]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!patientId) {
      setError("Choose a patient before saving the event.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.createAppointment(patientId, {
        therapistId: user.id,
        startsAt: new Date(startsAt).toISOString(),
        endsAt: new Date(endsAt).toISOString(),
        kind,
        location,
        isHomeVisit,
      });
      await onCreated();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Unable to create the event.");
    } finally {
      setBusy(false);
    }
  }

  return <div className="modal-backdrop" role="presentation"><section className="move-dialog" role="dialog" aria-modal="true" aria-labelledby="new-event-title"><button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">×</button><p className="eyebrow">Create event</p><h2 id="new-event-title">New calendar event</h2><form onSubmit={submit}><label htmlFor="event-patient">Patient</label><select id="event-patient" value={patientId} onChange={(event) => setPatientId(event.target.value)} required><option value="" disabled>Select patient</option>{patients.map((patient) => <option value={patient.id} key={patient.id}>{patient.fullName}</option>)}</select><div className="field-grid"><label>Start<input type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} required /></label><label>End<input type="datetime-local" value={endsAt} onChange={(event) => setEndsAt(event.target.value)} required /></label></div><div className="field-grid"><label>Visit type<select value={kind} onChange={(event) => setKind(event.target.value)}><option value="evaluation">Initial evaluation</option><option value="follow_up">Follow-up visit</option><option value="progress">Progress visit</option><option value="discharge">Discharge visit</option><option value="telehealth">Telehealth</option></select></label><label>Location<input value={location} onChange={(event) => setLocation(event.target.value)} placeholder="Clinic, home, or telehealth" /></label></div><label className="check-label"><input type="checkbox" checked={isHomeVisit} onChange={(event) => setIsHomeVisit(event.target.checked)} />Home visit</label>{error && <p className="form-error" role="alert">{error}</p>}<div className="button-row"><button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Cancel</button><button className="primary-button" type="submit" disabled={busy}>{busy ? "Creating…" : "Create event"}</button></div></form></section></div>;
}

function MoveDialog({ appointment, busy, onClose, onMove, onCancel }: { appointment: Appointment; busy: boolean; onClose: () => void; onMove: (targetDate: string, targetStart: string) => void; onCancel: () => void }) {
  const [targetStart, setTargetStart] = useState(appointment.startsAt.slice(0, 16));
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onMove(targetStart.slice(0, 10), targetStart);
  }
  return <div className="modal-backdrop" role="presentation"><section className="move-dialog" role="dialog" aria-modal="true" aria-labelledby="move-dialog-title"><button className="dialog-close" onClick={onClose} disabled={busy} aria-label="Close">×</button><p className="eyebrow">Reschedule visit</p><h2 id="move-dialog-title">Move appointment</h2><p>Choose a new date and time. The existing visit duration will remain unchanged.</p><form onSubmit={submit}><label htmlFor="move-target-start">New appointment date and time</label><input id="move-target-start" type="datetime-local" value={targetStart} onChange={(event) => setTargetStart(event.target.value)} required /><div className="button-row"><button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Keep appointment</button><button className="secondary-button danger-button" type="button" onClick={onCancel} disabled={busy}>Cancel appointment</button><button className="primary-button" type="submit" disabled={busy}>{busy ? "Moving…" : "Move appointment"}</button></div></form></section></div>;
}
