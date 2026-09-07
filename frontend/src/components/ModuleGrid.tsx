import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type ModuleTone = "crimson" | "teal" | "blue" | "amber" | "purple" | "green";

export interface ModuleTileConfig<TKey extends string = string> {
  key: TKey;
  label: string;
  description: string;
  icon: ReactNode;
  tone: ModuleTone;
}

const TONE_CLASSES: Record<ModuleTone, string> = {
  crimson: "bg-[#fce9ee] text-[#a11d3d]",
  teal: "bg-primary-soft text-primary-deep",
  blue: "bg-[#e6f0fb] text-[#2b5f9e]",
  amber: "bg-[#fff2d8] text-[#9b6908]",
  purple: "bg-[#f1ecff] text-[#5c4eb3]",
  green: "bg-[#e8f6ec] text-[#26714f]",
};

interface ModuleGridProps<TKey extends string> {
  modules: ModuleTileConfig<TKey>[];
  onSelect: (key: TKey) => void;
  ariaLabel: string;
}

export function ModuleGrid<TKey extends string>({ modules, onSelect, ariaLabel }: ModuleGridProps<TKey>) {
  return (
    <nav
      aria-label={ariaLabel}
      className="mb-10 grid grid-cols-1 gap-x-8 gap-y-5 min-[901px]:grid-cols-2"
    >
      {modules.map((module) => (
        <button
          key={module.key}
          type="button"
          onClick={() => onSelect(module.key)}
          className="group flex min-h-[110px] items-center gap-4 rounded-[14px] border border-border bg-white p-4 text-left transition-all hover:border-primary hover:bg-[#fbfdfd] hover:shadow-[0_10px_22px_rgb(15_23_42_/_7%)] hover:-translate-y-px max-[620px]:gap-4 max-[620px]:p-3"
        >
          <span
            className={cn(
              "grid h-[92px] w-[92px] shrink-0 place-items-center rounded-[20px] [&_svg]:h-11 [&_svg]:w-11",
              "max-[900px]:h-20 max-[900px]:w-20 max-[900px]:[&_svg]:h-[38px] max-[900px]:[&_svg]:w-[38px]",
              "max-[620px]:h-[68px] max-[620px]:w-[68px] max-[620px]:rounded-2xl max-[620px]:[&_svg]:h-8 max-[620px]:[&_svg]:w-8",
              TONE_CLASSES[module.tone],
            )}
          >
            {module.icon}
          </span>
          <span className="grid min-w-0 gap-1">
            <strong className="text-2xl font-semibold tracking-[-0.01em] text-[#202c3f] transition-colors group-hover:text-primary-deep max-[900px]:text-[1.375rem] max-[620px]:text-xl">
              {module.label}
            </strong>
            <small className="text-base leading-snug text-[#667085] max-[620px]:text-[0.9375rem]">
              {module.description}
            </small>
          </span>
        </button>
      ))}
    </nav>
  );
}
