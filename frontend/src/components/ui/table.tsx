import * as React from "react";

import { cn } from "@/lib/utils";

export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-white">
      <div className="overflow-x-auto">
        <table className={cn("w-full border-collapse text-sm", className)} {...props} />
      </div>
    </div>
  );
}

export function TableHeader({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={className} {...props} />;
}

export function TableBody({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn("divide-y divide-border", className)} {...props} />;
}

export function TableHeaderRow({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn(
        "border-b border-border bg-muted/50 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

export function TableRow({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("hover:bg-muted/30", className)} {...props} />;
}

export function TableHead({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={cn("px-4 py-3", className)} {...props} />;
}

export function TableCell({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("px-4 py-3", className)} {...props} />;
}

export function TableEmpty({ children }: { children: React.ReactNode }) {
  return <p className="px-4 py-10 text-center text-sm text-muted-foreground">{children}</p>;
}
