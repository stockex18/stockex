"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, Coins, HandCoins, Landmark, RefreshCw, Wallet } from "lucide-react";
import { SaLedgerAPI } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/**
 * The super-admin's CASH book — real money only, never coins.
 *
 * Two streams, shown apart because the operator runs them apart:
 *
 *   SECURITY — the admin lodges cash as collateral, and what is left goes
 *              back when they withdraw.
 *   BOOKS    — the super-admin's own cash / bank / cheque books: the receipts
 *              and payments written by hand against those accounts.
 *
 * Brokerage, the P&L share and the games result are NOT here. Charging them
 * moves no money — they are earned, and they are read in the trial balance,
 * where each admin's account carries what they owe against them.
 *
 * Laid out the way a ledger is read rather than the way the data arrives:
 * what came in, what went out, and who it was with.
 */

const inr = (n: number) =>
  Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function Amount({ value, className }: { value: number; className?: string }) {
  const v = Number(value || 0);
  return (
    <span
      className={cn(
        "font-tabular tabular-nums",
        v < 0 ? "text-destructive" : undefined,
        className,
      )}
    >
      {inr(v)}
    </span>
  );
}

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: number;
  hint?: string;
  tone?: "in" | "out" | "earn";
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-card px-3 py-2.5">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div
        className={cn(
          "font-tabular text-lg font-semibold tabular-nums",
          tone === "earn" && "text-emerald-600 dark:text-emerald-400",
          tone === "out" && "text-destructive",
        )}
      >
        🪙{inr(value)}
      </div>
      {hint ? <div className="text-[11px] text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

function SectionTitle({ icon: Icon, children, note }: { icon: any; children: React.ReactNode; note?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border pb-1.5">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold">
        <Icon className="size-4 text-primary" /> {children}
      </h3>
      {note ? <span className="text-[11px] text-muted-foreground">{note}</span> : null}
    </div>
  );
}

export function SaCashBook() {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const { data, isFetching, refetch } = useQuery<any>({
    queryKey: ["sa-cash-book", from, to],
    queryFn: () => SaLedgerAPI.cashBook({ date_from: from || undefined, date_to: to || undefined }),
    staleTime: 15_000,
  });

  const t = data?.totals ?? {};
  const admins: any[] = data?.admins ?? [];
  const books: any[] = data?.books ?? [];
  const days: any[] = data?.days ?? [];
  const entries: any[] = data?.entries ?? [];

  const withActivity = useMemo(
    () =>
      admins.filter(
        (a) => a.cash_in || a.cash_out || a.security_balance || a.payable_balance,
      ),
    [admins],
  );

  return (
    <div className="space-y-5">
      {/* Period */}
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">From</div>
          <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-9 w-[160px]" />
        </div>
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">To</div>
          <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-9 w-[160px]" />
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
          <RefreshCw className={cn("size-4", isFetching && "animate-spin")} /> Refresh
        </Button>
        {(from || to) && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setFrom("");
              setTo("");
            }}
          >
            Whole book
          </Button>
        )}
        <span className="ml-auto text-[11px] text-muted-foreground">
          Real cash only — coins and wallet balances are not part of this book.
        </span>
      </div>

      {/* Earnings are not cash. Say where they went, once. */}
      <p className="flex items-start gap-1.5 rounded-lg border border-border/60 bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground">
        <Coins className="mt-0.5 size-3.5 shrink-0" />
        <span>
          Brokerage, P&amp;L share and games are <strong>earned, not received</strong> — charging
          them moves no money, so they are not in this book. They post to the income accounts
          against each admin&apos;s own account, and the Trial Balance is where they are read and
          reconciled.
        </span>
      </p>

      {/* Cash with the admins */}
      <section className="space-y-2">
        <SectionTitle icon={Wallet} note="security lodged with the super-admin">
          Security money
        </SectionTitle>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Received" value={t.cash_in ?? 0} hint="admin → super-admin" />
          <Stat label="Returned / funded" value={t.cash_out ?? 0} tone="out" hint="super-admin → admin" />
          <Stat label="Held now" value={t.security_balance ?? 0} hint="closing collateral" />
          <Stat label="Payable" value={t.payable_balance ?? 0} tone="out" hint="owed back to admins" />
        </div>
      </section>

      {/* The super-admin's own books */}
      <section className="space-y-2">
        <SectionTitle icon={Landmark} note="cash / bank / cheque accounts">
          Books
        </SectionTitle>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Stat label="Receipts" value={t.book_receipts ?? 0} />
          <Stat label="Payments" value={t.book_payments ?? 0} tone="out" />
          <Stat label="Net" value={t.book_net ?? 0} />
        </div>
        {books.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-1.5 text-left font-medium">Account</th>
                  <th className="py-1.5 text-right font-medium">Receipts</th>
                  <th className="py-1.5 text-right font-medium">Payments</th>
                  <th className="py-1.5 text-right font-medium">Net</th>
                </tr>
              </thead>
              <tbody>
                {books.map((b) => (
                  <tr key={b.name} className="border-b border-border/40">
                    <td className="py-1.5">{b.name}</td>
                    <td className="py-1.5 text-right"><Amount value={b.receipts} /></td>
                    <td className="py-1.5 text-right"><Amount value={b.payments} /></td>
                    <td className="py-1.5 text-right font-semibold"><Amount value={b.net} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Admin by admin */}
      <section className="space-y-2">
        <SectionTitle icon={HandCoins} note="what came in, what went back, and what is still with them">
          Admin accounts
        </SectionTitle>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-sm">
            <thead>
              <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                <th className="py-1.5 text-left font-medium">Admin</th>
                <th className="py-1.5 text-right font-medium">Cash in</th>
                <th className="py-1.5 text-right font-medium">Cash out</th>
                <th className="py-1.5 text-right font-medium">Held</th>
                <th className="py-1.5 text-right font-medium">Payable</th>
              </tr>
            </thead>
            <tbody>
              {withActivity.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-6 text-center text-muted-foreground">
                    {isFetching ? "Reading the book…" : "Nothing in this period."}
                  </td>
                </tr>
              ) : (
                withActivity.map((a) => (
                  <tr key={a.admin_id} className="border-b border-border/40">
                    <td className="py-1.5">
                      <span className="block font-medium">{a.admin_name}</span>
                      <span className="block font-mono text-[11px] text-muted-foreground">{a.admin_code}</span>
                    </td>
                    <td className="py-1.5 text-right"><Amount value={a.cash_in} /></td>
                    <td className="py-1.5 text-right"><Amount value={a.cash_out} /></td>
                    <td className="py-1.5 text-right"><Amount value={a.security_balance} /></td>
                    <td className="py-1.5 text-right"><Amount value={a.payable_balance} /></td>
                  </tr>
                ))
              )}
            </tbody>
            {withActivity.length > 0 && (
              <tfoot>
                <tr className="border-t-2 border-border font-semibold">
                  <td className="py-2">Total</td>
                  <td className="py-2 text-right"><Amount value={t.cash_in ?? 0} /></td>
                  <td className="py-2 text-right"><Amount value={t.cash_out ?? 0} /></td>
                  <td className="py-2 text-right"><Amount value={t.security_balance ?? 0} /></td>
                  <td className="py-2 text-right"><Amount value={t.payable_balance ?? 0} /></td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </section>

      {/* Day by day */}
      {days.length > 0 && (
        <section className="space-y-2">
          <SectionTitle icon={CalendarDays} note="most recent first">
            Day book
          </SectionTitle>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-1.5 text-left font-medium">Date</th>
                  <th className="py-1.5 text-right font-medium">Cash in</th>
                  <th className="py-1.5 text-right font-medium">Cash out</th>
                </tr>
              </thead>
              <tbody>
                {days.map((d) => (
                  <tr key={d.date} className="border-b border-border/40">
                    <td className="py-1.5 font-mono text-[12px]">{d.date}</td>
                    <td className="py-1.5 text-right"><Amount value={d.cash_in} /></td>
                    <td className="py-1.5 text-right"><Amount value={d.cash_out} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* The lines themselves */}
      {entries.length > 0 && (
        <section className="space-y-2">
          <SectionTitle icon={CalendarDays} note={`latest ${entries.length} lines`}>
            Statement
          </SectionTitle>
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-1.5 text-left font-medium">Date</th>
                  <th className="py-1.5 text-left font-medium">With</th>
                  <th className="py-1.5 text-left font-medium">Particulars</th>
                  <th className="py-1.5 text-right font-medium">Amount</th>
                  <th className="py-1.5 text-right font-medium">Balance</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e, i) => (
                  <tr key={i} className="border-b border-border/40">
                    <td className="whitespace-nowrap py-1.5 font-mono text-[11px]">
                      {new Date(e.date).toLocaleString("en-IN", {
                        day: "2-digit",
                        month: "short",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </td>
                    <td className="py-1.5">
                      <span className="block">{e.name}</span>
                      {e.code ? (
                        <span className="block font-mono text-[10px] text-muted-foreground">{e.code}</span>
                      ) : null}
                    </td>
                    <td className="py-1.5">
                      <span
                        className={cn(
                          "mr-1.5 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase",
                          e.stream === "SECURITY"
                            ? "bg-primary/10 text-primary"
                            : "bg-muted text-muted-foreground",
                        )}
                      >
                        {e.type}
                      </span>
                      <span className="text-muted-foreground">{e.narration}</span>
                    </td>
                    <td className="py-1.5 text-right"><Amount value={e.amount} /></td>
                    <td className="py-1.5 text-right text-muted-foreground">
                      {e.balance_after == null ? "—" : <Amount value={e.balance_after} />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
