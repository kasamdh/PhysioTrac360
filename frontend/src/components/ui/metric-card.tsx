import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type MetricTone = "neutral" | "crimson" | "green" | "amber" | "blue";

const TONE_VALUE_CLASSES: Record<MetricTone, string> = {
  neutral: "text-[#1c1f23]",
  crimson: "text-primary-deep",
  green: "text-[#1f7a4d]",
  amber: "text-[#9b6908]",
  blue: "text-[#2b5f9e]",
};

interface MetricCardProps {
  label: string;
  value: ReactNode;
  detail?: string;
  tone?: MetricTone;
  onClick?: () => void;
}

/** A single clickable (when `onClick` is given) stat tile — the building
 * block of the Super Admin dashboard's metric grid. Reusable anywhere a
 * page needs a "count + label, optionally linking somewhere" tile. */
export function MetricCard({ label, value, detail, tone = "neutral", onClick }: MetricCardProps) {
  const content = (
    <>
      <span className="text-sm font-semibold text-[#6B7280]">{label}</span>
      <strong className={cn("text-[2rem] font-bold leading-none tracking-[-0.01em]", TONE_VALUE_CLASSES[tone])}>
        {value}
      </strong>
      {detail && <span className="text-[0.8125rem] text-[#6B7280]">{detail}</span>}
    </>
  );

  const className = "grid gap-1.5 rounded-[14px] border border-border bg-white p-4 text-left transition-all";

  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={cn(className, "cursor-pointer hover:border-primary hover:shadow-[0_10px_22px_rgb(15_23_42_/_7%)] hover:-translate-y-px")}
      >
        {content}
      </button>
    );
  }
  return <div className={className}>{content}</div>;
}
