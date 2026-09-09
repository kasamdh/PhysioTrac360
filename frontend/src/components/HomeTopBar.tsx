import { useState } from "react";

import type { WorkspaceUser } from "../api/types";
import { formatDateTime } from "../lib/format";
import { SecurityDialog } from "../features/SecurityDialog";

interface HomeTopBarProps {
  user: WorkspaceUser;
  onLogout: () => void;
  onHome?: () => void;
  pageLabel?: string;
  brandLabel?: string;
}

export function HomeTopBar({ user, onLogout, onHome, pageLabel = "Home", brandLabel }: HomeTopBarProps) {
  const organizationName = user.organization?.name || brandLabel || "Source Motion PT";
  const [showSecurity, setShowSecurity] = useState(false);

  return (
    <header className="home-topbar">
      <div className="home-topbar-left">
        {user.organization?.logoUrl ? (
          <img src={user.organization.logoUrl} alt="" />
        ) : !user.organization ? (
          // No organization = the platform-level (super admin) context, not
          // a specific tenant — safe to show Source Motion's own logo here.
          // A tenant without its own uploaded logo still falls through to
          // the generic "PT" mark below, never this deployment's brand.
          <img
            src={`${import.meta.env.BASE_URL}assets/source-motion-logo.png`}
            alt="Source Motion Physical Therapy"
            className="home-topbar-brand-logo"
          />
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
        <button type="button" className="home-topbar-icon" onClick={() => setShowSecurity(true)} aria-label="Security and active sessions" title="Security">
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M12 3.5 19.5 6.3V11c0 5-3.2 8.4-7.5 9.7-4.3-1.3-7.5-4.7-7.5-9.7V6.3L12 3.5Z"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
          </svg>
        </button>
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

      {showSecurity && <SecurityDialog user={user} onClose={() => setShowSecurity(false)} />}
    </header>
  );
}
