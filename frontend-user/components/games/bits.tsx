"use client";

import { useEffect, useRef, useState } from "react";
import { TrendingUp, TrendingDown, Bitcoin, Ticket, Trophy, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatCountdown } from "@/lib/games/window";

/**
 * Reusable "how to play" banner shown at the top of every game screen so a
 * new player instantly sees: what 1 ticket costs, how to play (steps), and
 * what a win pays. Each game passes its own ticket price / steps / payout —
 * ticket prices differ per game, so this is the single source of that info.
 */
export function GameHowTo({
  costText,
  payoutLabel,
  steps,
  className,
}: {
  costText: string;
  payoutLabel: string;
  steps: string[];
  className?: string;
}) {
  return (
    <div className={cn("rounded-xl border border-primary/30 bg-primary/5 p-3", className)}>
      <div className="flex flex-col gap-2.5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-start gap-2.5">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/15 text-primary">
            <Info className="size-5" />
          </span>
          <div>
            <div className="text-sm font-bold">How to play</div>
            <ol className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] leading-snug text-muted-foreground">
              {steps.map((s, i) => (
                <li key={i} className="flex items-center gap-1.5">
                  <span className="grid size-4 shrink-0 place-items-center rounded-full bg-muted text-[9px] font-bold text-foreground">{i + 1}</span>
                  <span>{s}</span>
                  {i < steps.length - 1 && <span className="text-border">·</span>}
                </li>
              ))}
            </ol>
          </div>
        </div>
        {/* Cost / payout chips — full-width on mobile so the ◉ amounts get
            their own clean line, condensing to inline pills on ≥lg. */}
        <div className="flex shrink-0 flex-wrap items-center gap-1.5 border-t border-primary/15 pt-2 text-[11px] font-bold tabular-nums lg:border-t-0 lg:pt-0">
          <span className="inline-flex min-w-0 items-center gap-1.5 rounded-md bg-atm/10 px-2 py-1 text-atm ring-1 ring-inset ring-atm/20">
            <Ticket className="size-3.5 shrink-0" /> <span className="truncate">{costText}</span>
          </span>
          <span className="inline-flex min-w-0 items-center gap-1.5 rounded-md bg-primary/10 px-2 py-1 text-primary ring-1 ring-inset ring-primary/20">
            <Trophy className="size-3.5 shrink-0" /> <span className="truncate">{payoutLabel}</span>
          </span>
        </div>
      </div>
    </div>
  );
}

/**
 * Price display for the Number games that HIGHLIGHTS the two winning digits
 * in red-bold with a "pop" on every tick — because the result is derived from
 * exactly those two digits:
 *   • BTC   → the integer part's last two digits   (61,2[68].01 → 68)
 *   • NIFTY → the two decimal digits               (23,123.[65] → 65)
 */
export function WinningDigitsPrice({
  value,
  mode,
  className,
}: {
  value: number | null | undefined;
  mode: "btc" | "nifty";
  className?: string;
}) {
  const [pop, setPop] = useState(false);
  const prev = useRef<number | null>(null);
  useEffect(() => {
    if (value == null || !(value > 0)) return;
    if (prev.current != null && value !== prev.current) {
      setPop(true);
      const t = setTimeout(() => setPop(false), 320);
      prev.current = value;
      return () => clearTimeout(t);
    }
    prev.current = value;
  }, [value]);

  const has = value != null && value > 0;
  if (!has) return <span className={cn("tabular-nums", className)}>—</span>;

  const v = Number(value);
  const grouped = Math.floor(v).toLocaleString("en-IN");
  const decimals = v.toFixed(2).split(".")[1] ?? "00";

  // Winning digits POP: bigger + extrabold + glow. Everything else is
  // de-emphasised (smaller + lighter) so the eye lands on the digits that win.
  const winCls = cn(
    "inline-block align-baseline text-sell font-extrabold text-[1.18em] leading-none transition-transform duration-300 drop-shadow-[0_0_10px_rgba(224,79,95,0.45)]",
    pop ? "scale-[1.35]" : "scale-100",
  );
  const dimCls = "align-baseline text-[0.72em] font-semibold text-foreground/70";
  const dotCls = "align-baseline text-[0.6em] text-muted-foreground";

  return (
    <span className={cn("inline-flex items-baseline tabular-nums", className)}>
      {mode === "btc" ? (
        <>
          <span className={dimCls}>{grouped.slice(0, -2)}</span>
          <span className={winCls}>{grouped.slice(-2)}</span>
          <span className={dotCls}>.{decimals}</span>
        </>
      ) : (
        <>
          <span className={dimCls}>{grouped}</span>
          <span className={dotCls}>.</span>
          <span className={winCls}>{decimals}</span>
        </>
      )}
    </span>
  );
}

/** Small status pill — open / pending / cooldown / settled. */
export function GameStatePill({
  state,
  label,
}: {
  state: "open" | "pending" | "closed" | "win" | "loss";
  label: string;
}) {
  const tone = {
    open: "bg-buy/15 text-buy ring-buy/30",
    pending: "bg-atm/15 text-atm ring-atm/30",
    closed: "bg-muted text-muted-foreground ring-border",
    win: "bg-buy/15 text-buy ring-buy/30",
    loss: "bg-sell/15 text-sell ring-sell/30",
  }[state];
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset", tone)}>
      {(state === "open" || state === "pending") && (
        <span className={cn("size-1.5 rounded-full", state === "open" ? "bg-buy" : "bg-atm animate-pulse")} />
      )}
      {label}
    </span>
  );
}

/** Ticking countdown driven by a target epoch-seconds value (local 1s tick). */
export function Countdown({ seconds, className }: { seconds: number; className?: string }) {
  const [remaining, setRemaining] = useState(seconds);
  useEffect(() => {
    setRemaining(seconds);
    const t = setInterval(() => setRemaining((r) => Math.max(0, r - 1)), 1000);
    return () => clearInterval(t);
  }, [seconds]);
  return <span className={cn("font-mono tabular-nums", className)}>{formatCountdown(remaining)}</span>;
}

export function StatChip({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={cn("truncate text-sm font-bold tabular-nums", tone)}>{value}</div>
    </div>
  );
}

/**
 * Big live price that flashes green / red on every tick and shows a small
 * up/down arrow for the last move. Drives the "fast moving" feel — pair it
 * with a ~1s price poll (useGamesPrice(1000)).
 */
/** Always render exactly `digits` decimals so a whole number (2384) shows as
 *  "2,384.00" and a half (7474.5) as "7,474.50" — `toLocaleString` with only
 *  `maximumFractionDigits` DROPS the trailing zero, which is what made the
 *  live-spot readout jump between "24,471.7" and "24,471.75" and left result
 *  columns misaligned. Shared from here because the same one-line formatter
 *  was being re-typed per screen and only some copies got it right. */
export function fmtPrice(v: number | undefined | null, digits = 2): string {
  if (v == null) return "—";
  return Number(v).toLocaleString("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function LivePrice({
  value,
  digits = 2,
  className,
}: {
  value: number | null | undefined;
  digits?: number;
  className?: string;
}) {
  const prev = useRef<number | null>(null);
  const [dir, setDir] = useState<"up" | "down" | null>(null);

  useEffect(() => {
    if (value == null || !(value > 0)) return;
    const p = prev.current;
    if (p != null && value !== p) {
      const d = value > p ? "up" : "down";
      setDir(d);
      prev.current = value;
      const t = setTimeout(() => setDir(null), 500);
      return () => clearTimeout(t);
    }
    prev.current = value;
  }, [value]);

  const has = value != null && value > 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 tabular-nums transition-colors duration-300",
        dir === "up" && "text-buy",
        dir === "down" && "text-sell",
        className,
      )}
    >
      {has ? fmtPrice(value, digits) : "—"}
      {dir === "up" && <TrendingUp className="size-5 shrink-0" />}
      {dir === "down" && <TrendingDown className="size-5 shrink-0" />}
    </span>
  );
}

/** Connectivity dot — green pulse when the live feed is delivering a price. */
export function LiveDot({ live, label }: { live: boolean; label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
      <span className="relative flex size-2">
        {live && <span className="absolute inline-flex size-full animate-ping rounded-full bg-buy/60" />}
        <span className={cn("relative inline-flex size-2 rounded-full", live ? "bg-buy" : "bg-muted-foreground/50")} />
      </span>
      {label ?? (live ? "Live feed" : "Feed offline")}
    </span>
  );
}

/** Compact live-price tag for the lobby / headers. `asset` picks the accent. */
export function LivePriceTag({
  asset,
  value,
  className,
}: {
  asset: "NIFTY" | "BTC";
  value: number | null | undefined;
  className?: string;
}) {
  const Icon = asset === "BTC" ? Bitcoin : TrendingUp;
  const has = value != null && value > 0;
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2",
        className,
      )}
    >
      <span
        className={cn(
          "grid size-7 shrink-0 place-items-center rounded-lg",
          asset === "BTC" ? "bg-atm/15 text-atm" : "bg-primary/10 text-primary",
        )}
      >
        <Icon className="size-4" />
      </span>
      <div className="min-w-0">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{asset}</div>
        <div className="truncate text-sm font-bold tabular-nums leading-tight">
          {has ? fmtPrice(value) : "—"}
        </div>
      </div>
    </div>
  );
}
