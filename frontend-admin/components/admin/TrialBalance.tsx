"use client";

/**
 * Trial balance — every account's closing balance, and the proof they square.
 *
 * The "balanced" line is the point of the whole screen. It is only meaningful
 * over double-entry vouchers, so rows written before those existed are called
 * out separately: they sit in the balances but cannot square by themselves,
 * and a difference with no explanation reads as a bug.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, TriangleAlert } from "lucide-react";
import { Input } from "@/components/ui/input";
import { LedgerBooksAPI } from "@/lib/api";
import { cn } from "@/lib/utils";

const TYPE_LABEL: Record<string, string> = {
  CASH: "Cash",
  BANK: "Bank",
  PARTY: "Party accounts",
  INCOME: "Income",
  EXPENSE: "Expenses",
  OTHER: "Other",
};

function money(v: unknown): string {
  const n = Number(v || 0);
  if (!n) return "";
  return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function total(v: unknown): string {
  return Number(v || 0).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function TrialBalance() {
  const [asOf, setAsOf] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["trial-balance", asOf],
    queryFn: () =>
      LedgerBooksAPI.trialBalance(asOf ? new Date(asOf + "T23:59:59").toISOString() : undefined),
    staleTime: 0,
    refetchInterval: 15000,
  });

  const rows: any[] = data?.rows || [];
  const groups = Object.keys(TYPE_LABEL).filter((t) => rows.some((r) => r.account_type === t));
  const unlinked = Number(data?.unlinked_debit || 0) || Number(data?.unlinked_credit || 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <label className="text-[10px] uppercase tracking-wider text-muted-foreground">As on</label>
          <Input
            type="date"
            value={asOf}
            onChange={(e) => setAsOf(e.target.value)}
            className="h-9 w-[10rem]"
          />
        </div>
        {data && (
          <div
            className={cn(
              "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm",
              data.balanced
                ? "border-buy/40 bg-buy/10 text-buy"
                : "border-sell/40 bg-sell/10 text-sell",
            )}
          >
            {data.balanced ? <Check className="size-4" /> : <TriangleAlert className="size-4" />}
            {data.balanced
              ? "Balanced"
              : `Out by ${total(data.difference)} — debits and credits do not match`}
          </div>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[34rem] text-sm">
          <thead>
            <tr className="border-y border-border text-[11px] uppercase tracking-wider text-muted-foreground">
              <th className="py-2 text-left font-medium">Account</th>
              <th className="py-2 text-right font-medium">Debit</th>
              <th className="py-2 text-right font-medium">Credit</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {groups.map((t) => (
              <>
                <tr key={t} className="bg-muted/40">
                  <td colSpan={3} className="py-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    {TYPE_LABEL[t]}
                  </td>
                </tr>
                {rows
                  .filter((r) => r.account_type === t)
                  .map((r) => (
                    <tr key={r.book_id} className="border-b border-border/40">
                      <td className="py-2">{r.name}</td>
                      <td className="py-2 text-right text-buy">{money(r.debit)}</td>
                      <td className="py-2 text-right text-sell">{money(r.credit)}</td>
                    </tr>
                  ))}
              </>
            ))}
            {isLoading && (
              <tr>
                <td colSpan={3} className="py-6 text-center text-muted-foreground">Loading…</td>
              </tr>
            )}
            {!isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={3} className="py-6 text-center text-muted-foreground">
                  No balances yet.
                </td>
              </tr>
            )}
          </tbody>
          <tfoot className="tabular-nums">
            <tr className="border-t border-border font-bold">
              <td className="py-2 text-right">Total</td>
              <td className="py-2 text-right">{total(data?.total_debit)}</td>
              <td className="py-2 text-right">{total(data?.total_credit)}</td>
            </tr>
          </tfoot>
        </table>
      </div>

      {unlinked > 0 && (
        <p className="rounded-lg border border-border/60 bg-muted/30 p-2.5 text-[11px] text-muted-foreground">
          <span className="font-medium">Why it may not square:</span> {total(data.unlinked_debit)} debit
          and {total(data.unlinked_credit)} credit come from entries posted before double-entry
          vouchers existed. Those lines have no other side to balance against — every voucher posted
          from now on does.
        </p>
      )}
    </div>
  );
}
