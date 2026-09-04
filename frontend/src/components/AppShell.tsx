import type { ReactNode } from "react";

import type { WorkspaceUser } from "../api/types";

export type WorkspacePage = "dashboard" | "schedule" | "patients" | "safety" | "clients" | "users" | "clinic-settings" | "reports";

interface AppShellProps {
  user: WorkspaceUser;
  page: WorkspacePage;
  onNavigate: (page: WorkspacePage) => void;
  onLogout: () => void;
  children: ReactNode;
}

function orgInitials(name: string): string {
  const words = name.split(/\s+/).filter(Boolean);
  if (!words.length) return "PT";
  return words.slice(0, 2).map((word) => word[0]).join("").toUpperCase();
}

export function AppShell({ user, page, onNavigate, onLogout, children }: AppShellProps) {
  const organizationName = user.organization?.name || "PhysioTrac360";

  return (
    <div className="workspace-shell">
      <aside className="workspace-sidebar" aria-label="Primary navigation">
        <div className="workspace-brand">
          {user.organization?.logoUrl ? (
            <img src={user.organization.logoUrl} alt={`${organizationName} logo`} />
          ) : (
            <span className="workspace-brand-mark">{orgInitials(organizationName)}</span>
          )}
          <span>
            <strong>{organizationName}</strong>
            <small>All-in-one practice workspace</small>
          </span>
        </div>

        <nav className="workspace-nav">
          {user.capabilities.isSuperAdmin && (
            <>
              <button className={page === "clients" ? "active" : ""} onClick={() => onNavigate("clients")}>
                <span aria-hidden="true">◆</span> Clients
              </button>
              <button className={page === "users" ? "active" : ""} onClick={() => onNavigate("users")}>
                <span aria-hidden="true">◉</span> Users
              </button>
            </>
          )}
          {!user.capabilities.isSuperAdmin && (
            <>
          <button className={page === "dashboard" ? "active" : ""} onClick={() => onNavigate("dashboard")}>
            <span aria-hidden="true">⌂</span> Today
          </button>
          {user.capabilities.canManageSchedule && (
            <button className={page === "schedule" ? "active" : ""} onClick={() => onNavigate("schedule")}>
              <span aria-hidden="true">◷</span> Schedule
            </button>
          )}
          <button className={page === "patients" ? "active" : ""} onClick={() => onNavigate("patients")}>
            <span aria-hidden="true">◉</span> Patients
          </button>
          {user.capabilities.canManageAccess && (
            <button className={page === "users" ? "active" : ""} onClick={() => onNavigate("users")}>
              <span aria-hidden="true">◈</span> Users
            </button>
          )}
          {user.capabilities.canReviewAudit && (
            <button className={page === "safety" ? "active" : ""} onClick={() => onNavigate("safety")}>
              <span aria-hidden="true">S</span> Safety
            </button>
          )}
          {user.role === "admin" && (
            <>
              <button className={page === "clinic-settings" ? "active" : ""} onClick={() => onNavigate("clinic-settings")}>
                <span aria-hidden="true">⚙</span> Clinic settings
              </button>
              <button className={page === "reports" ? "active" : ""} onClick={() => onNavigate("reports")}>
                <span aria-hidden="true">▤</span> Reports
              </button>
            </>
          )}
            </>
          )}
        </nav>

        <div className="workspace-sidebar-footer">
          <div className="workspace-privacy">
            <span aria-hidden="true">▣</span>
            <span>Private workspace. Keep this screen out of public view.</span>
          </div>
          <div className="workspace-user">
            <span className="workspace-avatar">{user.displayName.slice(0, 1).toUpperCase()}</span>
            <span>
              <strong>{user.displayName}</strong>
              <small>{user.roleLabel}</small>
            </span>
          </div>
          <button className="workspace-signout" onClick={onLogout}>Sign out</button>
        </div>
      </aside>
      <main className="workspace-main">{children}</main>
    </div>
  );
}
