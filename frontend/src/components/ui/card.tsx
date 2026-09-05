import * as React from "react";

import { cn } from "@/lib/utils";

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        "grid w-full gap-[1.1rem] rounded-[10px] bg-[#d8dedc] p-9 shadow-[0_18px_40px_rgb(15_23_42_/_12%)]",
        className,
      )}
      {...props}
    />
  ),
);
Card.displayName = "Card";
