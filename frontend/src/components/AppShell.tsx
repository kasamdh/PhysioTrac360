import type { ReactNode } from "react";

import type { WorkspaceUser } from "../api/types";
import { AppFooter } from "./AppFooter";
import { HomeTopBar } from "./HomeTopBar";

export type WorkspacePage = "dashboard" | "schedule" | "patients" | "safety" | "clients" | "users" | "clinic-settings" | "reports" | "admin-hub";

interface AppShellProps {
  user: WorkspaceUser;
  page: WorkspacePage;
  onNavigate: (page: WorkspacePage) => void;
  onLogout: () => void;
  children: ReactNode;
}

const PAGE_LABELS: Record<WorkspacePage, string> = {
  dashboard: "Home",
  schedule: "Scheduling",
  patients: "Patients",
  safety: "Safety & Audit",
  users: "Users",
  "clinic-settings": "Administration",
  reports: "Reports",
  clients: "Clients",
  "admin-hub": "Administration",
};

export function AppShell({ user, page, onNavigate, onLogout, children }: AppShellProps) {
  const navItems: { key: WorkspacePage; label: string; icon: string }[] = user.capabilities.isSuperAdmin
    ? [
        { key: "clients", label: "Clients", icon: "◆" },
        { key: "users", label: "Users", icon: "◉" },
      ]
    : [
        ...(user.capabilities.canManageSchedule ? [{ key: "schedule" as const, label: "Schedule", icon: "◷" }] : []),
        { key: "patients" as const, label: "Patients", icon: "◉" },
        ...(user.capabilities.canManageAccess ? [{ key: "users" as const, label: "Users", icon: "◈" }] : []),
        ...(user.capabilities.canReviewAudit ? [{ key: "safety" as const, label: "Safety", icon: "S" }] : []),
        ...(user.role === "admin"
          ? [
              { key: "clinic-settings" as const, label: "Clinic settings", icon: "⚙" },
              { key: "reports" as const, label: "Reports", icon: "▤" },
            ]
          : []),
      ];

  return (
    <div className="app-shell-flat">
      <HomeTopBar user={user} onLogout={onLogout} onHome={() => onNavigate("dashboard")} pageLabel={PAGE_LABELS[page]} />
      {navItems.length > 0 && (
        <nav className="app-menu-bar" aria-label="Primary navigation">
          {navItems.map((item) => (
            <button
              key={item.key}
              className={page === item.key ? "active" : ""}
              onClick={() => onNavigate(item.key)}
            >
              <span aria-hidden="true">{item.icon}</span> {item.label}
            </button>
          ))}
        </nav>
      )}
      <main className="app-main">{children}</main>
      <AppFooter />
    </div>
  );
}
