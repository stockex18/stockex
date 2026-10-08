"use client";

import { useState } from "react";
import { API_URL } from "@/lib/constants";
import { cn } from "@/lib/utils";

/** Symbols whose logo already failed on this page. Keyed by SYMBOL, never a
 *  per-row boolean: virtualised / re-sorted lists recycle rows, and a boolean
 *  would hide the logo of whatever symbol lands in that row next. */
const failed = new Set<string>();

/** "NSE:NIFTY 50" → "NIFTY50" — the shape the logo endpoint validates. */
export function logoKey(symbol: string | null | undefined): string {
  return String(symbol ?? "")
    .replace(/^[A-Z]+:/i, "")
    .replace(/\s+/g, "")
    .toUpperCase();
}

/**
 * Company / index / coin logo with initials underneath. The initials are the
 * base layer, tinted by the day's direction; the logo (served by our own API,
 * never the vendor) covers them once it loads. A missing logo leaves the
 * initials — never a broken-image icon.
 */
export function SymbolAvatar({
  symbol,
  changePct,
  className,
}: {
  symbol: string | null | undefined;
  changePct?: number | null;
  className?: string;
}) {
  const key = logoKey(symbol);
  // Which symbol the <img> settled for. Comparing against `key` means a row
  // reused for a different symbol starts fresh.
  const [loaded, setLoaded] = useState<string | null>(null);
  const [, rerender] = useState(0);
  const initials = key.replace(/[^A-Z]/g, "").slice(0, 2) || "•";
  const tone =
    changePct == null || changePct === 0
      ? "bg-muted text-muted-foreground"
      : changePct > 0
        ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
        : "bg-red-500/15 text-red-600 dark:text-red-400";
  const tryLogo = key !== "" && !failed.has(key);

  return (
    <span
      className={cn(
        "relative grid size-9 shrink-0 select-none place-items-center overflow-hidden rounded-full text-[11px] font-extrabold tracking-tight",
        tone,
        className,
      )}
      aria-hidden
    >
      {initials}
      {tryLogo && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          key={key}
          src={`${API_URL}/api/v1/market/logo/${encodeURIComponent(key)}`}
          alt=""
          loading="lazy"
          decoding="async"
          // A cached image can finish before React attaches onLoad.
          ref={(el) => {
            if (el?.complete && el.naturalWidth > 0 && loaded !== key) setLoaded(key);
          }}
          onLoad={() => setLoaded(key)}
          onError={() => {
            failed.add(key);
            rerender((n) => n + 1);
          }}
          className={cn(
            "absolute inset-0 size-full bg-white object-contain transition-opacity duration-200",
            loaded === key ? "opacity-100" : "opacity-0",
          )}
        />
      )}
    </span>
  );
}
