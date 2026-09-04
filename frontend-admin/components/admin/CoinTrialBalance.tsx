"use client";

/**
 * Trial balance for the coin economy.
 *
 * A different report from the cash-book trial balance beside it. That one
 * totals vouchers and can be out of balance when entries were written before
 * double entry existed. This one totals COINS, and squares by identity: every
 * coin that exists is sitting in exactly one wallet, so "what was issued" and
 * "where it is now" are the same quantity counted twice.
 *
 * Trading, brokerage, P&L, transfers — none of them create or destroy a coin,
 * so none of them can unbalance this. Only issuing and withdrawing move the
 * total, which is why the reconciliation note at the bottom is against the
 * transaction log rather than against the sheet itself.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, Download, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LedgerBooksAPI } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AdminCoinBreakdown } from "@/components/admin/AdminCoinBreakdown";

function money(v: unknown): string {
  const n = Number(v || 0);
  if (!Number.isFinite(n)) return "0.00";
  return n.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** Blank rather than 0.00 in the column a row does not touch — a printed
 *  ledger never fills both sides of one line. */
function cell(v: unknown, show: boolean): string {
  return show ? money(v) : "";
}

type Row = { group?: string; account?: string; debit?: string; credit?: string };

export function CoinTrialBalance() {
  const [asOn, setAsOn] = useState("");
  /** The admin whose breakdown is open, by user code. */
  const [drill, setDrill] = useState<string | null>(null);

  const iso = (d: string) => (d ? new Date(d + "T23:59:59").toISOString() : undefined);

  const { data, isLoading } = useQuery({
    queryKey: ["coin-trial-balance", asOn],
    queryFn: () => LedgerBooksAPI.coinTrialBalance(iso(asOn)),
    staleTime: 0,
    refetchInterval: 30_000,
  });

  const pdf = useMutation({
    mutationFn: () => LedgerBooksAPI.coinTrialBalancePdf(iso(asOn)),
    onSuccess: (blob: Blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `trial-balance-coins${asOn ? "-" + asOn : ""}.pdf`;
      // Firefox ignores a click on a detached anchor; revoking synchronously
      // can beat the save in Safari.
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast.success("Trial balance downloaded");
    },
    onError: (e: any) => toast.error(e?.message || "Could not build the PDF"),
  });

  const debitRows: Row[] = data?.debit_rows || [];
  const creditRows: Row[] = data?.credit_rows || [];
  const diff = Number(data?.difference || 0);
  const squared = Math.abs(diff) < 0.005;
  const rec = data?.reconciliation || {};
  const kuber = Number(data?.memo?.kuber_pool || 0);
  const unreconciled = Number(rec.unreconciled || 0);

  /** Rows with their group heading inserted where the group changes — the
   *  shape a printed trial balance has. */
  const withHeadings = useMemo(() => {
    const out: {
      heading?: string;
      row?: Row;
      side: "debit" | "credit";
      /** Set only on admin rows: the user code in brackets, which is what the
       *  breakdown endpoint takes. Computed here rather than in the JSX so the
       *  table body stays a flat map. */
      code?: string;
    }[] = [];
    const walk = (rows: Row[], side: "debit" | "credit") => {
      let last: string | undefined;
      for (const r of rows) {
        if (r.group !== last) {
          out.push({ heading: r.group, side });
          last = r.group;
        }
        const code =
          r.group === "Admins"
            ? /\(([A-Z0-9]+)\)\s*$/.exec(r.account || "")?.[1]
            : undefined;
        out.push({ row: r, side, code });
      }
    };
    walk(debitRows, "debit");
    walk(creditRows, "credit");
    return out;
  }, [debitRows, creditRows]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
            As on
          </label>
          <Input
            type="date"
            value={asOn}
            onChange={(e) => setAsOn(e.target.value)}
            className="h-9 w-[10rem]"
          />
        </div>

        <div className="flex items-center gap-3">
          <div
            className={cn(
              "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm",
              squared
                ? "border-buy/40 bg-buy/10 text-buy"
                : "border-sell/40 bg-sell/10 text-sell",
            )}
          >
            {squared ? (
              <Check className="size-4 shrink-0" />
            ) : (
              <TriangleAlert className="size-4 shrink-0" />
            )}
            <span className="font-semibold">
              {squared ? "Balanced" : `Out by ${money(Math.abs(diff))}`}
            </span>
          </div>
          <Button size="sm" loading={pdf.isPending} onClick={() => pdf.mutate()}>
            <Download className="size-4" /> PDF
          </Button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-sm">
          <thead>
            <tr className="border-y border-border text-[11px] uppercase tracking-wider text-muted-foreground">
              <th className="py-2 text-left font-medium">Particulars</th>
              <th className="py-2 text-right font-medium">Debit</th>
              <th className="py-2 text-right font-medium">Credit</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {isLoading && (
              <tr>
                <td colSpan={3} className="py-6 text-center text-muted-foreground">
                  Loading…
                </td>
              </tr>
            )}
            {withHeadings.map((item, i) =>
              item.heading != null ? (
                <tr key={`h${i}`} className="bg-muted/40">
                  <td
                    colSpan={3}
                    className="px-1 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground"
                  >
                    {item.heading}
                  </td>
                </tr>
              ) : (
                <tr
                  key={`r${i}`}
                  className={cn(
                    "border-b border-border/40",
                    item.code && "cursor-pointer hover:bg-muted/40",
                  )}
                  onClick={item.code ? () => setDrill(item.code!) : undefined}
                  title={item.code ? "See where this came from" : undefined}
                >
                  <td className="py-2 pl-4">
                    {item.row?.account}
                    {item.code && (
                      <span className="ml-2 text-[10px] uppercase tracking-wide text-primary">
                        details
                      </span>
                    )}
                  </td>
                  <td className="py-2 text-right">
                    {cell(item.row?.debit, item.side === "debit")}
                  </td>
                  <td className="py-2 text-right">
                    {cell(item.row?.credit, item.side === "credit")}
                  </td>
                </tr>
              ),
            )}
            <tr className="border-t-2 border-border font-bold">
              <td className="py-2.5 text-right">Grand Total</td>
              <td className="py-2.5 text-right">{money(data?.total_debit)}</td>
              <td className="py-2.5 text-right">{money(data?.total_credit)}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <AdminCoinBreakdown
        userCode={drill}
        open={!!drill}
        onOpenChange={(v) => !v && setDrill(null)}
      />

      {/* The Kuber pool is out of the totals on purpose, but a pool that size
          going unmentioned would be the more misleading choice. */}
      {kuber > 0 && (
        <div className="flex flex-wrap items-baseline justify-between gap-2 rounded-lg border border-border bg-muted/20 px-3 py-2 text-[12px]">
          <span>
            <span className="font-semibold">Memo — Kuber Pool</span>{" "}
            <span className="text-muted-foreground">
              (separate house pool, not part of this sheet)
            </span>
          </span>
          <span className="font-tabular font-semibold tabular-nums">{money(kuber)}</span>
        </div>
      )}

      {/* The sheet squares by identity, so a total that matches proves nothing
          on its own. This is where the claim can actually be checked. */}
      <div className="rounded-lg border border-border bg-muted/30 p-3 text-[12px] leading-relaxed">
        <p className="font-semibold">Reconciliation with the transaction log</p>
        <div className="mt-1.5 grid gap-x-6 gap-y-0.5 sm:grid-cols-2">
          <Line label="Issued, per log" value={rec.logged_minted} />
          <Line label="Withdrawn, per log" value={rec.logged_burned} />
          <Line label="Net, per log" value={rec.logged_net} />
          <Line label="Held in wallets" value={rec.in_wallets} />
        </div>
        <p
          className={cn(
            "mt-1.5 font-semibold",
            Math.abs(unreconciled) < 0.005 ? "text-buy" : "text-amber-600 dark:text-amber-400",
          )}
        >
          Unreconciled: {money(unreconciled)}
        </p>
        <p className="mt-1 text-muted-foreground">
          The sheet is built from wallet balances — the reliable record of where
          every coin is. The transaction log covers only part of the history,
          because balances seeded directly were never journalled, so a
          difference here is expected on old data.{" "}
          <strong className="text-foreground">
            What matters is that it does not grow:
          </strong>{" "}
          every movement from now on is journalled, so any increase is a coin
          that moved without a record.
        </p>
      </div>
    </div>
  );
}

function Line({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-tabular tabular-nums">{money(value)}</span>
    </div>
  );
}
