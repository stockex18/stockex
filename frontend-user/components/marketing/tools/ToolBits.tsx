"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/* Shared form + result primitives for the four calculator pages, so the
   tools read as one family instead of four separately-styled forms.
   Deliberately avoids `blur-[…]` / `blur-3xl` classes — `.mp-scope` hides
   those globally (globals.css), so a decorative glow authored here would
   silently vanish. */

export function ToolField({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[13px] font-semibold text-mp-text">{label}</span>
      {children}
      {hint ? (
        <span className="text-[11px] leading-snug text-mp-text-mut">{hint}</span>
      ) : null}
    </label>
  );
}

const CONTROL =
  "h-11 w-full rounded-xl border border-mp-border bg-mp-surface px-3 text-sm text-mp-text outline-none transition-colors focus:border-mp-primary focus:ring-2 focus:ring-mp-primary/20";

export function ToolNumber({
  value,
  onChange,
  min = 0,
  step = "any",
  placeholder,
}: {
  value: number | "";
  onChange: (n: number) => void;
  min?: number;
  step?: number | string;
  placeholder?: string;
}) {
  return (
    <input
      type="number"
      inputMode="decimal"
      className={cn(CONTROL, "mp-num tabular-nums")}
      value={value}
      min={min}
      step={step}
      placeholder={placeholder}
      // Empty string must not become NaN — an empty box reads as 0 so the
      // result panel stays populated while the user is mid-edit.
      onChange={(e) => {
        const raw = e.target.value;
        onChange(raw === "" ? 0 : Number(raw));
      }}
      onFocus={(e) => e.target.select()}
    />
  );
}

export function ToolSelect<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <select
      className={CONTROL}
      value={value}
      onChange={(e) => onChange(e.target.value as T)}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function ToolToggle<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <div className="flex flex-wrap gap-1.5 rounded-xl border border-mp-border bg-mp-surface-2 p-1">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            aria-pressed={active}
            className={cn(
              "flex-1 rounded-lg px-3 py-2 text-[13px] font-semibold transition-colors",
              active
                ? "bg-mp-primary text-white"
                : "text-mp-text-mut hover:text-mp-text",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function ResultRow({
  label,
  value,
  tone = "default",
  strong = false,
}: {
  label: string;
  value: string;
  tone?: "default" | "up" | "down" | "muted";
  strong?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex items-baseline justify-between gap-4 py-2.5",
        strong && "border-t border-mp-border pt-3.5",
      )}
    >
      <span
        className={cn(
          "text-[13px]",
          strong ? "font-semibold text-mp-text" : "text-mp-text-mut",
        )}
      >
        {label}
      </span>
      <span
        className={cn(
          "mp-num tabular-nums",
          strong ? "text-xl font-bold" : "text-sm font-semibold",
          tone === "up" && "text-mp-success",
          tone === "down" && "text-mp-danger",
          tone === "muted" && "text-mp-text-mut",
          tone === "default" && "text-mp-text",
        )}
      >
        {value}
      </span>
    </div>
  );
}

/** The "these are your broker's numbers" caveat every tool carries. */
export function ToolDisclaimer({ children }: { children: ReactNode }) {
  return (
    <p className="mt-6 rounded-xl border border-mp-border bg-mp-surface-2 p-4 text-[12px] leading-[1.65] text-mp-text-mut">
      {children}
    </p>
  );
}
