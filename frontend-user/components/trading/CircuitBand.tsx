"use client";

import { cn } from "@/lib/utils";

/** Today's circuit band — the prices this instrument cannot trade beyond:
 *  Zerodha's lower / upper_circuit_limit (stocks, futures, options, MCX),
 *  served on the effective segment settings. Nothing for crypto / forex,
 *  which have no band. */
export function CircuitBand({
  lower,
  upper,
  decimals = 2,
  className,
}: {
  lower?: number | null;
  upper?: number | null;
  decimals?: number;
  className?: string;
}) {
  const lc = Number(lower) || 0;
  const uc = Number(upper) || 0;
  if (lc <= 0 && uc <= 0) return null;
  const fmt = (v: number) => (v > 0 ? v.toFixed(decimals) : "—");
  return (
    <div className={cn("grid grid-cols-2 overflow-hidden rounded-lg border border-border text-[11px]", className)}>
      <div className="flex items-center justify-between gap-1 bg-sell/5 px-2.5 py-1.5">
        <span className="font-semibold text-muted-foreground">Lower circuit</span>
        <span className="font-tabular font-bold tabular-nums text-sell">{fmt(lc)}</span>
      </div>
      <div className="flex items-center justify-between gap-1 border-l border-border bg-buy/5 px-2.5 py-1.5">
        <span className="font-semibold text-muted-foreground">Upper circuit</span>
        <span className="font-tabular font-bold tabular-nums text-buy">{fmt(uc)}</span>
      </div>
    </div>
  );
}
