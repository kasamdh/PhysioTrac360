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
    <div className="flex min-h-screen flex-col bg-white">
      <HomeTopBar user={user} onLogout={onLogout} onHome={() => onNavigate("dashboard")} brandLabel="Source Motion PT" />
      <div className="mx-auto flex w-full max-w-[1040px] flex-1 flex-col px-6 pt-10">
        <header className="mb-7 text-center">
          <h1 className="m-0 text-[clamp(1.75rem,3vw,2.125rem)] font-bold tracking-[-0.02em] text-[#172127]">
            Source Motion PT
          </h1>
        </header>

        <nav aria-label="Platform administration modules" className="mb-10">
          <button
            type="button"
            onClick={() => onNavigate("admin-hub")}
            className="group flex min-h-[110px] w-full items-center gap-4 rounded-[14px] border-0 bg-gradient-to-br from-primary to-primary-deep p-4 text-left text-white shadow-[0_10px_20px_rgb(176_0_32_/_18%)] transition-all hover:brightness-105 hover:-translate-y-px"
          >
            <span className="grid h-[92px] w-[92px] shrink-0 place-items-center rounded-[20px] bg-white/15 text-white [&_svg]:h-11 [&_svg]:w-11 max-[900px]:h-20 max-[900px]:w-20 max-[900px]:[&_svg]:h-[38px] max-[900px]:[&_svg]:w-[38px]">
              <IconAdministration />
            </span>
            <span className="grid min-w-0 gap-1">
              <strong className="text-2xl font-semibold tracking-[-0.01em] text-white max-[900px]:text-[1.375rem]">
                Administration
              </strong>
              <small className="text-base leading-snug text-white/85 max-[620px]:text-[0.9375rem]">
                Manage clients, platform users, and account settings.
              </small>
            </span>
          </button>
        </nav>

        <footer className="mt-auto flex justify-center gap-[0.6rem] border-t border-[#ece5df] py-6 text-sm text-[#97a0a8]">
          <span>v1.0</span>
          <span>&copy; {new Date().getFullYear()} Source Motion Physical Therapy LLC. All rights reserved.</span>
        </footer>
      </div>
    </div>
  );
}
