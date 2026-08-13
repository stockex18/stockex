"use client";

import { useMemo, useState } from "react";
import { ArrowRight, Table2, LayoutGrid } from "lucide-react";
import Link from "next/link";
import { MpCard } from "@/components/marketing/mp-ui";
import { formatNumber } from "@/lib/tools/charges";
import { cn } from "@/lib/utils";

/* ── Data ────────────────────────────────────────────────────────────────
   An INDICATIVE snapshot, not a live feed. Every market endpoint on this
   backend requires an authenticated user (`CurrentUser` on every route in
   app/api/v1/user/), and the public marketing site has no session — so a
   genuinely live public heatmap needs a public quotes endpoint that does
   not exist yet. Rather than fake liveness with a random walk, the page
   labels this as a snapshot and points at the terminal for real prices.
   Swap SECTORS for a fetch the moment a public endpoint lands.          */

type Stock = { symbol: string; name: string; weight: number; change: number };
type Sector = { sector: string; stocks: Stock[] };

const SECTORS: Sector[] = [
  {
    sector: "Banking & Financials",
    stocks: [
      { symbol: "HDFCBANK", name: "HDFC Bank", weight: 11.2, change: 0.84 },
      { symbol: "ICICIBANK", name: "ICICI Bank", weight: 8.1, change: 1.32 },
      { symbol: "SBIN", name: "State Bank of India", weight: 3.4, change: -0.46 },
      { symbol: "KOTAKBANK", name: "Kotak Mahindra Bank", weight: 2.8, change: 0.12 },
      { symbol: "AXISBANK", name: "Axis Bank", weight: 2.6, change: -1.24 },
      { symbol: "BAJFINANCE", name: "Bajaj Finance", weight: 2.1, change: 2.36 },
    ],
  },
  {
    sector: "Information Technology",
    stocks: [
      { symbol: "TCS", name: "Tata Consultancy Services", weight: 4.3, change: -1.86 },
      { symbol: "INFY", name: "Infosys", weight: 3.9, change: -0.92 },
      { symbol: "HCLTECH", name: "HCL Technologies", weight: 1.6, change: 0.34 },
      { symbol: "WIPRO", name: "Wipro", weight: 0.9, change: -2.14 },
      { symbol: "TECHM", name: "Tech Mahindra", weight: 0.8, change: -0.08 },
    ],
  },
  {
    sector: "Oil, Gas & Energy",
    stocks: [
      { symbol: "RELIANCE", name: "Reliance Industries", weight: 9.6, change: -0.36 },
      { symbol: "ONGC", name: "Oil & Natural Gas Corp", weight: 1.1, change: 1.74 },
      { symbol: "NTPC", name: "NTPC", weight: 1.5, change: 0.62 },
      { symbol: "POWERGRID", name: "Power Grid Corp", weight: 1.2, change: -0.18 },
      { symbol: "BPCL", name: "Bharat Petroleum", weight: 0.6, change: 3.42 },
    ],
  },
  {
    sector: "Auto",
    stocks: [
      { symbol: "M&M", name: "Mahindra & Mahindra", weight: 2.2, change: 1.96 },
      { symbol: "MARUTI", name: "Maruti Suzuki", weight: 1.9, change: 0.48 },
      { symbol: "TATAMOTORS", name: "Tata Motors", weight: 1.7, change: 2.88 },
      { symbol: "BAJAJ-AUTO", name: "Bajaj Auto", weight: 1.0, change: -0.72 },
      { symbol: "EICHERMOT", name: "Eicher Motors", weight: 0.7, change: -1.42 },
    ],
  },
  {
    sector: "FMCG & Consumer",
    stocks: [
      { symbol: "ITC", name: "ITC", weight: 3.8, change: 0.22 },
      { symbol: "HINDUNILVR", name: "Hindustan Unilever", weight: 2.4, change: -0.64 },
      { symbol: "NESTLEIND", name: "Nestle India", weight: 0.9, change: -0.14 },
      { symbol: "TITAN", name: "Titan Company", weight: 1.4, change: 1.08 },
      { symbol: "BRITANNIA", name: "Britannia Industries", weight: 0.6, change: -2.62 },
    ],
  },
  {
    sector: "Pharma & Healthcare",
    stocks: [
      { symbol: "SUNPHARMA", name: "Sun Pharmaceutical", weight: 2.0, change: 1.44 },
      { symbol: "DRREDDY", name: "Dr Reddy's Labs", weight: 0.8, change: -0.34 },
      { symbol: "CIPLA", name: "Cipla", weight: 0.8, change: 0.92 },
      { symbol: "APOLLOHOSP", name: "Apollo Hospitals", weight: 0.7, change: 3.86 },
      { symbol: "DIVISLAB", name: "Divi's Laboratories", weight: 0.7, change: -0.88 },
    ],
  },
  {
    sector: "Metals & Cement",
    stocks: [
      { symbol: "ULTRACEMCO", name: "UltraTech Cement", weight: 1.3, change: -1.08 },
      { symbol: "TATASTEEL", name: "Tata Steel", weight: 1.1, change: -3.24 },
      { symbol: "JSWSTEEL", name: "JSW Steel", weight: 0.9, change: -2.46 },
      { symbol: "HINDALCO", name: "Hindalco Industries", weight: 0.9, change: -1.66 },
      { symbol: "GRASIM", name: "Grasim Industries", weight: 0.8, change: 0.28 },
    ],
  },
];

/* ── Diverging bucket ────────────────────────────────────────────────────
   Four equal steps per arm plus a hueless midpoint. Thresholds are in %
   change; the dead band around zero is deliberately narrow so a genuinely
   flat stock stays grey instead of picking a side.                       */
const STEPS = [
  { max: -3, token: "--heat-d4" },
  { max: -2, token: "--heat-d3" },
  { max: -1, token: "--heat-d2" },
  { max: -0.25, token: "--heat-d1" },
  { max: 0.25, token: "--heat-0" },
  { max: 1, token: "--heat-u1" },
  { max: 2, token: "--heat-u2" },
  { max: 3, token: "--heat-u3" },
  { max: Infinity, token: "--heat-u4" },
];

function tokenFor(change: number): string {
  return (STEPS.find((s) => change < s.max) ?? STEPS[STEPS.length - 1]).token;
}

const pct = (n: number) => `${n >= 0 ? "+" : ""}${formatNumber(n, 2)}%`;

type SortKey = "sector" | "gainers" | "losers";

export function MarketHeatmap() {
  const [sector, setSector] = useState<string>("ALL");
  const [sort, setSort] = useState<SortKey>("sector");
  const [view, setView] = useState<"grid" | "table">("grid");
  const [active, setActive] = useState<Stock | null>(null);

  const visible = useMemo(() => {
    const groups =
      sector === "ALL" ? SECTORS : SECTORS.filter((s) => s.sector === sector);
    if (sort === "sector") return groups;
    // Flatten into one pseudo-sector when sorting by move, so the ranking
    // is across the whole board rather than within each block.
    const all = groups.flatMap((g) => g.stocks);
    const sorted = [...all].sort((a, b) =>
      sort === "gainers" ? b.change - a.change : a.change - b.change,
    );
    return [{ sector: sort === "gainers" ? "Top gainers" : "Top losers", stocks: sorted }];
  }, [sector, sort]);

  const flat = useMemo(() => visible.flatMap((g) => g.stocks), [visible]);
  const advancing = flat.filter((s) => s.change > 0).length;
  const declining = flat.filter((s) => s.change < 0).length;

  return (
    <div className="flex flex-col gap-5">
      {/* Controls — one row above the chart */}
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={sector}
          onChange={(e) => setSector(e.target.value)}
          className="h-10 rounded-xl border border-mp-border bg-mp-surface px-3 text-[13px] font-medium text-mp-text outline-none focus:border-mp-primary"
          aria-label="Filter by sector"
        >
          <option value="ALL">All sectors</option>
          {SECTORS.map((s) => (
            <option key={s.sector} value={s.sector}>
              {s.sector}
            </option>
          ))}
        </select>

        <div className="flex gap-1 rounded-xl border border-mp-border bg-mp-surface-2 p-1">
          {(
            [
              { k: "sector", label: "By sector" },
              { k: "gainers", label: "Top gainers" },
              { k: "losers", label: "Top losers" },
            ] as { k: SortKey; label: string }[]
          ).map((o) => (
            <button
              key={o.k}
              type="button"
              onClick={() => setSort(o.k)}
              aria-pressed={sort === o.k}
              className={cn(
                "rounded-lg px-3 py-1.5 text-[13px] font-semibold transition-colors",
                sort === o.k
                  ? "bg-mp-primary text-white"
                  : "text-mp-text-mut hover:text-mp-text",
              )}
            >
              {o.label}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={() => setView(view === "grid" ? "table" : "grid")}
          className="ml-auto inline-flex h-10 items-center gap-2 rounded-xl border border-mp-border bg-mp-surface px-3 text-[13px] font-semibold text-mp-text transition-colors hover:border-mp-primary/60"
        >
          {view === "grid" ? <Table2 className="size-4" /> : <LayoutGrid className="size-4" />}
          {view === "grid" ? "Table view" : "Heatmap view"}
        </button>
      </div>

      {/* Breadth summary */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[13px] text-mp-text-mut">
        <span>
          <strong className="text-mp-success">{advancing}</strong> advancing
        </span>
        <span>
          <strong className="text-mp-danger">{declining}</strong> declining
        </span>
        <span>{flat.length} stocks shown</span>
      </div>

      {view === "grid" ? (
        <div className="flex flex-col gap-6">
          {visible.map((group) => (
            <section key={group.sector}>
              <h3 className="mb-2.5 text-[13px] font-bold uppercase tracking-[0.08em] text-mp-text-mut">
                {group.sector}
              </h3>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
                {group.stocks.map((s) => (
                  <button
                    key={s.symbol}
                    type="button"
                    onMouseEnter={() => setActive(s)}
                    onFocus={() => setActive(s)}
                    onMouseLeave={() => setActive(null)}
                    onBlur={() => setActive(null)}
                    // Colour carries the polarity, but the number is printed
                    // on every tile — identity is never colour-alone, which
                    // is what keeps this readable for CVD and in print.
                    style={{
                      backgroundColor: `rgb(var(${tokenFor(s.change)}))`,
                      color: `rgb(var(--heat-ink))`,
                    }}
                    className="flex flex-col items-start gap-1 rounded-xl p-3 text-left outline-none ring-mp-primary/40 transition-transform hover:-translate-y-0.5 focus-visible:ring-2"
                    title={`${s.name} · ${pct(s.change)} · index weight ${formatNumber(s.weight, 1)}%`}
                  >
                    <span className="text-[12px] font-bold leading-tight">
                      {s.symbol}
                    </span>
                    <span className="mp-num text-[15px] font-bold tabular-nums">
                      {pct(s.change)}
                    </span>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <MpCard hover={false} className="overflow-x-auto p-0">
          <table className="w-full min-w-[520px] text-sm">
            <thead>
              <tr className="border-b border-mp-border text-left text-[12px] uppercase tracking-wide text-mp-text-mut">
                <th className="px-4 py-3 font-semibold">Symbol</th>
                <th className="px-4 py-3 font-semibold">Company</th>
                <th className="px-4 py-3 text-right font-semibold">Weight</th>
                <th className="px-4 py-3 text-right font-semibold">Change</th>
              </tr>
            </thead>
            <tbody>
              {flat.map((s) => (
                <tr key={s.symbol} className="border-b border-mp-border/60 last:border-0">
                  <td className="px-4 py-2.5 font-semibold text-mp-text">{s.symbol}</td>
                  <td className="px-4 py-2.5 text-mp-text-mut">{s.name}</td>
                  <td className="mp-num px-4 py-2.5 text-right tabular-nums text-mp-text-mut">
                    {formatNumber(s.weight, 1)}%
                  </td>
                  <td
                    className={cn(
                      "mp-num px-4 py-2.5 text-right font-semibold tabular-nums",
                      s.change >= 0 ? "text-mp-success" : "text-mp-danger",
                    )}
                  >
                    {pct(s.change)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </MpCard>
      )}

      {/* Hover readout */}
      <div
        aria-live="polite"
        className="min-h-[44px] rounded-xl border border-mp-border bg-mp-surface-2 px-4 py-3 text-[13px]"
      >
        {active ? (
          <span className="text-mp-text">
            <strong>{active.symbol}</strong>{" "}
            <span className="text-mp-text-mut">{active.name}</span> ·{" "}
            <span className={active.change >= 0 ? "text-mp-success" : "text-mp-danger"}>
              {pct(active.change)}
            </span>{" "}
            <span className="text-mp-text-mut">
              · index weight {formatNumber(active.weight, 1)}%
            </span>
          </span>
        ) : (
          <span className="text-mp-text-mut">
            Hover or focus a tile for the full name, move and index weight.
          </span>
        )}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-[12px] font-semibold text-mp-text-mut">
          Day change
        </span>
        <div className="flex items-center gap-1">
          {STEPS.map((s, i) => (
            <span
              key={s.token}
              className="h-4 w-7 rounded"
              style={{ backgroundColor: `rgb(var(${s.token}))` }}
              aria-hidden
            />
          ))}
        </div>
        <span className="text-[12px] text-mp-text-mut">
          −3% or worse &nbsp;→&nbsp; flat &nbsp;→&nbsp; +3% or better
        </span>
      </div>

      <div className="rounded-xl border border-mp-border bg-mp-surface-2 p-4">
        <p className="text-[12px] leading-[1.65] text-mp-text-mut">
          <strong className="text-mp-text">This board is an indicative snapshot</strong>,
          not a live feed — the public site has no market session, so prices
          here are representative rather than real-time. Live, tick-by-tick
          prices for every NSE, BSE and MCX instrument are in the trading
          terminal.
        </p>
        <Link
          href="/register"
          className="mt-3 inline-flex items-center gap-1.5 text-[13px] font-semibold text-mp-primary hover:underline"
        >
          Open an account for live prices
          <ArrowRight className="size-3.5" />
        </Link>
      </div>
    </div>
  );
}
