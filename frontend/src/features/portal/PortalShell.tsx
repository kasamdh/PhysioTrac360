import type { ReactNode } from "react";

import type { WorkspaceUser } from "../../api/types";

export type PortalPage = "dashboard" | "appointments" | "book" | "waitlist" | "forms" | "documents" | "hep" | "outcomes" | "messages" | "payments" | "profile";

const NAV_ITEMS: { key: PortalPage; label: string }[] = [
  { key: "dashboard", label: "Home" },
  { key: "appointments", label: "My Appointments" },
  { key: "book", label: "Book a Visit" },
  { key: "forms", label: "Forms" },
  { key: "documents", label: "Documents" },
  { key: "hep", label: "My Exercises" },
  { key: "outcomes", label: "Outcome Measures" },
  { key: "messages", label: "Messages" },
  { key: "payments", label: "Payments" },
  { key: "waitlist", label: "Waitlist" },
  { key: "profile", label: "Profile" },
];

interface PortalShellProps {
  user: WorkspaceUser;
  page: PortalPage;
  onNavigate: (page: PortalPage) => void;
  onLogout: () => void;
  children: ReactNode;
}

/**
 * The patient-facing shell — deliberately not AppShell. No sidebar full of
 * staff/admin navigation, no clinical/billing complexity by default; a
 * simple top bar, a row of large-touch-target nav tabs, and a single
 * content column that reads well on a phone. Reuses the same design-system
 * CSS classes as the staff app (surface-card, page-content, etc.) for
 * visual consistency, without any of its structure.
 */
export function PortalShell({ user, page, onNavigate, onLogout, children }: PortalShellProps) {
  return (
    <div className="portal-shell">
      <header className="portal-topbar">
        <div className="portal-topbar-brand">
          {user.organization?.logoUrl && <img src={user.organization.logoUrl} alt="" className="portal-topbar-logo" />}
          <span>{user.organization?.name || "Patient Portal"}</span>
        </div>
        <div className="portal-topbar-actions">
          <span className="portal-topbar-user">{user.displayName}</span>
          <button className="text-action" onClick={onLogout}>Sign out</button>
        </div>
      </header>
      <nav className="portal-nav" aria-label="Patient portal sections">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.key}
            className={page === item.key ? "active" : ""}
            onClick={() => onNavigate(item.key)}
            aria-current={page === item.key ? "page" : undefined}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <main className="portal-content">{children}</main>
    </div>
  );
}
