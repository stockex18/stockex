"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Search, ShieldCheck } from "lucide-react";
import { FyersAPI, type FyersCheckRow, type FyersCheckStatus } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/common/PageHeader";
import { FyersSetupCard } from "@/components/admin/FyersSetupCard";
import { useMarkFyersMismatchesSeen } from "@/components/admin/FyersMismatchBadge";
import { cn } from "@/lib/utils";

const num = (n: number | null | undefined, dp = 2) =>
  n == null
    ? "—"
    : Number(n).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp });

function today() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

const timeIST = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

const TABS: { key: FyersCheckStatus | "ALL"; label: string }[] = [
  { key: "MISMATCH", label: "Mismatch" },
  { key: "OK", label: "OK" },
  { key: "NOT_CHECKED", label: "Not checked" },
  { key: "ALL", label: "All" },
];

function StatusPill({ s }: { s: FyersCheckStatus }) {
  return (
    <span
      className={cn(
        "rounded px-1.5 py-0.5 text-[10px] font-bold",
        s === "MISMATCH" && "bg-destructive/15 text-destructive",
        s === "OK" && "bg-primary/15 text-primary",
        s === "NOT_CHECKED" && "bg-muted text-muted-foreground",
      )}
    >
      {s === "NOT_CHECKED" ? "NOT CHECKED" : s}
    </span>
  );
}

function FyersRange({ r }: { r: FyersCheckRow }) {
  if (r.fyers_bid != null && r.fyers_ask != null) {
    return (
      <>
        {num(r.fyers_bid)} – {num(r.fyers_ask)}
      </>
    );
  }
  return <>{num(r.fyers_ltp)}</>;
}

/**
 * Fyers Connect & Price Check — every MARKET order's Zerodha price, compared
 * with Fyers' price at the moment it was placed. Report-only: nothing on this
 * page (or behind it) ever blocks an order.
 *
 * Added at the client's request and suggestion (Nov 2026).
 */
export default function FyersCheckPage() {
  const [from, setFrom] = useState(today());
  const [to, setTo] = useState(today());
  const [tab, setTab] = useState<FyersCheckStatus | "ALL">("MISMATCH");
  const [q, setQ] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  const markSeen = useMarkFyersMismatchesSeen();

  useEffect(() => {
    const t = setTimeout(() => setQDebounced(q.trim()), 350);
    return () => clearTimeout(t);
  }, [q]);

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["fyers", "checks", from, to, tab, qDebounced],
    queryFn: () =>
      FyersAPI.checks({
        date_from: from,
        date_to: to,
        status: tab === "ALL" ? undefined : tab,
        q: qDebounced || undefined,
        limit: 300,
      }),
    refetchInterval: 30_000,
  });

  // Opening the page (and every refresh while it is open) counts as having
  // seen the mismatches, so the menu badge clears.
  useEffect(() => {
    markSeen();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const counts = data?.counts;
  const rows = data?.rows ?? [];
  const ticks = data?.tolerance_ticks ?? 1;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Fyers Connect & Price Check"
        description="Every market order's Zerodha price compared with Fyers at the moment it was placed. Orders are never blocked — mismatches are only reported here."
      />

      <FyersSetupCard />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="size-4 text-primary" /> Checks
          </CardTitle>
          <CardDescription>
            <b>Mismatch</b> — our price (ask for a BUY, bid for a SELL) was outside Fyers&apos;
            bid–ask range by more than {ticks} tick{ticks === 1 ? "" : "s"}.{" "}
            <b>Not checked</b> — Fyers could not answer (not connected, timeout, or no Fyers
            symbol); the order filled as normal.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground">From</span>
              <Input
                type="date"
                max={today()}
                value={from}
                onChange={(e) => setFrom(e.target.value)}
                className="h-9 w-[160px]"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground">To</span>
              <Input
                type="date"
                min={from}
                max={today()}
                value={to}
                onChange={(e) => setTo(e.target.value)}
                className="h-9 w-[160px]"
              />
            </label>
            <label className="relative min-w-[200px] flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Symbol, user code, name or order no."
                className="h-9 pl-8"
              />
            </label>
            {isFetching && <Loader2 className="mb-2.5 size-4 animate-spin text-muted-foreground" />}
          </div>

          <div className="flex flex-wrap gap-1.5">
            {TABS.map((t) => {
              const n =
                t.key === "ALL"
                  ? counts
                    ? counts.OK + counts.MISMATCH + counts.NOT_CHECKED
                    : undefined
                  : counts?.[t.key];
              return (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={cn(
                    "rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
                    tab === t.key
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:bg-accent",
                  )}
                >
                  {t.label}
                  {n != null && (
                    <span
                      className={cn(
                        "ml-1.5 font-tabular",
                        t.key === "MISMATCH" && n > 0 && "font-bold text-destructive",
                      )}
                    >
                      {n}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {isLoading ? (
            <p className="flex items-center gap-1.5 py-6 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading…
            </p>
          ) : rows.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              {tab === "MISMATCH" ? "No mismatches in this range." : "No checks in this range."}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1100px] text-sm">
                <thead>
                  <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                    <th className="py-1.5 text-left font-medium">Time (IST)</th>
                    <th className="py-1.5 text-left font-medium">Result</th>
                    <th className="py-1.5 text-left font-medium">User</th>
                    <th className="py-1.5 text-left font-medium">Symbol</th>
                    <th className="py-1.5 text-left font-medium">Side</th>
                    <th className="py-1.5 text-right font-medium">Qty</th>
                    <th className="py-1.5 text-right font-medium">Zerodha price</th>
                    <th className="py-1.5 text-right font-medium">Fyers bid – ask</th>
                    <th className="py-1.5 text-right font-medium">Off by</th>
                    <th className="py-1.5 text-right font-medium">Filled at</th>
                    <th className="py-1.5 pl-3 text-left font-medium">Order / note</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className="border-b border-border/40">
                      <td className="whitespace-nowrap py-1.5 font-mono text-[12px]">{timeIST(r.placed_at)}</td>
                      <td className="py-1.5">
                        <StatusPill s={r.status} />
                      </td>
                      <td className="py-1.5">
                        <div className="font-medium">{r.user_code}</div>
                        <div className="text-[11px] text-muted-foreground">{r.user_name}</div>
                      </td>
                      <td className="py-1.5">
                        <div className="font-medium">{r.symbol}</div>
                        <div className="text-[11px] text-muted-foreground">{r.fyers_symbol || r.exchange}</div>
                      </td>
                      <td
                        className={cn(
                          "py-1.5 font-semibold",
                          r.action === "BUY" ? "text-emerald-500" : "text-red-500",
                        )}
                      >
                        {r.action}
                      </td>
                      <td className="py-1.5 text-right font-tabular">{r.quantity}</td>
                      <td className="py-1.5 text-right font-tabular" title={`Zerodha bid ${num(r.zerodha_bid)} · ask ${num(r.zerodha_ask)} · LTP ${num(r.zerodha_ltp)}`}>
                        {num(r.compared_price)}
                      </td>
                      <td className="py-1.5 text-right font-tabular" title={`Fyers LTP ${num(r.fyers_ltp)}`}>
                        <FyersRange r={r} />
                      </td>
                      <td
                        className={cn(
                          "py-1.5 text-right font-tabular",
                          r.status === "MISMATCH" && "font-bold text-destructive",
                        )}
                      >
                        {r.difference ? num(r.difference) : "—"}
                      </td>
                      <td className="py-1.5 text-right font-tabular text-muted-foreground">{num(r.fill_price)}</td>
                      <td className="py-1.5 pl-3">
                        <div className="font-mono text-[11px]">{r.order_number}</div>
                        {r.note && <div className="text-[11px] text-muted-foreground">{r.note}</div>}
                        {r.fyers_latency_ms != null && !r.note && (
                          <div className="text-[11px] text-muted-foreground">Fyers {r.fyers_latency_ms} ms</div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
