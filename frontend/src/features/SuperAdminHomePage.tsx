import type { WorkspaceUser } from "../api/types";
import type { WorkspacePage } from "../components/AppShell";
import { HomeTopBar } from "../components/HomeTopBar";
import { ModuleGrid, type ModuleTileConfig } from "../components/ModuleGrid";

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

const MODULES: ModuleTileConfig<WorkspacePage>[] = [
  {
    key: "admin-hub",
    label: "Administration",
    description: "Manage clients, platform users, and account settings.",
    icon: <IconAdministration />,
    tone: "purple",
  },
];

export function SuperAdminHomePage({ user, onNavigate, onLogout }: SuperAdminHomePageProps) {
  return (
    <div className="flex min-h-screen flex-col bg-white">
      <HomeTopBar user={user} onLogout={onLogout} onHome={() => onNavigate("dashboard")} brandLabel="PhysioTrac360" />
      <div className="mx-auto flex w-full max-w-[1040px] flex-1 flex-col px-6 pt-10">
        <header className="mb-7 text-center">
          <h1 className="m-0 text-[clamp(1.75rem,3vw,2.125rem)] font-bold tracking-[-0.02em] text-[#172127]">
            PhysioTrac360 Platform
          </h1>
        </header>

        <ModuleGrid modules={MODULES} onSelect={onNavigate} ariaLabel="Platform administration modules" />

        <footer className="mt-auto flex justify-center gap-[0.6rem] border-t border-[#ece5df] py-6 text-sm text-[#97a0a8]">
          <span>v1.0</span>
          <span>&copy; {new Date().getFullYear()} PhysioTrac360</span>
        </footer>
      </div>
    </div>
  );
}
