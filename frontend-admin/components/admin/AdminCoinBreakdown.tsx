"use client";

/**
 * One admin's page behind their line in the coin trial balance.
 *
 * The trial balance answers "how much does this admin hold". This answers the
 * next question — how it got there — and it takes three sources, because the
 * money arrives by three different routes and no single one of them tells the
 * whole story:
 *
 *   cash / bank ledgers   physical money booked against them
 *   coin movements        funding, withdrawals, float, patti, brokerage, P&L
 *   security              collateral lodged, and what is payable back
 */

import { useQuery } from "@tanstack/react-query";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { LedgerBooksAPI } from "@/lib/api";
import { cn } from "@/lib/utils";

function money(v: unknown): string {
  const n = Number(v || 0);
  if (!Number.isFinite(n)) return "0.00";
  return n.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** Blank at zero — a ledger never prints 0.00 in a column the line does not
 *  touch. */
function cell(v: unknown): string {
  return Number(v || 0) ? money(v) : "";
}

function dmy(v?: string | null): string {
  if (!v) return "";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-GB").replace(/\//g, "-");
}

/** ADMIN_BOOK_BROKERAGE -> "Admin book brokerage". The raw enum is what the
 *  database calls it, not what an accountant reads. */
function label(t: string): string {
  const s = String(t || "").replace(/_/g, " ").toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function AdminCoinBreakdown({
  userCode,
  open,
  onOpenChange,
}: {
  userCode: string | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["coin-admin-breakdown", userCode],
    queryFn: () => LedgerBooksAPI.coinTrialBalanceAdmin(userCode!),
    enabled: open && !!userCode,
    staleTime: 5_000,
  });

  const ledger: any[] = data?.ledger || [];
  const coin: any[] = data?.coin || [];
  const sec = data?.security || {};

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-base">
            {data?.name || userCode}{" "}
            <span className="font-mono text-xs text-muted-foreground">{userCode}</span>
          </DialogTitle>
        </DialogHeader>

        {isLoading && (
          <p className="py-8 text-center text-sm text-muted-foreground">Loading…</p>
        )}

        {!isLoading && (
          <div className="space-y-5">
            {/* What they hold right now — the figure the trial balance shows. */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                ["Available", data?.wallet?.available],
                ["Margin locked", data?.wallet?.margin],
                ["Held commission", data?.wallet?.temporary],
                ["Total", data?.wallet?.total],
              ].map(([k, v], i) => (
                <div
                  key={String(k)}
                  className={cn(
                    "rounded-lg border border-border px-3 py-2",
                    i === 3 && "bg-muted/40",
                  )}
                >
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                    {k}
                  </p>
                  <p
                    className={cn(
                      "font-tabular tabular-nums",
                      i === 3 ? "text-base font-bold" : "text-sm font-semibold",
                    )}
                  >
                    {money(v)}
                  </p>
                </div>
              ))}
            </div>

            {/* ── cash / bank ─────────────────────────────────────── */}
            <Section title="Cash / Bank ledgers">
              {ledger.length === 0 ? (
                <Empty>No cash or bank entry is booked against this admin.</Empty>
              ) : (
                ledger.map((b) => (
                  <div key={b.book} className="mb-3">
                    <div className="flex items-baseline justify-between border-b border-border py-1.5">
                      <span className="text-[13px] font-semibold">{b.book}</span>
                      <span className="font-tabular text-[13px] font-semibold tabular-nums">
                        {money(b.net)}
                      </span>
                    </div>
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr className="text-[10px] uppercase tracking-wider text-muted-foreground">
                          <th className="py-1 text-left font-medium">Date</th>
                          <th className="py-1 text-left font-medium">Type</th>
                          <th className="py-1 text-left font-medium">Narration</th>
                          <th className="py-1 text-right font-medium">Debit</th>
                          <th className="py-1 text-right font-medium">Credit</th>
                        </tr>
                      </thead>
                      <tbody className="tabular-nums">
                        {b.entries.map((e: any, i: number) => (
                          <tr key={i} className="border-b border-border/40">
                            <td className="whitespace-nowrap py-1.5">{dmy(e.date)}</td>
                            <td className="py-1.5">{e.voucher_type}</td>
                            <td className="py-1.5 text-muted-foreground">{e.narration}</td>
                            <td className="py-1.5 text-right">{cell(e.debit)}</td>
                            <td className="py-1.5 text-right">{cell(e.credit)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))
              )}
            </Section>

            {/* ── coin movements ──────────────────────────────────── */}
            <Section title="Coin movements">
              {coin.length === 0 ? (
                <Empty>No coin has moved on this admin&apos;s wallet.</Empty>
              ) : (
                <table className="w-full text-[12px]">
                  <thead>
                    <tr className="border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
                      <th className="py-1 text-left font-medium">Movement</th>
                      <th className="py-1 text-right font-medium">Entries</th>
                      <th className="py-1 text-right font-medium">Amount</th>
                    </tr>
                  </thead>
                  <tbody className="tabular-nums">
                    {coin.map((c) => {
                      const amt = Number(c.amount || 0);
                      return (
                        <tr key={c.type} className="border-b border-border/40">
                          <td className="py-1.5">{label(c.type)}</td>
                          <td className="py-1.5 text-right text-muted-foreground">
                            {c.count}
                          </td>
                          <td
                            className={cn(
                              "py-1.5 text-right font-semibold",
                              amt < 0 ? "text-sell" : "text-buy",
                            )}
                          >
                            {money(amt)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </Section>

            {/* ── security ────────────────────────────────────────── */}
            <Section title="Security money">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-border px-3 py-2">
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                    Security held
                  </p>
                  <p className="font-tabular text-sm font-semibold tabular-nums">
                    {money(sec.security_balance)}
                  </p>
                </div>
                <div className="rounded-lg border border-border px-3 py-2">
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                    Payable to admin
                  </p>
                  <p className="font-tabular text-sm font-semibold tabular-nums">
                    {money(sec.payable_balance)}
                  </p>
                </div>
              </div>
            </Section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </p>
      {children}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-[12px] text-muted-foreground">
      {children}
    </p>
  );
}
