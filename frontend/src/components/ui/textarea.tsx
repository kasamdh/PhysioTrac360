import * as React from "react";

import { cn } from "@/lib/utils";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "flex min-h-[90px] w-full rounded-md border-0 bg-white px-4 py-3 text-[1.0625rem] text-foreground shadow-[inset_0_0_0_1px_var(--color-input)] outline-none placeholder:text-[#8b96a3] focus:shadow-[inset_0_0_0_1.5px_var(--color-primary)] disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";
