"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { PiArrowDownRightBold, PiArrowUpRightBold, PiCaretRightBold } from "react-icons/pi";
import { usePublicMarketFeed, type PublicQuote } from "@/lib/usePublicMarketFeed";
import { usePriceFlash } from "@/lib/usePriceFlash";
import { SymbolAvatar } from "@/components/common/SymbolAvatar";
import { Sparkline } from "@/components/common/Sparkline";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────
// Home "Market Overview" — one card, five tabs, every row with its logo.
//
// Data is the curated `/market/snapshot` (via usePublicMarketFeed): ONE
// request returns the instruments AND their prices, and the app's persisted
// query cache paints the last-known prices before that request even lands.
// The old card searched each symbol, then fetched quotes, then streamed —
// three round-trips before a price, which is why the rows sat on "—".
// Live ticks overlay the snapshot through the same hook.
// ─────────────────────────────────────────────────────────────────────

type Tab = "indices" | "gainers" | "losers" | "mcx" | "crypto";
const TABS: { key: Tab; label: string }[] = [
  { key: "indices", label: "Indices" },
  { key: "gainers", label: "Top Gainers" },
  { key: "losers", label: "Top Losers" },
  { key: "mcx", label: "MCX" },
  { key: "crypto", label: "Crypto" },
];
const ROWS = 5;

// Readable second line for rows whose catalogue name is the symbol again.
const SUBTITLE: Record<string, string> = {
  NIFTY50: "Nifty 50",
  BANKNIFTY: "Bank Nifty",
  SENSEX: "BSE Sensex",
  FINNIFTY: "Nifty Financial Services",
  GOLD: "Gold · MCX",
  SILVER: "Silver · MCX",
  CRUDEOIL: "Crude Oil · MCX",
  NATURALGAS: "Natural Gas · MCX",
  BTCUSD: "Bitcoin",
  ETHUSD: "Ethereum",
  SOLUSD: "Solana",
  XRPUSD: "XRP",
};

const INR_EXCH = new Set(["NSE", "BSE", "NFO", "BFO", "MCX", "CDS", "NCO"]);

function titleCase(s: string): string {
  return s.toLowerCase().replace(/\b[a-z]/g, (c) => c.toUpperCase());
}

function fmtPrice(r: PublicQuote): string {
  const cur = INR_EXCH.has(String(r.exchange).toUpperCase()) ? "₹" : "$";
  return `${cur}${Number(r.ltp).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function MarketOverview({ className }: { className?: string }) {
  const { rows, loading, failed } = usePublicMarketFeed();
  const [tab, setTab] = useState<Tab>("indices");

  const shown = useMemo(() => {
    const by = (cat: string) => rows.filter((r) => r.category === cat);
    const stocks = [...by("Stocks")].sort((a, b) => b.change_pct - a.change_pct);
    switch (tab) {
      case "gainers":
        return stocks.filter((r) => r.change_pct > 0).slice(0, ROWS);
      case "losers":
        return stocks.filter((r) => r.change_pct < 0).reverse().slice(0, ROWS);
      case "mcx":
        return by("Commodities").slice(0, ROWS);
      case "crypto":
        return by("Crypto").slice(0, ROWS);
      default:
        return by("Indices").slice(0, ROWS);
    }
  }, [rows, tab]);

  return (
    <section className={cn("overflow-hidden rounded-2xl border border-border bg-card shadow-sm", className)}>
      <div className="flex items-center justify-between px-4 pb-2 pt-3.5">
        <div className="flex items-center gap-2">
          <span className="grid size-5 place-items-center rounded-full bg-gradient-to-br from-yellow-300 to-amber-500 shadow-sm shadow-amber-500/40" />
          <h3 className="text-[15px] font-extrabold tracking-tight">Market Overview</h3>
        </div>
        <span className="inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
          <span className="relative flex size-1.5">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-500/70" />
            <span className="relative inline-flex size-1.5 rounded-full bg-emerald-500" />
          </span>
          Live
        </span>
      </div>

      {/* Tabs — gold pill for the active one, horizontally scrollable on narrow phones. */}
      <div className="-mb-px flex gap-1.5 overflow-x-auto px-4 pb-3 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={cn(
              "h-7 shrink-0 whitespace-nowrap rounded-full px-2.5 text-[11px] font-bold transition-colors",
              tab === t.key
                ? "bg-primary text-primary-foreground shadow-sm shadow-primary/30"
                : "bg-muted text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading && rows.length === 0 ? (
        <ul className="divide-y divide-border border-t border-border">
          {Array.from({ length: 4 }).map((_, i) => (
            <li key={i} className="flex items-center gap-3 px-4 py-3">
              <div className="size-10 animate-pulse rounded-full bg-muted/60" />
              <div className="flex-1 space-y-1.5">
                <div className="h-3 w-20 animate-pulse rounded bg-muted/60" />
                <div className="h-2.5 w-28 animate-pulse rounded bg-muted/40" />
              </div>
              <div className="space-y-1.5">
                <div className="ml-auto h-3 w-16 animate-pulse rounded bg-muted/60" />
                <div className="ml-auto h-4 w-12 animate-pulse rounded-full bg-muted/40" />
              </div>
            </li>
          ))}
        </ul>
      ) : failed || shown.length === 0 ? (
        <div className="border-t border-border px-4 py-8 text-center text-xs text-muted-foreground">
          {failed ? "Market data unavailable right now." : "Nothing to show here yet."}
        </div>
      ) : (
        <ul className="divide-y divide-border border-t border-border">
          {shown.map((r) => (
            <MarketRow key={r.token} row={r} />
          ))}
        </ul>
      )}

      <Link
        href="/marketwatch"
        className="flex items-center justify-center gap-1 border-t border-border py-2.5 text-xs font-bold text-primary transition-colors hover:bg-primary/5"
      >
        View all markets <PiCaretRightBold className="size-3" />
      </Link>
    </section>
  );
}

function MarketRow({ row }: { row: PublicQuote }) {
  const flash = usePriceFlash(row.ltp);
  const up = row.change_pct >= 0;
  const subtitle = SUBTITLE[row.key] ?? (row.name ? titleCase(row.name) : row.exchange);

  return (
    <li>
      <Link
        href={`/terminal?token=${row.token}`}
        className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/40 active:bg-muted/60"
      >
        <SymbolAvatar symbol={row.key} changePct={row.change_pct} className="size-10" />

        <div className="min-w-0 flex-1">
          <div className="truncate text-[14px] font-extrabold leading-tight tracking-tight">{row.label}</div>
          <div className="mt-0.5 truncate text-[11px] font-semibold text-muted-foreground">{subtitle}</div>
        </div>

        <Sparkline token={row.token} up={up} className="hidden h-7 w-14 shrink-0 min-[360px]:block" />

        <div className="shrink-0 text-right">
          <div
            className={cn(
              "font-tabular text-[14px] font-extrabold tabular-nums transition-colors duration-300",
              flash === "up" ? "text-emerald-500" : flash === "down" ? "text-red-500" : "text-foreground",
            )}
          >
            {fmtPrice(row)}
          </div>
          <span
            className={cn(
              "mt-1 inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[11px] font-bold tabular-nums",
              up
                ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                : "bg-red-500/15 text-red-600 dark:text-red-400",
            )}
          >
            {up ? <PiArrowUpRightBold className="size-3" /> : <PiArrowDownRightBold className="size-3" />}
            {`${up ? "+" : ""}${row.change_pct.toFixed(2)}%`}
          </span>
        </div>
      </Link>
    </li>
  );
}
