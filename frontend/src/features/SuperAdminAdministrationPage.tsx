import type { WorkspaceUser } from "../api/types";
import type { WorkspacePage } from "../components/AppShell";
import { HomeTopBar } from "../components/HomeTopBar";

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
  const items: AdminMenuItem[] = [
    { label: "Clients", action: () => onNavigate("clients") },
    { label: "Users", action: () => onNavigate("users") },
    { label: "Credentials", action: () => onNavigate("credentials") },
    { label: "Mobile Care Defaults", action: () => onNavigate("mobile-care-platform-defaults") },
  ];

  return (
    <div className="flex min-h-screen flex-col bg-white">
      <HomeTopBar
        user={user}
        onLogout={onLogout}
        onHome={() => onNavigate("dashboard")}
        pageLabel="Administration"
        brandLabel="Source Motion PT"
      />
      <div className="mx-auto flex w-full max-w-[1040px] flex-1 flex-col px-6 pt-10">
        <nav aria-label="Administration" className="my-10 grid grid-cols-1 gap-x-6 gap-y-[1.1rem] min-[621px]:grid-cols-2 max-[620px]:my-6">
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              onClick={item.action}
              className="min-h-[76px] rounded-[10px] border-0 bg-gradient-to-br from-primary to-primary-deep px-6 py-[0.9rem] text-center text-[1.25rem] font-semibold text-white shadow-[0_8px_18px_rgb(176_0_32_/_18%)] transition-all hover:brightness-[1.06] hover:-translate-y-px hover:shadow-[0_12px_22px_rgb(176_0_32_/_24%)] max-[620px]:min-h-16 max-[620px]:text-lg"
            >
              {item.label}
            </button>
          ))}
        </nav>

        <footer className="mt-auto flex justify-center gap-[0.6rem] border-t border-[#ece5df] py-6 text-sm text-[#97a0a8]">
          <span>v1.0</span>
          <span>&copy; {new Date().getFullYear()} Source Motion Physical Therapy LLC. All rights reserved.</span>
        </footer>
      </div>
    </div>
  );
}
