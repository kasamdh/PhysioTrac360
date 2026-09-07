import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold whitespace-nowrap", {
  variants: {
    tone: {
      neutral: "bg-muted text-muted-foreground",
      success: "bg-emerald-100 text-emerald-700",
      warning: "bg-amber-100 text-amber-700",
      danger: "bg-red-100 text-red-700",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
