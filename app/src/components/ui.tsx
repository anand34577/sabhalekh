import clsx from "clsx";
import { Check, ChevronDown, X } from "lucide-react";
import { type ButtonHTMLAttributes, type ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useStore } from "../store";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "subtle";

export function Button({ variant = "secondary", size = "md", icon, className, children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "lg"; icon?: ReactNode }) {
  return (
    <button
      {...rest}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors select-none",
        "disabled:opacity-45 disabled:pointer-events-none whitespace-nowrap",
        size === "sm" && "h-8 px-3 text-[0.82rem]",
        size === "md" && "h-9 px-3.5 text-[0.88rem]",
        size === "lg" && "h-11 px-5 text-[0.95rem]",
        variant === "primary" && "bg-accent text-accent-fg hover:brightness-110 active:brightness-95 shadow-sm",
        variant === "secondary" && "bg-card hover:bg-card-hover border border-stroke text-fg",
        variant === "ghost" && "hover:bg-card-hover text-fg-2 hover:text-fg",
        variant === "subtle" && "bg-accent-soft text-accent hover:brightness-110",
        variant === "danger" && "bg-danger text-white hover:brightness-110",
        className,
      )}
    >
      {icon}
      {children}
    </button>
  );
}

export function IconButton({ label, className, children, active, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean }) {
  return (
    <button
      {...rest}
      aria-label={label}
      title={label}
      className={clsx(
        "inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors text-fg-2",
        "hover:bg-card-hover hover:text-fg disabled:opacity-40 disabled:pointer-events-none",
        active && "bg-accent-soft text-accent",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Badge({ children, tone = "neutral", className }:
  { children: ReactNode; tone?: "neutral" | "accent" | "success" | "warning" | "danger" | "rec"; className?: string }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-[1px] text-[0.7rem] font-semibold tracking-wide",
        tone === "neutral" && "bg-card text-fg-2 border border-stroke",
        tone === "accent" && "bg-accent-soft text-accent",
        tone === "success" && "bg-success/15 text-success",
        tone === "warning" && "bg-warning/15 text-warning",
        tone === "danger" && "bg-danger/15 text-danger",
        tone === "rec" && "bg-rec/15 text-rec",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Toggle({ checked, onChange, label, description, disabled }:
  { checked: boolean; onChange: (v: boolean) => void; label: string; description?: string; disabled?: boolean }) {
  return (
    <label className={clsx("flex items-start justify-between gap-6 py-2.5", disabled && "opacity-50")}>
      <span>
        <span className="block text-[0.9rem]">{label}</span>
        {description && <span className="block text-[0.78rem] text-fg-3 mt-0.5">{description}</span>}
      </span>
      <button
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={clsx(
          "relative mt-0.5 h-5 w-10 shrink-0 rounded-full border transition-colors",
          checked ? "bg-accent border-accent" : "bg-transparent border-stroke-strong",
        )}
      >
        <span className={clsx("absolute top-[2px] h-3.5 w-3.5 rounded-full transition-all",
          checked ? "left-[22px] bg-white" : "left-[3px] bg-fg-2")} />
      </button>
    </label>
  );
}

export function Select<T extends string | number>({ value, onChange, options, label, className }:
  { value: T; onChange: (v: T) => void; options: { value: T; label: string; disabled?: boolean }[];
    label?: string; className?: string }) {
  return (
    <div className={clsx("relative", className)}>
      <select
        aria-label={label}
        value={String(value)}
        onChange={(e) => {
          const o = options.find((x) => String(x.value) === e.target.value);
          if (o) onChange(o.value);
        }}
        className="h-9 w-full appearance-none rounded-lg border border-stroke bg-card pl-3 pr-8 text-[0.86rem] text-fg
          hover:bg-card-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        {options.map((o) => (
          <option key={String(o.value)} value={String(o.value)} disabled={o.disabled} className="bg-layer-2">
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown size={15} className="pointer-events-none absolute right-2.5 top-2.5 text-fg-3" />
    </div>
  );
}

export interface MenuItem {
  label: string;
  icon?: ReactNode;
  onClick?: () => void;
  danger?: boolean;
  checked?: boolean;
  disabled?: boolean;
  separator?: boolean;
  hint?: string;
}

/** Dropdown menu anchored to its trigger, rendered in a portal, keyboard accessible. */
export function Menu({ trigger, items, align = "left", width = 220 }:
  { trigger: (open: () => void, isOpen: boolean) => ReactNode; items: MenuItem[]; align?: "left" | "right";
    width?: number }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const anchor = useRef<HTMLSpanElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const show = () => {
    const r = anchor.current?.getBoundingClientRect();
    if (r) {
      const x = align === "right" ? r.right - width : r.left;
      const y = r.bottom + 4;
      setPos({ x: Math.max(8, Math.min(x, window.innerWidth - width - 8)), y });
    }
    setOpen(true);
  };
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!menu.current?.contains(e.target as Node)) setOpen(false);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const btns = Array.from(menu.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);
        const i = btns.indexOf(document.activeElement as HTMLButtonElement);
        btns[(i + (e.key === "ArrowDown" ? 1 : -1) + btns.length) % btns.length]?.focus();
      }
    };
    setTimeout(() => menu.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus(), 0);
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", key);
    };
  }, [open]);
  return (
    <>
      <span ref={anchor} className="inline-flex">{trigger(show, open)}</span>
      {open && createPortal(
        <div
          ref={menu}
          role="menu"
          style={{ left: pos.x, top: pos.y, width, maxHeight: window.innerHeight - pos.y - 12 }}
          className="fixed z-50 overflow-auto rounded-xl border border-stroke-strong bg-layer-2 p-1 shadow-[var(--shadow)] fade-in"
        >
          {items.map((it, i) =>
            it.separator ? <div key={i} className="my-1 h-px bg-stroke" /> : (
              <button
                key={i}
                role="menuitem"
                disabled={it.disabled}
                onClick={() => {
                  setOpen(false);
                  it.onClick?.();
                }}
                className={clsx(
                  "flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[0.86rem]",
                  "hover:bg-card-hover focus:bg-card-hover focus:outline-none disabled:opacity-40",
                  it.danger ? "text-danger" : "text-fg",
                )}
              >
                <span className="w-4 shrink-0 text-fg-2">{it.checked ? <Check size={15} /> : it.icon}</span>
                <span className="flex-1 truncate">{it.label}</span>
                {it.hint && <span className="text-[0.72rem] text-fg-3">{it.hint}</span>}
              </button>
            ),
          )}
        </div>,
        document.body,
      )}
    </>
  );
}

export function Modal({ title, onClose, children, footer, width = 520 }:
  { title: string; onClose?: () => void; children: ReactNode; footer?: ReactNode; width?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("input, textarea, select, button:not([data-close])")?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape" && onClose) onClose();
    };
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("keydown", key);
      prev?.focus?.();
    };
  }, [onClose]);
  return createPortal(
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/45 backdrop-blur-[2px] fade-in"
      onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title} style={{ width }}
        className="max-h-[88vh] max-w-[94vw] overflow-hidden rounded-2xl border border-stroke-strong bg-layer-2 shadow-[var(--shadow)] flex flex-col">
        <div className="flex items-center justify-between px-5 pt-4 pb-2">
          <h2 className="text-[1.05rem] font-semibold">{title}</h2>
          {onClose && <IconButton label="Close" data-close onClick={onClose}><X size={17} /></IconButton>}
        </div>
        <div className="overflow-auto px-5 pb-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-stroke bg-card px-5 py-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function ProgressBar({ value, indeterminate, className }:
  { value?: number; indeterminate?: boolean; className?: string }) {
  return (
    <div className={clsx("h-1 w-full overflow-hidden rounded-full bg-stroke", className)}
      role="progressbar" aria-valuenow={value != null ? Math.round(value * 100) : undefined}>
      {indeterminate ? <div className="h-full progress-indeterminate" />
        : <div className="h-full rounded-full bg-accent transition-[width] duration-300"
          style={{ width: `${Math.max(2, Math.min(100, (value ?? 0) * 100))}%` }} />}
    </div>
  );
}

export function Toasts() {
  const toasts = useStore((s) => s.toasts);
  const dismiss = useStore((s) => s.dismiss);
  return (
    <div className="pointer-events-none fixed bottom-24 right-5 z-50 flex w-[360px] flex-col gap-2" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className="pointer-events-auto fade-in rounded-xl border border-stroke-strong bg-layer-2 p-3.5 shadow-[var(--shadow)]">
          <div className="flex items-start gap-3">
            <span className={clsx("mt-1.5 h-2 w-2 shrink-0 rounded-full", {
              "bg-accent": t.kind === "info", "bg-success": t.kind === "success",
              "bg-danger": t.kind === "error", "bg-warning": t.kind === "warning" })} />
            <div className="min-w-0 flex-1">
              <div className="text-[0.88rem] font-medium">{t.title}</div>
              {t.body && <div className="mt-0.5 whitespace-pre-line break-words text-[0.8rem] text-fg-2 selectable">{t.body}</div>}
              {t.action && (
                <button className="mt-1.5 text-[0.8rem] font-medium text-accent hover:underline"
                  onClick={() => { t.action?.run(); dismiss(t.id); }}>{t.action.label}</button>
              )}
            </div>
            <IconButton label="Dismiss" className="h-6 w-6" onClick={() => dismiss(t.id)}><X size={14} /></IconButton>
          </div>
        </div>
      ))}
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="py-2.5">
      <div className="mb-1.5 text-[0.9rem]">{label}</div>
      {children}
      {hint && <div className="mt-1 text-[0.76rem] text-fg-3">{hint}</div>}
    </div>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("rounded-xl border border-stroke bg-card", className)}>{children}</div>;
}
