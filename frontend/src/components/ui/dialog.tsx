import type { ReactNode } from "react";
import { X } from "lucide-react";

interface DialogProps {
  eyebrow?: string;
  title: ReactNode;
  titleId: string;
  onClose: () => void;
  busy?: boolean;
  maxWidth?: string;
  children: ReactNode;
}

export function Dialog({ eyebrow, title, titleId, onClose, busy, maxWidth = "max-w-2xl", children }: DialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`relative w-full ${maxWidth} max-h-[90vh] overflow-y-auto rounded-lg bg-white shadow-2xl`}
      >
        <button
          type="button"
          onClick={onClose}
          disabled={busy}
          aria-label="Close"
          className="absolute right-5 top-5 border-0 bg-transparent p-1 text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          <X className="h-5 w-5" />
        </button>
        <header className="border-b border-border px-8 pb-5 pt-8">
          {eyebrow && <p className="m-0 mb-1 text-xs font-bold uppercase tracking-wider text-primary-deep">{eyebrow}</p>}
          <h2 id={titleId} className="m-0 pr-8 text-2xl font-semibold text-foreground">{title}</h2>
        </header>
        <div className="px-8 py-6">{children}</div>
      </section>
    </div>
  );
}

export function DialogFooter({ children }: { children: ReactNode }) {
  return <div className="-mx-8 mt-6 flex items-center justify-end gap-3 border-t border-border px-8 pt-5">{children}</div>;
}

interface FormRowProps {
  label: ReactNode;
  htmlFor?: string;
  children: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
}

export function FormRow({ label, htmlFor, children, hint, error }: FormRowProps) {
  return (
    <div className="grid grid-cols-[160px_1fr] items-start gap-x-4 gap-y-1 py-2.5 max-[560px]:grid-cols-1 max-[560px]:gap-y-1.5">
      <label htmlFor={htmlFor} className="pt-2.5 text-right text-[0.9375rem] font-semibold text-foreground max-[560px]:pt-0 max-[560px]:text-left">
        {label}
      </label>
      <div className="min-w-0">
        {children}
        {error && <div className="mt-1 text-xs font-medium text-destructive">{error}</div>}
        {!error && hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
      </div>
    </div>
  );
}
