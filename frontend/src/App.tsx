import { useEffect, useState } from "react";

import { ApiError, api } from "./api/client";
import type { WorkspaceUser } from "./api/types";
import { ActivateInvitationPage } from "./features/ActivateInvitationPage";
import { AdminHomePage } from "./features/AdminHomePage";
import { AllUsersPage } from "./features/AllUsersPage";
import { AppShell, type WorkspacePage } from "./components/AppShell";
import { ClientDetailPage } from "./features/ClientDetailPage";
import { ClinicSettingsPage } from "./features/ClinicSettingsPage";
import { CredentialDashboardPage } from "./features/CredentialDashboardPage";
import { DashboardPage } from "./features/DashboardPage";
import { ClientManagementPage } from "./features/ClientManagementPage";
import { DocumentationPage } from "./features/documentation/DocumentationPage";
import { DocumentationWorkspace } from "./features/documentation/DocumentationWorkspace";
import { ForcedPasswordChangeDialog } from "./features/ForcedPasswordChangeDialog";
import { LoginScreen } from "./features/LoginScreen";
import { OrganizationUsersPage } from "./features/OrganizationUsersPage";
import { PatientsPage } from "./features/PatientsPage";
import { PortalAppointmentsPage } from "./features/portal/PortalAppointmentsPage";
import { PortalBookingPage } from "./features/portal/PortalBookingPage";
import { PortalDashboardPage } from "./features/portal/PortalDashboardPage";
import { PortalDocumentsPage } from "./features/portal/PortalDocumentsPage";
import { PortalFormsSection } from "./features/portal/PortalFormsSection";
import { PortalHepPage } from "./features/portal/PortalHepPage";
import { PortalMessagesPage } from "./features/portal/PortalMessagesPage";
import { PortalOutcomesSection } from "./features/portal/PortalOutcomesSection";
import { PortalPaymentsPage } from "./features/portal/PortalPaymentsPage";
import { PortalProfilePage } from "./features/portal/PortalProfilePage";
import { PortalShell, type PortalPage } from "./features/portal/PortalShell";
import { PortalWaitlistPage } from "./features/portal/PortalWaitlistPage";
import { PublicBookingPage } from "./features/PublicBookingPage";
import { ReportsPage } from "./features/ReportsPage";
import { SchedulePage } from "./features/SchedulePage";
import { SafetyPage } from "./features/SafetyPage";
import { SuperAdminAdministrationPage } from "./features/SuperAdminAdministrationPage";
import { SuperAdminHomePage } from "./features/SuperAdminHomePage";
import { onSessionEnded } from "./lib/sessionEvents";

const TENANT_PAGES: WorkspacePage[] = ["schedule", "patients", "documentation", "safety", "users", "clinic-settings", "reports"];

function pageFromHash(): WorkspacePage {
  const value = window.location.hash.replace("#", "").split("/")[0];
  return (TENANT_PAGES as string[]).includes(value) || value === "clients" || value === "admin-hub" || value === "credentials"
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

function documentationParamsFromHash(): { patientId: string; noteId: string } | null {
  const segments = window.location.hash.replace("#", "").split("/");
  if (segments[0] !== "documentation" || !segments[1] || !segments[2]) return null;
  return { patientId: segments[1], noteId: segments[2] };
}

export default function App() {
  const [user, setUser] = useState<WorkspaceUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState<WorkspacePage>(pageFromHash);
  const [selectedClientNumber, setSelectedClientNumber] = useState<number | null>(clientNumberFromHash);
  const [documentationParams, setDocumentationParams] = useState<{ patientId: string; noteId: string } | null>(documentationParamsFromHash);
  const [invitationToken, setInvitationToken] = useState<string | null>(invitationTokenFromLocation);
  const [error, setError] = useState("");
  const [sessionNotice, setSessionNotice] = useState("");
  const [portalPage, setPortalPage] = useState<PortalPage>("dashboard");

  useEffect(() => {
    return onSessionEnded((message) => {
      // The session is already dead server-side (or in another tab) —
      // just drop everything sensitive from memory and show why.
      setUser(null);
      setSessionNotice(message);
    });
  }, []);

  useEffect(() => {
    const syncPageFromHash = () => {
      setPage(pageFromHash());
      setSelectedClientNumber(clientNumberFromHash());
      setDocumentationParams(documentationParamsFromHash());
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

  function openDocumentationNote(patientId: string, noteId: string) {
    setPage("documentation");
    setDocumentationParams({ patientId, noteId });
    window.location.hash = `documentation/${patientId}/${noteId}`;
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
    return (
      <>
        <LoginScreen onAuthenticated={(nextUser) => { setSessionNotice(""); setUser(nextUser); }} noticeMessage={sessionNotice} />
        {error && <p className="app-connection-error" role="alert">{error}</p>}
      </>
    );
  }
  if (user.mustChangePassword) {
    return <ForcedPasswordChangeDialog user={user} onChanged={setUser} onLogout={() => void logout()} />;
  }

  // Patients get a completely separate, much simpler shell — never the
  // staff AppShell, sidebar, or any of the tenant-page routing below.
  if (user.capabilities.isPatient) {
    return (
      <PortalShell user={user} page={portalPage} onNavigate={setPortalPage} onLogout={() => void logout()}>
        {portalPage === "dashboard" && <PortalDashboardPage onNavigate={setPortalPage} />}
        {portalPage === "appointments" && <PortalAppointmentsPage />}
        {portalPage === "book" && <PortalBookingPage onBooked={() => setPortalPage("appointments")} />}
        {portalPage === "forms" && <PortalFormsSection />}
        {portalPage === "documents" && <PortalDocumentsPage />}
        {portalPage === "hep" && <PortalHepPage />}
        {portalPage === "outcomes" && <PortalOutcomesSection />}
        {portalPage === "messages" && <PortalMessagesPage />}
        {portalPage === "payments" && <PortalPaymentsPage />}
        {portalPage === "profile" && <PortalProfilePage />}
        {portalPage === "waitlist" && <PortalWaitlistPage />}
      </PortalShell>
    );
  }

  const visiblePage = user.capabilities.isSuperAdmin
    ? (["users", "clients", "dashboard", "admin-hub", "credentials"].includes(page) ? page : "dashboard")
    : page === "schedule" && !user.capabilities.canManageSchedule
      ? "dashboard"
      : page === "documentation" && !user.capabilities.canAccessClinical
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
    {visiblePage === "documentation" && (
      documentationParams
        ? (
          <DocumentationWorkspace
            key={documentationParams.noteId}
            patientId={documentationParams.patientId}
            noteId={documentationParams.noteId}
            user={user}
            onBack={() => navigate("documentation")}
          />
        )
        : <DocumentationPage user={user} onOpenNote={openDocumentationNote} />
    )}
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
    {visiblePage === "credentials" && <CredentialDashboardPage />}
  </AppShell>;
}
