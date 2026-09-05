import { useState } from "react";

import type { WorkspaceUser } from "../api/types";
import type { WorkspacePage } from "../components/AppShell";
import { HomeTopBar } from "../components/HomeTopBar";
import { ChangePasswordDialog } from "./ChangePasswordDialog";

interface SuperAdminAdministrationPageProps {
  user: WorkspaceUser;
  onNavigate: (page: WorkspacePage) => void;
  onLogout: () => void;
}

interface AdminMenuItem {
  label: string;
  action: () => void;
}

export function SuperAdminAdministrationPage({ user, onNavigate, onLogout }: SuperAdminAdministrationPageProps) {
  const [showChangePassword, setShowChangePassword] = useState(false);

  const items: AdminMenuItem[] = [
    { label: "Clients", action: () => onNavigate("clients") },
    { label: "Platform Users", action: () => onNavigate("users") },
    { label: "Change Password", action: () => setShowChangePassword(true) },
  ];

  return (
    <div className="admin-home-page">
      <HomeTopBar
        user={user}
        onLogout={onLogout}
        onHome={() => onNavigate("dashboard")}
        pageLabel="Administration"
        brandLabel="PhysioTrac360"
      />
      <div className="page-content admin-home">
        <nav className="admin-menu-grid" aria-label="Administration">
          {items.map((item) => (
            <button key={item.label} className="admin-menu-button" onClick={item.action}>
              {item.label}
            </button>
          ))}
        </nav>

        <footer className="admin-home-footer">
          <span>v1.0</span>
          <span>&copy; {new Date().getFullYear()} PhysioTrac360</span>
        </footer>
      </div>

      {showChangePassword && <ChangePasswordDialog onClose={() => setShowChangePassword(false)} />}
    </div>
  );
}
