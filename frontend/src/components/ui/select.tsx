import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const selectVariants = cva(
  "rounded-md border-0 bg-white text-foreground shadow-[inset_0_0_0_1px_var(--color-input)] outline-none focus:shadow-[inset_0_0_0_1.5px_var(--color-primary)] disabled:cursor-not-allowed disabled:opacity-50",
  {
    variants: {
      uiSize: {
        // Matches the filter-bar select convention already used on list pages
        // (AllUsersPage/ClientManagementPage).
        sm: "h-10 border border-input px-3 text-sm shadow-none",
        // Matches the form-row select convention already used in Edit/Create dialogs.
        default: "flex h-[54px] w-full px-4 text-[1.0625rem]",
      },
    },
    defaultVariants: { uiSize: "default" },
  },
);

export interface SelectProps
  extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "size">,
    VariantProps<typeof selectVariants> {}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(({ className, uiSize, ...props }, ref) => (
  <select ref={ref} className={cn(selectVariants({ uiSize }), className)} {...props} />
));
Select.displayName = "Select";
