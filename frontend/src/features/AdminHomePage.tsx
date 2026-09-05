import { ReactNode, useEffect, useState } from "react";

import { api } from "../api/client";
import type { ClinicLocation, WorkspaceUser } from "../api/types";
import type { WorkspacePage } from "../components/AppShell";
import { HomeTopBar } from "../components/HomeTopBar";

interface AdminHomePageProps {
  user: WorkspaceUser;
  onNavigate: (page: WorkspacePage) => void;
  onLogout: () => void;
}

interface ModuleTile {
  key: WorkspacePage;
  label: string;
  description: string;
  icon: ReactNode;
  tone: string;
  visible: boolean;
}

function IconPatients() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="9" cy="8" r="3.25" stroke="currentColor" strokeWidth="1.6" />
      <path d="M3.5 20c0-3.31 2.46-6 5.5-6s5.5 2.69 5.5 6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="17" cy="7.5" r="2.25" stroke="currentColor" strokeWidth="1.6" />
      <path d="M14.8 20c.2-2.9 1.9-5 4.2-5 2.15 0 3.9 1.83 4.2 4.4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function IconCalendar() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3.5" y="5" width="17" height="15.5" rx="2.2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M3.5 9.5h17" stroke="currentColor" strokeWidth="1.6" />
      <path d="M7.5 3v4M16.5 3v4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M7.5 13h3M13.5 13h3M7.5 16.5h3M13.5 16.5h3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function IconReports() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 20V10M11 20V4M18 20v-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <path d="M3 20.5h18" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function IconSettings() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="3.1" stroke="currentColor" strokeWidth="1.6" />
      <path
        d="M12 3.5v2M12 18.5v2M20.5 12h-2M5.5 12h-2M17.7 6.3l-1.4 1.4M7.7 16.3l-1.4 1.4M17.7 17.7l-1.4-1.4M7.7 7.7 6.3 6.3"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function IconShield() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 3.5 19.5 6.3V11c0 5-3.2 8.4-7.5 9.7-4.3-1.3-7.5-4.7-7.5-9.7V6.3L12 3.5Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M9 12.2l2 2 4-4.4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function AdminHomePage({ user, onNavigate, onLogout }: AdminHomePageProps) {
  const [locations, setLocations] = useState<ClinicLocation[]>([]);
  const [selectedLocationId, setSelectedLocationId] = useState("");
  const [loadingLocations, setLoadingLocations] = useState(true);

  useEffect(() => {
    let active = true;
    api
      .locations()
      .then((result) => {
        if (!active) return;
        const activeLocations = result.locations.filter((location) => location.isActive);
        setLocations(activeLocations);
        if (activeLocations.length) setSelectedLocationId(activeLocations[0].id);
      })
      .catch(() => undefined)
      .finally(() => active && setLoadingLocations(false));
    return () => {
      active = false;
    };
  }, []);

  const organizationName = user.organization?.name || "Your organization";

  const allModules: ModuleTile[] = [
    {
      key: "patients",
      label: "Patients",
      description: "Search charts, open a patient workspace, or add a new patient.",
      icon: <IconPatients />,
      tone: "crimson",
      visible: true,
    },
    {
      key: "schedule",
      label: "Scheduling",
      description: "Day, week, work-week, and month views with home-visit support.",
      icon: <IconCalendar />,
      tone: "teal",
      visible: user.capabilities.canManageSchedule,
    },
    {
      key: "reports",
      label: "Reports",
      description: "Operational reports across your practice.",
      icon: <IconReports />,
      tone: "amber",
      visible: user.role === "admin",
    },
    {
      key: "users",
      label: "Administration",
      description: "Manage staff accounts, access, locations, and appointment types.",
      icon: <IconSettings />,
      tone: "purple",
      visible: user.capabilities.canManageAccess,
    },
    {
      key: "safety",
      label: "Safety & audit",
      description: "Review the audit trail and compliance queue.",
      icon: <IconShield />,
      tone: "green",
      visible: user.capabilities.canReviewAudit,
    },
  ];
  const modules = allModules.filter((module) => module.visible);

  return (
    <div className="admin-home-page">
      <HomeTopBar user={user} onLogout={onLogout} onHome={() => onNavigate("dashboard")} />
      <div className="page-content admin-home">
      <header className="admin-home-header">
        <h1>{organizationName}</h1>
      </header>

      <div className="admin-home-location">
        <label htmlFor="admin-home-location-select">Location</label>
        {loadingLocations ? (
          <p className="muted">Loading locations…</p>
        ) : locations.length ? (
          <select
            id="admin-home-location-select"
            value={selectedLocationId}
            onChange={(event) => setSelectedLocationId(event.target.value)}
            disabled={locations.length < 2}
            aria-label="Current location"
          >
            {locations.map((location) => (
              <option key={location.id} value={location.id}>
                {location.name}
              </option>
            ))}
          </select>
        ) : (
          <p className="muted">No locations configured yet — add one from Administration.</p>
        )}
      </div>

      <nav className="module-grid" aria-label="Workspace modules">
        {modules.map((module) => (
          <button key={module.key} className="module-link" onClick={() => onNavigate(module.key)}>
            <span className={`module-icon ${module.tone}`}>{module.icon}</span>
            <span className="module-copy">
              <strong>{module.label}</strong>
              <small>{module.description}</small>
            </span>
          </button>
        ))}
      </nav>

      <footer className="admin-home-footer">
        <span>v1.0</span>
        <span>&copy; {new Date().getFullYear()} {organizationName}</span>
      </footer>
      </div>
    </div>
  );
}
