import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, ShieldAlert, TriangleAlert } from "lucide-react";

import type { LicenseAlertStatus, UserLicenseInfo } from "@/api/types";
import { formatDate } from "../../lib/format";
import { cn } from "@/lib/utils";

interface LicenseConfig {
  label: string;
  icon: ReactNode;
  badgeClasses: string;
  panelClasses: string;
}

const LICENSE_CONFIG: Record<Exclude<LicenseAlertStatus, "none">, LicenseConfig> = {
  valid: {
    label: "License Valid",
    icon: <CheckCircle2 className="h-4 w-4" aria-hidden="true" />,
    badgeClasses: "bg-emerald-100 text-emerald-800",
    panelClasses: "border-emerald-200 bg-emerald-50",
  },
  expiring_soon: {
    label: "Expiring Soon",
    icon: <AlertTriangle className="h-4 w-4" aria-hidden="true" />,
    badgeClasses: "bg-amber-100 text-amber-800",
    panelClasses: "border-amber-200 bg-amber-50",
  },
  critical: {
    label: "Renew Urgently",
    icon: <TriangleAlert className="h-4 w-4" aria-hidden="true" />,
    badgeClasses: "bg-orange-100 text-orange-800",
    panelClasses: "border-orange-200 bg-orange-50",
  },
  expired: {
    label: "License Expired",
    icon: <ShieldAlert className="h-4 w-4" aria-hidden="true" />,
    badgeClasses: "bg-red-100 text-red-800",
    panelClasses: "border-red-200 bg-red-50",
  },
};

const TIER_MESSAGES: Record<string, string> = {
  expiring_90: "This license expires in 90 days.",
  expiring_60: "This license expires in 60 days.",
  expiring_30: "This license expires in 30 days.",
  critical_14: "This license expires in 14 days.",
  critical_7: "This license expires in 7 days.",
};

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between gap-4 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium text-foreground">{value}</span>
    </div>
  );
}

export function LicenseBadge({ status }: { status: LicenseAlertStatus }) {
  if (status === "none") return <span className="text-sm text-muted-foreground">—</span>;
  const config = LICENSE_CONFIG[status];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wide", config.badgeClasses)}>
      {config.icon}
      {config.label}
    </span>
  );
}

function licenseDescription(license: UserLicenseInfo): string {
  if (license.colorBucket === "expired") {
    return "This PT/PTA license has expired. The account was automatically suspended and cannot access the EMR until it is renewed.";
  }
  return (
    TIER_MESSAGES[license.alertTier] ??
    `This license expires in ${license.daysRemaining} day${license.daysRemaining === 1 ? "" : "s"}.`
  ) + " Renew it before it lapses to avoid an automatic suspension.";
}

interface LicenseBannerProps {
  licenses: UserLicenseInfo[];
}

export function LicenseBanner({ licenses }: LicenseBannerProps) {
  const flagged = licenses.filter((license) => license.colorBucket !== "valid");
  if (!flagged.length) return null;

  return (
    <>
      {flagged.map((license) => {
        const config = LICENSE_CONFIG[license.colorBucket];
        return (
          <div key={license.id} className={cn("mb-6 rounded-lg border p-4", config.panelClasses)}>
            <LicenseBadge status={license.colorBucket} />
            <p className="mt-2 mb-3 text-sm font-medium text-foreground">{licenseDescription(license)}</p>
            <div className="grid max-w-sm gap-1">
              <DetailRow label="License Number" value={license.licenseNumber} />
              <DetailRow label="Issuing State" value={license.issuingState} />
              <DetailRow label="Expires" value={formatDate(license.expiresAt)} />
            </div>
          </div>
        );
      })}
    </>
  );
}
