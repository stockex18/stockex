import type { CSSProperties, HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/**
 * Loading placeholders: grey shapes in the layout of the content that is on
 * its way, instead of a lone "Loading…" line. The shimmer lives in
 * globals.css (`.skeleton`) and stops for reduced-motion users. Everything is
 * drawn from the theme tokens, so it follows light / dark automatically.
 *
 * Each wrapper carries role="status" + a visually hidden "Loading…", so screen
 * readers still announce what sighted users now see as shapes.
 */

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return <span aria-hidden className={cn("skeleton block rounded-md", className)} {...props} />;
}

/** Varied but stable widths, so rows look like real text rather than a grid. */
const w = (i: number, base: number, spread: number): CSSProperties => ({
  width: `${base + ((i * 17) % spread)}%`,
});

/** List rows: side badge + title, a detail line, and a value on the right
 *  (orders, trades, positions, strikes). */
export function ListSkeleton({ rows = 6, className }: { rows?: number; className?: string }) {
  return (
    <div role="status" className={cn("divide-y divide-border/50", className)}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3 px-4 py-3">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex items-center gap-2">
              <Skeleton className="h-4 w-9 shrink-0" />
              <Skeleton className="h-3.5" style={w(i, 34, 22)} />
            </div>
            <Skeleton className="h-2.5" style={w(i + 2, 26, 18)} />
          </div>
          <div className="flex flex-col items-end gap-1.5">
            <Skeleton className="h-3.5 w-16" />
            <Skeleton className="h-2.5 w-9" />
          </div>
        </div>
      ))}
      <span className="sr-only">Loading…</span>
    </div>
  );
}

/** Rows for a table body that is still loading. First column left, the rest
 *  right-aligned like the numbers they stand in for. */
export function TableSkeletonRows({ cols, rows = 6 }: { cols: number; rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, r) => (
        <tr key={r} aria-hidden>
          {Array.from({ length: cols }, (_, c) => (
            <td key={c} className="px-3 py-3.5">
              <Skeleton
                className={cn("h-3", c > 0 && "ml-auto")}
                style={{ width: c === 0 ? 70 + ((r * 13) % 40) : 40 + (((r + c) * 17) % 35) }}
              />
            </td>
          ))}
        </tr>
      ))}
      <tr className="sr-only">
        <td colSpan={cols} role="status">Loading…</td>
      </tr>
    </>
  );
}

/** A small row of chip-shaped placeholders (expiry dates, filters). */
export function ChipsSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div role="status" className="flex items-center gap-2">
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} className="h-7 rounded-full" style={{ width: 64 + ((i * 11) % 24) }} />
      ))}
      <span className="sr-only">Loading…</span>
    </div>
  );
}

/** Outline of a whole page of cards (profile, dashboards). */
export function PageSkeleton() {
  const card = (i: number) => (
    <div key={i} className="space-y-2.5 rounded-2xl border border-border bg-card p-4">
      <Skeleton className="h-3 w-1/3" />
      <Skeleton className="h-5" style={w(i, 45, 25)} />
      <Skeleton className="h-2.5 w-1/4" />
    </div>
  );
  return (
    <div role="status" className="space-y-4">
      <div className="flex items-center gap-4 rounded-2xl border border-border bg-card p-5">
        <Skeleton className="size-16 shrink-0 rounded-full" />
        <div className="flex-1 space-y-2.5">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-3 w-56 max-w-full" />
        </div>
      </div>
      {[0, 1, 2, 3].map(card)}
      <span className="sr-only">Loading…</span>
    </div>
  );
}

/**
 * Full-screen outline of the app while the saved session loads (every app
 * start). Mirrors the real shell: sidebar (w-60) + h-14 top bar on desktop;
 * top bar + index strip + bottom nav on phones. `terminal` swaps the page for
 * the trading terminal's panels.
 */
export function AppShellSkeleton({ variant = "dashboard" }: { variant?: "dashboard" | "terminal" }) {
  if (variant === "terminal") {
    return (
      <div role="status" className="flex h-screen flex-col bg-background">
        <div className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-border px-3">
          <Skeleton className="h-7 w-24 rounded-full" />
          <div className="flex items-center gap-2">
            <Skeleton className="h-7 w-32 rounded-full" />
            <Skeleton className="size-7 rounded-full" />
            <Skeleton className="size-7 rounded-full" />
          </div>
        </div>
        <div className="grid min-h-0 flex-1 gap-2 p-2 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="grid min-h-0 grid-rows-[1fr_auto] gap-2">
            <Skeleton className="h-full min-h-48 rounded-lg" />
            <Skeleton className="h-40 rounded-lg" />
          </div>
          <Skeleton className="hidden h-full rounded-lg lg:block" />
        </div>
        <span className="sr-only">Loading…</span>
      </div>
    );
  }

  const tile = (i: number) => (
    <div key={i} className="grid justify-items-center gap-2.5 rounded-2xl border border-border bg-card p-4">
      <Skeleton className="size-11 rounded-full" />
      <Skeleton className="h-2.5 w-14" />
    </div>
  );
  const wallet = (i: number) => (
    <div key={i} className="space-y-2.5 rounded-2xl border border-border bg-card p-3.5">
      <Skeleton className="h-3.5 w-12 rounded-full" />
      <Skeleton className="h-2.5 w-16" />
      <Skeleton className="h-4 w-24" />
    </div>
  );

  return (
    <div role="status" className="grid min-h-screen grid-cols-1 bg-background md:grid-cols-[auto_1fr]">
      <aside className="hidden h-screen w-60 flex-col border-r border-border bg-card md:flex">
        <div className="flex h-14 items-center gap-2 border-b border-border px-3">
          <Skeleton className="size-8 rounded-full" />
          <Skeleton className="h-4 w-24" />
        </div>
        <div className="space-y-1 p-2">
          {Array.from({ length: 11 }, (_, i) => (
            <div key={i} className="flex items-center gap-3 px-3 py-2.5">
              <Skeleton className="size-4 rounded" />
              <Skeleton className="h-3" style={{ width: 64 + ((i * 23) % 56) }} />
            </div>
          ))}
        </div>
      </aside>
      <div className="flex min-h-screen min-w-0 flex-col">
        <div className="border-b border-border">
          <div className="flex h-14 items-center justify-between gap-3 px-3 md:px-4">
            <Skeleton className="h-8 w-28 md:w-[440px]" />
            <div className="flex items-center gap-2">
              <Skeleton className="h-8 w-28 rounded-full" />
              <Skeleton className="size-6 rounded-full" />
              <Skeleton className="size-6 rounded-full" />
            </div>
          </div>
          <div className="h-7 border-t border-border/60 md:hidden" />
        </div>
        <div className="mx-auto w-full max-w-screen-2xl flex-1 space-y-4 p-4 md:p-6">
          <Skeleton className="h-8 w-full rounded" />
          <div className="flex items-center justify-between gap-3">
            <div className="space-y-2">
              <Skeleton className="h-3 w-28" />
              <Skeleton className="h-7 w-36" />
              <Skeleton className="h-2.5 w-20" />
            </div>
            <Skeleton className="h-12 w-40 rounded-2xl" />
          </div>
          <div className="space-y-2.5 rounded-2xl border border-border bg-card p-4">
            <Skeleton className="h-3 w-32" />
            <Skeleton className="h-8 w-48" />
            <Skeleton className="h-2.5 w-24" />
          </div>
          <div className="grid grid-cols-4 gap-2 sm:gap-3">{[0, 1, 2, 3].map(tile)}</div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">{[0, 1, 2, 3, 4].map(wallet)}</div>
        </div>
        <div className="fixed inset-x-0 bottom-0 flex h-14 items-center justify-around border-t border-border bg-background md:hidden">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="grid justify-items-center gap-1.5">
              <Skeleton className="size-5 rounded" />
              <Skeleton className="h-2 w-9" />
            </div>
          ))}
        </div>
      </div>
      <span className="sr-only">Loading…</span>
    </div>
  );
}
