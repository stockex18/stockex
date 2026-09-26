"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  HelpCircle,
  Loader2,
  ScanSearch,
  Wrench,
} from "lucide-react";
import { CheckTradesAPI, TradingAPI } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { PageHeader } from "@/components/common/PageHeader";
import { cn } from "@/lib/utils";

const num = (n: unknown, dp = 2) =>
  Number(n ?? 0).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp });

const range = (r: unknown) =>
  Array.isArray(r) && r[1] ? `${num(r[0])} – ${num(r[1])}` : "—";

type Ran = { from: string; to: string; timeFrom: string; timeTo: string };

function today() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

/** Yesterday, which is as far back as this page can look.
 *
 *  Not a policy choice — it is how long the raw tick store keeps what we
 *  were quoting. Inside it every fill is judged against our quote at its own
 *  SECOND; outside it there is nothing left to judge against. The server
 *  refuses a wider range, so the pickers refuse it here rather than letting
 *  the operator pick a date that can only come back as an error. */
function oldest() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
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
 * Check Trades — two questions per fill, kept apart on purpose.
 *
 * Was our feed right? Our own prices for that minute against the exchange's
 * one-minute candle. Was the fill right? The fill price against the bid and
 * ask we ourselves published in that same minute.
 *
 * They have to stay separate. A candle's high and low are TRADED prices, so
 * an ask sits above the high and a bid below the low by the spread. Judge a
 * market buy against the candle alone and every one of them reads "above
 * high" — arithmetic, not a finding.
 *
 * Finding one is only half of it, so a flagged row carries a Fix that hands
 * the correction to PATCH /admin/positions/{id} — the same path the Positions
 * page has always used, which recomputes realised P&L, posts the difference
 * to the user's wallet as a REVERSAL, rewrites the underlying fills so the
 * user's own history agrees, and pushes the change to their screen. Reusing
 * it is the point: a second way to move money is a second way to get it
 * wrong. Nothing is corrected without the operator confirming the figure.
 */
export default function CheckTradesPage() {
  const [from, setFrom] = useState(today());
  const [to, setTo] = useState(today());
  const [timeFrom, setTimeFrom] = useState("");
  const [timeTo, setTimeTo] = useState("");
  const [ran, setRan] = useState<Ran | null>(null);
  const [fixing, setFixing] = useState<any | null>(null);

  const { data, isFetching, error } = useQuery({
    queryKey: ["check-trades", ran],
    queryFn: () =>
      CheckTradesAPI.run({
        date_from: ran!.from,
        date_to: ran!.to,
        time_from: ran!.timeFrom || undefined,
        time_to: ran!.timeTo || undefined,
      }),
    enabled: !!ran,
    // The answer for a closed minute never changes, so never re-ask on its own.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qc = useQueryClient();
  const fix = useMutation({
    mutationFn: ({ row, price }: { row: any; price: string }) =>
      TradingAPI.editPosition(row.position_id, { [row.fix_field]: price }),
    onSuccess: () => {
      setFixing(null);
      // The corrected fill should no longer be flagged, and the position it
      // belongs to has moved — so re-ask rather than patch the row in place.
      qc.invalidateQueries({ queryKey: ["check-trades"] });
      qc.invalidateQueries({ queryKey: ["positions"] });
    },
  });

  const s = data?.summary ?? {};
  const rows: any[] = data?.rows ?? [];
  const skipped: any[] = data?.skipped ?? [];
  const bad = rows.filter((r) => r.verdict !== "OK");

  return (
    <div className="space-y-4">
      <PageHeader
        title="Check Trades"
        description="Every fill against the exchange's one-minute candle, and against the bid and ask we ourselves quoted that minute."
      />

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <ScanSearch className="size-4" /> Pick a period
          </CardTitle>
          <CardDescription>
            Today and yesterday only — that is how long every tick is kept, and the
            tick is what says the price we were quoting at the second a fill happened.
            Leave the times blank for whole days.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground">From</span>
              <Input
                type="date"
                min={oldest()}
                max={today()}
                value={from}
                onChange={(e) => setFrom(e.target.value)}
                className="h-10 w-[170px]"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                From time <span className="normal-case opacity-60">(optional)</span>
              </span>
              <Input
                type="time"
                value={timeFrom}
                onChange={(e) => setTimeFrom(e.target.value)}
                className="h-10 w-[135px]"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground">To</span>
              <Input
                type="date"
                min={oldest()}
                max={today()}
                value={to}
                onChange={(e) => setTo(e.target.value)}
                className="h-10 w-[170px]"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                To time <span className="normal-case opacity-60">(optional)</span>
              </span>
              <Input
                type="time"
                value={timeTo}
                onChange={(e) => setTimeTo(e.target.value)}
                className="h-10 w-[135px]"
              />
            </label>
            <Button
              onClick={() => setRan({ from, to, timeFrom, timeTo })}
              disabled={isFetching}
              className="h-10 gap-1.5"
            >
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
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <Stat
              label="Checked"
              value={s.checked ?? 0}
              hint={`${s.at_second ?? 0} at the second`}
            />
            <Stat label="Matched" value={s.ok ?? 0} tone="good" hint="feed and fill both right" />
            <Stat
              label="Feed off"
              value={s.feed_off ?? 0}
              tone={(s.feed_off ?? 0) > 0 ? "bad" : "good"}
              hint="our price ≠ exchange"
            />
            <Stat
              label="Fill off"
              value={s.fill_off ?? 0}
              tone={(s.fill_off ?? 0) > 0 ? "bad" : "good"}
              hint="outside our own quote"
            />
            <Stat
              label="Worst gap"
              value={`🪙${num(s.worst_off_by)}`}
              tone={(s.mismatched ?? 0) > 0 ? "bad" : "muted"}
            />
            <Stat label="Not checkable" value={s.not_checkable ?? 0} tone="muted" hint="no reference" />
          </div>

          {bad.length > 0 && (
            <Card className="border-destructive/40">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base text-destructive">
                  <AlertTriangle className="size-4" /> Priced wrong
                </CardTitle>
                <CardDescription>
                  <b>Feed</b> — our price for that minute did not match what the exchange
                  traded. <b>Fill</b> — the fill landed outside the bid and ask we were
                  showing at the time. Worst first.
                </CardDescription>
              </CardHeader>
              <CardContent className="overflow-x-auto">
                <table className="w-full min-w-[1180px] text-sm">
                  <thead>
                    <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                      <th className="py-1.5 text-left font-medium">Minute</th>
                      <th className="py-1.5 text-left font-medium">User</th>
                      <th className="py-1.5 text-left font-medium">Symbol</th>
                      <th className="py-1.5 text-left font-medium">Side</th>
                      <th className="py-1.5 text-right font-medium">Qty</th>
                      <th className="py-1.5 text-right font-medium">Filled at</th>
                      <th className="py-1.5 text-right font-medium">Exchange</th>
                      <th className="py-1.5 text-right font-medium">Our price</th>
                      <th className="py-1.5 text-right font-medium">Our bid</th>
                      <th className="py-1.5 text-right font-medium">Our ask</th>
                      <th className="py-1.5 pl-3 text-left font-medium">What went wrong</th>
                      <th className="py-1.5 text-right font-medium">Off by</th>
                      <th className="py-1.5 pl-3 text-right font-medium">Fix</th>
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
                        <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                          {r.exchange_high ? `${num(r.exchange_low)} – ${num(r.exchange_high)}` : "—"}
                        </td>
                        <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                          {r.our_high ? `${num(r.our_low)} – ${num(r.our_high)}` : "—"}
                        </td>
                        <td className="py-1.5 text-right tabular-nums text-muted-foreground">{range(r.our_bid)}</td>
                        <td className="py-1.5 text-right tabular-nums text-muted-foreground">{range(r.our_ask)}</td>
                        <td className="py-1.5 pl-3 text-[11px]">
                          <span
                            className={cn(
                              "mr-1.5 rounded px-1.5 py-0.5 text-[10px] font-bold",
                              r.verdict === "FEED_OFF"
                                ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                                : "bg-red-500/15 text-red-500",
                            )}
                          >
                            {r.verdict === "FEED_OFF" ? "FEED" : "FILL"}
                          </span>
                          <span className="text-muted-foreground">{r.reason}</span>
                        </td>
                        <td className="py-1.5 text-right font-semibold tabular-nums text-destructive">
                          {num(r.off_by)}{" "}
                          <span className="text-[10px] font-normal">({num(r.off_pct, 3)}%)</span>
                        </td>
                        <td className="py-1.5 pl-3 text-right">
                          {r.position_id ? (
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-7 gap-1 text-[11px]"
                              onClick={() => setFixing(r)}
                            >
                              <Wrench className="size-3" /> Fix
                            </Button>
                          ) : (
                            <span className="text-[10px] text-muted-foreground">
                              {r.fix_blocked || "—"}
                            </span>
                          )}
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
                Every fill in this period matched the exchange for its minute and sat inside
                the bid and ask we were quoting.
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
                  Nothing to judge these against — the exchange serves no minute history for
                  them, or the fill is older than our 30-day quote record. Saying
                  &quot;wrong&quot; about them would be worse than saying nothing.
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
                        <td className="py-1.5 pl-3 text-right text-[11px] text-muted-foreground">{r.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {fixing && (
        <FixDialog
          row={fixing}
          pending={fix.isPending}
          error={(fix.error as any)?.message}
          onClose={() => {
            fix.reset();
            setFixing(null);
          }}
          onConfirm={(price) => fix.mutate({ row: fixing, price })}
        />
      )}
    </div>
  );
}

/**
 * Confirm one correction, with the money shown before it moves.
 *
 * The suggested price is the nearest edge of the band the fill broke — the
 * closest price that was genuinely available — never a rate of our own
 * invention, though the operator can overrule it. The figure below it is what
 * this fill's P&L becomes; the wallet reversal the server posts is computed
 * from the position's full size, which is the same number whenever the leg
 * holds a single fill and is why a multi-fill leg says so out loud.
 */
function FixDialog({
  row,
  pending,
  error,
  onClose,
  onConfirm,
}: {
  row: any;
  pending: boolean;
  error?: string;
  onClose: () => void;
  onConfirm: (price: string) => void;
}) {
  const [price, setPrice] = useState(String(row.suggested_price ?? row.price ?? ""));
  const multi = (row.leg_fill_count ?? 1) > 1;

  // A buy that gets dearer, or a sell that gets cheaper, costs the user — one
  // formula covers both legs, because an opening fill moves the P&L the
  // opposite way a closing one does and the fill's own side already says which.
  const moved = (Number(price) || 0) - Number(row.price ?? 0);
  const delta = moved * Number(row.quantity ?? 0) * (row.action === "SELL" ? 1 : -1);

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Wrench className="size-4" /> Correct this fill
          </DialogTitle>
          <DialogDescription>
            {row.symbol} · {row.action} {num(row.quantity, 0)} · {row.minute} ·{" "}
            {row.user_code}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 text-sm">
          <p className="rounded-md border border-border/60 bg-muted/40 px-3 py-2 text-xs">
            {row.reason}
          </p>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Filled at
              </div>
              <div className="font-tabular text-lg font-bold line-through opacity-60">
                {num(row.price)}
              </div>
            </div>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Correct to
              </span>
              <Input
                type="number"
                step="0.01"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                className="h-10"
              />
            </label>
          </div>

          <div className="rounded-md border border-border/60 px-3 py-2 text-xs">
            Sets the position&apos;s{" "}
            <b>{row.fix_field === "avg_price" ? "entry price" : "close price"}</b>. The
            user&apos;s P&amp;L changes by{" "}
            <b className={delta >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-destructive"}>
              {delta >= 0 ? "+" : "−"}🪙{num(Math.abs(delta))}
            </b>
            , and the difference is posted to their wallet as a reversal. Their ledger,
            history and screen follow.
          </div>

          {multi && (
            <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
              This position has <b>{row.leg_fill_count} fills</b> on this leg. A correction
              sets them <b>all</b> to this one price — it cannot fix a single fill on its
              own. Check the position before confirming.
            </p>
          )}

          {error && (
            <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button
            onClick={() => onConfirm(price)}
            disabled={pending || !price || Number(price) <= 0}
            className="gap-1.5"
          >
            {pending && <Loader2 className="size-4 animate-spin" />}
            Correct and post
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
