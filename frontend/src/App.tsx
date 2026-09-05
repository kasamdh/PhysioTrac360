import { useEffect, useState } from "react";

import { ApiError, api } from "./api/client";
import type { WorkspaceUser } from "./api/types";
import { ActivateInvitationPage } from "./features/ActivateInvitationPage";
import { AdminHomePage } from "./features/AdminHomePage";
import { AllUsersPage } from "./features/AllUsersPage";
import { AppShell, type WorkspacePage } from "./components/AppShell";
import { ClientDetailPage } from "./features/ClientDetailPage";
import { ClinicSettingsPage } from "./features/ClinicSettingsPage";
import { DashboardPage } from "./features/DashboardPage";
import { ClientManagementPage } from "./features/ClientManagementPage";
import { LoginScreen } from "./features/LoginScreen";
import { OrganizationUsersPage } from "./features/OrganizationUsersPage";
import { PatientsPage } from "./features/PatientsPage";
import { PublicBookingPage } from "./features/PublicBookingPage";
import { ReportsPage } from "./features/ReportsPage";
import { SchedulePage } from "./features/SchedulePage";
import { SafetyPage } from "./features/SafetyPage";
import { SuperAdminAdministrationPage } from "./features/SuperAdminAdministrationPage";
import { SuperAdminHomePage } from "./features/SuperAdminHomePage";

const TENANT_PAGES: WorkspacePage[] = ["schedule", "patients", "safety", "users", "clinic-settings", "reports"];

function pageFromHash(): WorkspacePage {
  const value = window.location.hash.replace("#", "").split("/")[0];
  return (TENANT_PAGES as string[]).includes(value) || value === "clients" || value === "admin-hub"
    ? (value as WorkspacePage)
    : "dashboard";
}

function invitationTokenFromLocation(): string | null {
  const segments = window.location.pathname.split("/").filter(Boolean);
  if (segments.length < 2 || segments[segments.length - 1] !== "activate") return null;
  return new URLSearchParams(window.location.search).get("token");
}

function bookingSlugFromLocation(): string | null {
  const segments = window.location.pathname.split("/").filter(Boolean);
  if (segments.length < 2 || segments[0] !== "book") return null;
  return segments[1];
}

function clientNumberFromHash(): number | null {
  const segments = window.location.hash.replace("#", "").split("/");
  if (segments[0] !== "clients" || !segments[1]) return null;
  const parsed = Number(segments[1]);
  return Number.isInteger(parsed) ? parsed : null;
}

export default function App() {
  const [user, setUser] = useState<WorkspaceUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState<WorkspacePage>(pageFromHash);
  const [selectedClientNumber, setSelectedClientNumber] = useState<number | null>(clientNumberFromHash);
  const [invitationToken, setInvitationToken] = useState<string | null>(invitationTokenFromLocation);
  const [error, setError] = useState("");

  useEffect(() => {
    const syncPageFromHash = () => {
      setPage(pageFromHash());
      setSelectedClientNumber(clientNumberFromHash());
    };
    window.addEventListener("hashchange", syncPageFromHash);
    syncPageFromHash();
    return () => window.removeEventListener("hashchange", syncPageFromHash);
  }, []);

  useEffect(() => {
    let active = true;
    api.me()
      .then((sessionUser) => active && setUser(sessionUser))
      .catch((requestError) => {
        if (active && (!(requestError instanceof ApiError) || requestError.status !== 401)) {
          setError(requestError instanceof ApiError ? requestError.message : "Unable to connect to the Django backend.");
        }
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  function navigate(nextPage: WorkspacePage) {
    setPage(nextPage);
    window.location.hash = nextPage === "dashboard" ? "" : nextPage;
  }

  async function logout() {
    try {
      await api.logout();
    } finally {
      setUser(null);
      navigate("dashboard");
    }
  }

  const bookingSlug = bookingSlugFromLocation();
  if (bookingSlug) {
    return <PublicBookingPage slug={bookingSlug} />;
  }
  if (invitationToken) {
    return (
      <ActivateInvitationPage
        token={invitationToken}
        onActivated={(activatedUser) => {
          window.history.replaceState(null, "", "/");
          setInvitationToken(null);
          setUser(activatedUser);
        }}
      />
    );
  }
  if (loading) {
    return <main className="app-loading">Connecting to the protected workspace…</main>;
  }
  if (!user) {
    return <><LoginScreen onAuthenticated={setUser} />{error && <p className="app-connection-error" role="alert">{error}</p>}</>;
  }

  const visiblePage = user.capabilities.isSuperAdmin
    ? (["users", "clients", "dashboard", "admin-hub"].includes(page) ? page : "dashboard")
    : page === "schedule" && !user.capabilities.canManageSchedule
      ? "dashboard"
      : page === "safety" && !user.capabilities.canReviewAudit
        ? "dashboard"
        : page === "users" && !user.capabilities.canManageAccess
          ? "dashboard"
          : (page === "clinic-settings" || page === "reports") && user.role !== "admin"
            ? "dashboard"
            : page === "clients"
              ? "dashboard"
              : page;

  // The Home landing page (Super Admin and org-admin) is a standalone,
  // sidebar-free page — like the login screen — not a page inside AppShell.
  // Every other page keeps the persistent sidebar shell.
  if (visiblePage === "dashboard" && user.capabilities.isSuperAdmin) {
    return <SuperAdminHomePage user={user} onNavigate={navigate} onLogout={() => void logout()} />;
  }
  if (visiblePage === "admin-hub" && user.capabilities.isSuperAdmin) {
    return <SuperAdminAdministrationPage user={user} onNavigate={navigate} onLogout={() => void logout()} />;
  }
  if (visiblePage === "dashboard" && user.role === "admin") {
    return <AdminHomePage user={user} onNavigate={navigate} onLogout={() => void logout()} />;
  }

  return <AppShell user={user} page={visiblePage} onNavigate={navigate} onLogout={() => void logout()}>
    {visiblePage === "dashboard" && <DashboardPage />}
    {visiblePage === "patients" && <PatientsPage user={user} />}
    {visiblePage === "schedule" && <SchedulePage user={user} />}
    {visiblePage === "safety" && <SafetyPage />}
    {visiblePage === "users" && (user.capabilities.isSuperAdmin ? <AllUsersPage /> : <OrganizationUsersPage currentUserId={user.id} />)}
    {visiblePage === "clinic-settings" && <ClinicSettingsPage />}
    {visiblePage === "reports" && <ReportsPage />}
    {visiblePage === "clients" && (
      selectedClientNumber === null
        ? <ClientManagementPage />
        : <ClientDetailPage clientNumber={selectedClientNumber} onBack={() => navigate("clients")} />
    )}
  </AppShell>;
}
