import { Check, Circle } from "lucide-react";

import { cn } from "@/lib/utils";

export interface DocumentationSection {
  key: string;
  label: string;
  complete: boolean;
}

interface SectionNavProps {
  sections: DocumentationSection[];
  activeKey: string;
  onSelect: (key: string) => void;
}

export function SectionNav({ sections, activeKey, onSelect }: SectionNavProps) {
  return (
    <nav aria-label="Documentation sections" className="grid gap-0.5">
      {sections.map((section) => {
        const isActive = section.key === activeKey;
        return (
          <button
            key={section.key}
            type="button"
            onClick={() => onSelect(section.key)}
            className={cn(
              "flex items-center gap-2 rounded-md border-0 px-3 py-2.5 text-left text-sm font-medium",
              isActive ? "bg-primary-soft/60 text-primary-deep" : "bg-transparent text-foreground hover:bg-muted/50",
            )}
          >
            {section.complete ? (
              <Check className="h-4 w-4 shrink-0 text-emerald-600" aria-hidden="true" />
            ) : (
              <Circle className={cn("h-4 w-4 shrink-0", isActive ? "text-primary-deep" : "text-muted-foreground")} aria-hidden="true" />
            )}
            {section.label}
          </button>
        );
      })}
    </nav>
  );
}
