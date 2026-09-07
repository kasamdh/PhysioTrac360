import { cn } from "@/lib/utils";

export interface SegmentOption {
  value: string;
  label: string;
}

interface SegmentedControlProps {
  options: SegmentOption[];
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

export function SegmentedControl({ options, value, onChange, disabled }: SegmentedControlProps) {
  return (
    <div className="inline-flex h-[54px] overflow-hidden rounded-md border border-input">
      {options.map((option, index) => (
        <button
          key={option.value}
          type="button"
          disabled={disabled}
          onClick={() => onChange(option.value)}
          className={cn(
            "border-0 bg-white px-5 text-[0.9375rem] font-semibold text-primary-deep transition-colors disabled:cursor-not-allowed disabled:opacity-60",
            index > 0 && "border-l border-input",
            value === option.value
              ? "bg-primary text-primary-foreground hover:bg-primary"
              : "hover:bg-muted",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
