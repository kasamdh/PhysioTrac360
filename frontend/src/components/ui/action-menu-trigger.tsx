import * as React from "react";
import { ChevronDown, Menu } from "lucide-react";

import { cn } from "@/lib/utils";

export const ActionMenuTrigger = React.forwardRef<HTMLButtonElement, React.ButtonHTMLAttributes<HTMLButtonElement>>(
  ({ className, ...props }, ref) => (
    <button
      ref={ref}
      type="button"
      className={cn(
        "flex items-center gap-2.5 rounded-2xl border-0 bg-white px-3.5 py-2.5 text-[#2b3542] shadow-[0_1px_2px_rgb(15_23_42_/_8%),0_6px_14px_rgb(15_23_42_/_10%)] transition-shadow hover:shadow-[0_2px_4px_rgb(15_23_42_/_10%),0_8px_18px_rgb(15_23_42_/_14%)]",
        className,
      )}
      {...props}
    >
      <Menu className="h-4 w-4" strokeWidth={2.5} />
      <span className="h-4 w-px bg-border" />
      <ChevronDown className="h-4 w-4" strokeWidth={2.5} />
    </button>
  ),
);
ActionMenuTrigger.displayName = "ActionMenuTrigger";
