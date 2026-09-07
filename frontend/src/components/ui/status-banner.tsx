import type { ReactNode } from "react";
import { Ban, CheckCircle2, Lock, PauseCircle, Trash2 } from "lucide-react";

import type { ManagedClientUser, UserAccountStatus } from "@/api/types";
import { formatDateTime } from "../../lib/format";
import { cn } from "@/lib/utils";

interface StatusConfig {
  label: string;
  icon: ReactNode;
  badgeClasses: string;
  panelClasses: string;
}

const STATUS_CONFIG: Record<UserAccountStatus, StatusConfig> = {
  active: {
    label: "Active",
    icon: <CheckCircle2 className="h-4 w-4" aria-hidden="true" />,
    badgeClasses: "bg-emerald-100 text-emerald-800",
    panelClasses: "border-emerald-200 bg-emerald-50",
  },
  inactive: {
    label: "Inactive",
    icon: <PauseCircle className="h-4 w-4" aria-hidden="true" />,
    badgeClasses: "bg-muted text-muted-foreground",
    panelClasses: "border-border bg-muted/40",
  },
  locked_out: {
    label: "Locked Out",
    icon: <Lock className="h-4 w-4" aria-hidden="true" />,
    badgeClasses: "bg-amber-100 text-amber-800",
    panelClasses: "border-amber-200 bg-amber-50",
  },
  suspended: {
    label: "Suspended",
    icon: <Ban className="h-4 w-4" aria-hidden="true" />,
    badgeClasses: "bg-red-100 text-red-800",
    panelClasses: "border-red-200 bg-red-50",
  },
  deleted: {
    label: "Deleted",
    icon: <Trash2 className="h-4 w-4" aria-hidden="true" />,
    badgeClasses: "bg-slate-200 text-slate-800",
    panelClasses: "border-slate-300 bg-slate-100",
  },
};

function remainingMinutes(until: string): string {
  const ms = new Date(until).getTime() - Date.now();
  const minutes = Math.max(0, Math.round(ms / 60000));
  if (minutes < 1) return "less than a minute";
  return `${minutes} minute${minutes === 1 ? "" : "s"}`;
}

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between gap-4 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium text-foreground">{value}</span>
    </div>
  );
}

export function StatusBadge({ status }: { status: UserAccountStatus }) {
  const config = STATUS_CONFIG[status];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wide", config.badgeClasses)}>
      {config.icon}
      {config.label}
    </span>
  );
}

interface StatusBannerProps {
  user: ManagedClientUser;
}

export function StatusBanner({ user }: StatusBannerProps) {
  const config = STATUS_CONFIG[user.status];

  if (user.status === "active") {
    return (
      <div className="mb-6">
        <StatusBadge status="active" />
        <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 max-w-sm">
          <DetailRow label="Last Login" value={user.lastLogin ? formatDateTime(user.lastLogin) : "Never"} />
          <DetailRow label="MFA" value={user.mustUseMfa ? "Enabled" : "Disabled"} />
        </div>
      </div>
    );
  }

  let description = "";
  let details: ReactNode = null;

  if (user.status === "inactive") {
    description = "This user is currently inactive and cannot sign in.";
    details = (
      <>
        <DetailRow label="Inactive Since" value={user.statusChangedAt ? formatDateTime(user.statusChangedAt) : "Unknown"} />
        {user.statusChangedBy && <DetailRow label="Changed By" value={user.statusChangedBy} />}
      </>
    );
  } else if (user.status === "locked_out") {
    description = "This user cannot currently sign in because the account has been temporarily locked after multiple unsuccessful login attempts.";
    details = (
      <>
        <DetailRow label="Failed Attempts" value={user.failedLoginAttempts} />
        {user.lockedAt && <DetailRow label="Locked At" value={formatDateTime(user.lockedAt)} />}
        {user.lockedUntil && <DetailRow label="Unlocks At" value={formatDateTime(user.lockedUntil)} />}
        {user.lockedUntil && <DetailRow label="Remaining Lockout" value={remainingMinutes(user.lockedUntil)} />}
      </>
    );
  } else if (user.status === "suspended") {
    description = user.suspendedBy
      ? "This account has been suspended by an administrator and cannot access the EMR."
      : "This account was automatically suspended because its PT/PTA license expired, and cannot access the EMR.";
    details = (
      <>
        {user.suspendedAt && <DetailRow label="Suspended At" value={formatDateTime(user.suspendedAt)} />}
        {user.suspendedBy && <DetailRow label="Suspended By" value={user.suspendedBy} />}
        {user.suspensionReason && <DetailRow label="Reason" value={user.suspensionReason} />}
      </>
    );
  } else if (user.status === "deleted") {
    description = "This account has been deleted and cannot sign in. Historical records and audit information are retained.";
    details = (
      <>
        {user.archivedAt && <DetailRow label="Deleted At" value={formatDateTime(user.archivedAt)} />}
        {user.archivedBy && <DetailRow label="Deleted By" value={user.archivedBy} />}
      </>
    );
  }

  return (
    <div className={cn("mb-6 rounded-lg border p-4", config.panelClasses)}>
      <StatusBadge status={user.status} />
      <p className="mt-2 mb-3 text-sm font-medium text-foreground">{description}</p>
      <div className="grid max-w-sm gap-1">{details}</div>
    </div>
  );
}
