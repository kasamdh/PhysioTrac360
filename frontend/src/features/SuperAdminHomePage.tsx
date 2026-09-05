import type { WorkspaceUser } from "../api/types";
import type { WorkspacePage } from "../components/AppShell";
import { HomeTopBar } from "../components/HomeTopBar";

interface SuperAdminHomePageProps {
  user: WorkspaceUser;
  onNavigate: (page: WorkspacePage) => void;
  onLogout: () => void;
}

function IconAdministration() {
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

export function SuperAdminHomePage({ user, onNavigate, onLogout }: SuperAdminHomePageProps) {
  return (
    <div className="admin-home-page">
      <HomeTopBar user={user} onLogout={onLogout} onHome={() => onNavigate("dashboard")} brandLabel="PhysioTrac360" />
      <div className="page-content admin-home">
        <header className="admin-home-header">
          <h1>PhysioTrac360 Platform</h1>
        </header>

        <nav className="module-grid" aria-label="Platform administration modules">
          <button className="module-link" onClick={() => onNavigate("admin-hub")}>
            <span className="module-icon purple">
              <IconAdministration />
            </span>
            <span className="module-copy">
              <strong>Administration</strong>
              <small>Manage clients, platform users, and account settings.</small>
            </span>
          </button>
        </nav>

        <footer className="admin-home-footer">
          <span>v1.0</span>
          <span>&copy; {new Date().getFullYear()} PhysioTrac360</span>
        </footer>
      </div>
    </div>
  );
}
