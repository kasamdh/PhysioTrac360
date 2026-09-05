import type { WorkspaceUser } from "../api/types";
import { formatDateTime } from "../lib/format";

interface HomeTopBarProps {
  user: WorkspaceUser;
  onLogout: () => void;
  onHome?: () => void;
  pageLabel?: string;
  brandLabel?: string;
}

export function HomeTopBar({ user, onLogout, onHome, pageLabel = "Home", brandLabel }: HomeTopBarProps) {
  const organizationName = user.organization?.name || brandLabel || "PhysioTrac360";

  return (
    <header className="home-topbar">
      <div className="home-topbar-left">
        {user.organization?.logoUrl ? (
          <img src={user.organization.logoUrl} alt="" />
        ) : (
          <span className="home-topbar-mark" aria-hidden="true">
            PT
          </span>
        )}
        <button type="button" className="home-topbar-link" onClick={() => window.history.back()}>
          Go Back
        </button>
        <button type="button" className="home-topbar-link active" onClick={onHome} disabled={!onHome}>
          Home
        </button>
      </div>

      <div className="home-topbar-center">
        <p className="home-topbar-welcome">
          Welcome, {user.displayName}
          {user.lastLogin && (
            <span className="home-topbar-lastlogin">
              {" "}
              · Last login: {formatDateTime(user.lastLogin, user.organization?.timezone)}
            </span>
          )}
        </p>
        <p className="home-topbar-pagelabel">{pageLabel}</p>
      </div>

      <div className="home-topbar-right">
        <button type="button" className="home-topbar-icon" onClick={() => window.print()} aria-label="Print this page" title="Print">
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M6 9V3.5h12V9" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
            <rect x="3.5" y="9" width="17" height="8" rx="1.6" stroke="currentColor" strokeWidth="1.6" />
            <path d="M6 14.5h12V20.5H6z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
          </svg>
        </button>
        <button type="button" className="home-topbar-logout" onClick={onLogout}>
          Logout
        </button>
      </div>
    </header>
  );
}
