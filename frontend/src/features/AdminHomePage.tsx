import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ClinicLocation, WorkspaceUser } from "../api/types";
import type { WorkspacePage } from "../components/AppShell";
import { HomeTopBar } from "../components/HomeTopBar";
import { ModuleGrid, type ModuleTileConfig } from "../components/ModuleGrid";

interface AdminHomePageProps {
  user: WorkspaceUser;
  onNavigate: (page: WorkspacePage) => void;
  onLogout: () => void;
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

function IconDocumentation() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6 3.5h9l4 4V20a1.2 1.2 0 0 1-1.2 1.2H6A1.2 1.2 0 0 1 4.8 20V4.7A1.2 1.2 0 0 1 6 3.5Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M15 3.5V7a1 1 0 0 0 1 1h3.5" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M8 12.5h8M8 15.8h8M8 9.2h4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function IconHome() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 11.5 12 4l8 7.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M6 10v9.5a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V10" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M10 20.5v-6h4v6" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
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

  const allModules: ModuleTileConfig<WorkspacePage>[] = [
    {
      key: "patients",
      label: "Patients",
      description: "Search charts, open a patient workspace, or add a new patient.",
      icon: <IconPatients />,
      tone: "crimson",
    },
    {
      key: "documentation",
      label: "Documentation",
      description: "Start, continue, and sign clinical notes across your caseload.",
      icon: <IconDocumentation />,
      tone: "blue",
    },
    {
      key: "schedule",
      label: "Scheduling",
      description: "Day, week, work-week, and month views with home-visit support.",
      icon: <IconCalendar />,
      tone: "teal",
    },
    {
      key: "mobile-care",
      label: "Mobile Care",
      description: "Review in-home PT requests, match a provider, and schedule the visit.",
      icon: <IconHome />,
      tone: "blue",
    },
    {
      key: "reports",
      label: "Reports",
      description: "Operational reports across your practice.",
      icon: <IconReports />,
      tone: "amber",
    },
    {
      key: "users",
      label: "Administration",
      description: "Manage staff accounts, access, locations, and appointment types.",
      icon: <IconSettings />,
      tone: "purple",
    },
    {
      key: "safety",
      label: "Safety & audit",
      description: "Review the audit trail and compliance queue.",
      icon: <IconShield />,
      tone: "green",
    },
  ];
  const visibility: Record<WorkspacePage, boolean> = {
    patients: true,
    documentation: user.capabilities.canAccessClinical,
    schedule: user.capabilities.canManageSchedule,
    "mobile-care": user.capabilities.canManageSchedule,
    reports: user.role === "admin",
    users: user.capabilities.canManageAccess,
    safety: user.capabilities.canReviewAudit,
    dashboard: false,
    clients: false,
    "clinic-settings": false,
    "admin-hub": false,
    credentials: false,
    "mobile-care-platform-defaults": false,
  };
  const modules = allModules.filter((module) => visibility[module.key]);

  return (
    <div className="flex min-h-screen flex-col bg-white">
      <HomeTopBar user={user} onLogout={onLogout} onHome={() => onNavigate("dashboard")} />
      <div className="mx-auto flex w-full max-w-[1040px] flex-1 flex-col px-6 pt-10">
        <header className="mb-7 text-center">
          <h1 className="m-0 text-[clamp(1.75rem,3vw,2.125rem)] font-bold tracking-[-0.02em] text-[#172127]">
            {organizationName}
          </h1>
        </header>

        <div className="mx-auto mb-10 flex flex-col items-center gap-2 text-center max-[620px]:w-full">
          <label htmlFor="admin-home-location-select" className="text-base font-semibold text-[#3d495d]">
            Location
          </label>
          {loadingLocations ? (
            <p className="text-[#5c697c]">Loading locations…</p>
          ) : locations.length ? (
            <select
              id="admin-home-location-select"
              value={selectedLocationId}
              onChange={(event) => setSelectedLocationId(event.target.value)}
              disabled={locations.length < 2}
              aria-label="Current location"
              className="min-h-[3.25rem] min-w-[280px] rounded-lg border border-[#cfdbe3] bg-white px-4 py-[0.6rem] text-center text-[1.0625rem] font-semibold text-[#263945] focus:border-primary focus:outline focus:outline-3 focus:outline-primary/15 disabled:bg-[#f6f8f9] disabled:text-[#5c697c] max-[620px]:w-full max-[620px]:min-w-0"
              style={{ textAlignLast: "center" }}
            >
              {locations.map((location) => (
                <option key={location.id} value={location.id}>
                  {location.name}
                </option>
              ))}
            </select>
          ) : (
            <p className="text-[#5c697c]">No locations configured yet — add one from Administration.</p>
          )}
        </div>

        <ModuleGrid modules={modules} onSelect={onNavigate} ariaLabel="Workspace modules" />

        <footer className="mt-auto flex justify-center gap-[0.6rem] border-t border-[#ece5df] py-6 text-sm text-[#97a0a8]">
          <span>v1.0</span>
          <span>&copy; {new Date().getFullYear()} {organizationName}</span>
        </footer>
      </div>
    </div>
  );
}
