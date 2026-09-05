import * as React from "react";

import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "flex h-[54px] w-full rounded-md border-0 bg-white px-4 text-[1.125rem] text-foreground shadow-[inset_0_0_0_1px_var(--color-input)] outline-none placeholder:text-[#8b96a3] focus:shadow-[inset_0_0_0_1.5px_var(--color-primary)] focus:outline focus:outline-3 focus:outline-primary/28 disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";
