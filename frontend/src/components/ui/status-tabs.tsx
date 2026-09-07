import { cn } from "@/lib/utils";

export interface StatusTabOption {
  value: string;
  label: string;
}

interface StatusTabsProps {
  tabs: StatusTabOption[];
  value: string;
  onChange: (value: string) => void;
}

export function StatusTabs({ tabs, value, onChange }: StatusTabsProps) {
  return (
    <div className="flex flex-wrap gap-1 rounded-lg border border-border bg-white p-1">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          type="button"
          onClick={() => onChange(tab.value)}
          className={cn(
            "rounded-md border-0 bg-transparent px-4 py-2 text-sm font-semibold transition-colors",
            value === tab.value
              ? "bg-primary text-primary-foreground shadow-sm"
              : "text-primary-deep hover:bg-muted",
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
