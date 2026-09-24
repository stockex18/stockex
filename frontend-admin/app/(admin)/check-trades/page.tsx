"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  HelpCircle,
  Loader2,
  ScanSearch,
} from "lucide-react";
import { CheckTradesAPI } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/common/PageHeader";
import { cn } from "@/lib/utils";

const num = (n: unknown, dp = 2) =>
  Number(n ?? 0).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp });

function today() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function Stat({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: string | number;
  tone?: "good" | "bad" | "muted";
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-card px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div
        className={cn(
          "font-tabular text-xl font-bold leading-tight",
          tone === "good" && "text-emerald-600 dark:text-emerald-400",
          tone === "bad" && "text-destructive",
          tone === "muted" && "text-muted-foreground",
        )}
      >
        {value}
      </div>
      {hint && <div className="mt-0.5 text-[10px] text-muted-foreground">{hint}</div>}
    </div>
  );
}

/**
 * Check Trades — did the exchange print a price that covers this fill?
 *
 * For every fill in the window we pull the exchange's own one-minute candle
 * for that instrument and minute, and ask whether the fill price sits inside
 * that minute's high and low. A price outside it never traded on the
 * exchange: either the feed was stale or the fill was mispriced, and either
 * way it is the house that has to answer for it.
 *
 * Nothing here writes. It reports; correcting a trade stays a separate and
 * deliberate act on the trade itself.
 */
export default function CheckTradesPage() {
  const [from, setFrom] = useState(today());
  const [to, setTo] = useState(today());
  const [ran, setRan] = useState<{ from: string; to: string } | null>(null);

  const { data, isFetching, error } = useQuery({
    queryKey: ["check-trades", ran?.from, ran?.to],
    queryFn: () => CheckTradesAPI.run({ date_from: ran!.from, date_to: ran!.to }),
    enabled: !!ran,
    // The answer for a closed minute never changes, so never re-ask on its own.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const s = data?.summary ?? {};
  const rows: any[] = data?.rows ?? [];
  const skipped: any[] = data?.skipped ?? [];
  const bad = rows.filter((r) => r.verdict !== "OK");

  return (
    <div className="space-y-4">
      <PageHeader
        title="Check Trades"
        description="Every fill against the exchange's own one-minute candle — was the price inside that minute's high and low?"
      />

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <ScanSearch className="size-4" /> Pick a period
          </CardTitle>
          <CardDescription>
            Up to 7 days at a time. Candles are fetched once per instrument per day and
            cached, so re-running the same period costs nothing.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground">From</span>
              <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-10 w-[170px]" />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground">To</span>
              <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-10 w-[170px]" />
            </label>
            <Button onClick={() => setRan({ from, to })} disabled={isFetching} className="h-10 gap-1.5">
              {isFetching ? <Loader2 className="size-4 animate-spin" /> : <ScanSearch className="size-4" />}
              {isFetching ? "Checking…" : "Check trades"}
            </Button>
          </div>

          {error && (
            <p className="mt-3 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {(error as any)?.message || "Could not run the check."}
            </p>
          )}
        </CardContent>
      </Card>

      {data && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            <Stat label="Checked" value={s.checked ?? 0} hint="fills with a candle" />
            <Stat label="Matched" value={s.ok ?? 0} tone="good" hint="inside high / low" />
            <Stat
              label="Mismatched"
              value={s.mismatched ?? 0}
              tone={(s.mismatched ?? 0) > 0 ? "bad" : "good"}
              hint={`${s.above_high ?? 0} above · ${s.below_low ?? 0} below`}
            />
            <Stat label="Worst gap" value={`🪙${num(s.worst_off_by)}`} tone={(s.mismatched ?? 0) > 0 ? "bad" : "muted"} />
            <Stat label="Not checkable" value={s.not_checkable ?? 0} tone="muted" hint="no exchange candle" />
          </div>

          {bad.length > 0 && (
            <Card className="border-destructive/40">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base text-destructive">
                  <AlertTriangle className="size-4" /> Filled outside the exchange's range
                </CardTitle>
                <CardDescription>
                  The exchange never printed these prices in that minute. Worst first.
                </CardDescription>
              </CardHeader>
              <CardContent className="overflow-x-auto">
                <table className="w-full min-w-[980px] text-sm">
                  <thead>
                    <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                      <th className="py-1.5 text-left font-medium">Minute</th>
                      <th className="py-1.5 text-left font-medium">User</th>
                      <th className="py-1.5 text-left font-medium">Symbol</th>
                      <th className="py-1.5 text-left font-medium">Side</th>
                      <th className="py-1.5 text-right font-medium">Qty</th>
                      <th className="py-1.5 text-right font-medium">Filled at</th>
                      <th className="py-1.5 text-right font-medium">Exchange low</th>
                      <th className="py-1.5 text-right font-medium">Exchange high</th>
                      <th className="py-1.5 text-right font-medium">Off by</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bad.map((r) => (
                      <tr key={r.trade_id} className="border-b border-border/40">
                        <td className="py-1.5 font-mono text-[12px]">{r.minute}</td>
                        <td className="py-1.5 font-mono text-[11px]">{r.user_code}</td>
                        <td className="py-1.5 font-medium">{r.symbol}</td>
                        <td className="py-1.5">
                          <span
                            className={cn(
                              "rounded px-1.5 py-0.5 text-[10px] font-bold",
                              r.action === "BUY"
                                ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                                : "bg-red-500/15 text-red-500",
                            )}
                          >
                            {r.action}
                          </span>
                        </td>
                        <td className="py-1.5 text-right tabular-nums">{num(r.quantity, 0)}</td>
                        <td className="py-1.5 text-right font-semibold tabular-nums">{num(r.price)}</td>
                        <td className="py-1.5 text-right tabular-nums text-muted-foreground">{num(r.exchange_low)}</td>
                        <td className="py-1.5 text-right tabular-nums text-muted-foreground">{num(r.exchange_high)}</td>
                        <td className="py-1.5 text-right font-semibold tabular-nums text-destructive">
                          {r.verdict === "ABOVE_HIGH" ? "+" : "−"}
                          {num(r.off_by)}{" "}
                          <span className="text-[10px] font-normal">({num(r.off_pct, 3)}%)</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}

          {bad.length === 0 && (s.checked ?? 0) > 0 && (
            <Card className="border-emerald-500/40">
              <CardContent className="flex items-center gap-2 py-5 text-sm">
                <CheckCircle2 className="size-5 text-emerald-600 dark:text-emerald-400" />
                Every fill in this period sat inside the exchange's high and low for its minute.
              </CardContent>
            </Card>
          )}

          {(s.checked ?? 0) === 0 && (
            <Card>
              <CardContent className="py-6 text-center text-sm text-muted-foreground">
                No fills to check in this period.
              </CardContent>
            </Card>
          )}

          {skipped.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <HelpCircle className="size-4" /> Could not be checked
                </CardTitle>
                <CardDescription>
                  The exchange serves no minute history for these — crypto and forex, mostly.
                  Saying &quot;wrong&quot; about them would be worse than saying nothing.
                </CardDescription>
              </CardHeader>
              <CardContent className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-sm">
                  <tbody>
                    {skipped.slice(0, 50).map((r) => (
                      <tr key={r.trade_id} className="border-b border-border/40">
                        <td className="py-1.5 font-mono text-[12px]">{r.minute}</td>
                        <td className="py-1.5 font-mono text-[11px]">{r.user_code}</td>
                        <td className="py-1.5">{r.symbol}</td>
                        <td className="py-1.5 text-right tabular-nums">{num(r.price)}</td>
                        <td className="py-1.5 text-right text-[11px] text-muted-foreground">{r.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
