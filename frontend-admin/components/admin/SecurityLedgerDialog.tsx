"use client";

/**
 * One admin's security account, ruled the way a printed ledger is.
 *
 * Sides are the ordinary ones for a liability: collateral an admin lodges is
 * money you are HOLDING, so it is a CREDIT in their account and the balance
 * reads Cr — "you owe them this much". A games loss or your brokerage eats
 * into it, so those are DEBITS.
 *
 * The magnitude is the security figure on the card: the number can always be
 * explained by the rows under it, because the server replays the entries
 * rather than storing a balance. Payable runs in its own column, from what
 * was stored at the time of each entry.
 */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { AdminSecurityAPI } from "@/lib/api";
import { formatINR } from "@/lib/utils";

/** Blank at zero — a ledger never prints 0.00 in a column the line doesn't touch. */
function cell(v: unknown): string {
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

function dmy(v?: string | null): string {
  if (!v) return "";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-GB").replace(/\//g, "-");
}

/** Several rows share a date; the clock is what separates them. IST, because
 *  that is the day the rest of the platform books against. */
function hms(v?: string | null): string {
  if (!v) return "";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("en-GB", { hour12: false, timeZone: "Asia/Kolkata" });
}

export function SecurityLedgerDialog({
  row,
  open,
  onOpenChange,
}: {
  row: any;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const iso = (d: string, endOfDay = false) =>
    d ? new Date(d + (endOfDay ? "T23:59:59" : "T00:00:00")).toISOString() : undefined;

  const { data: st, isLoading } = useQuery({
    queryKey: ["security-statement", row.admin_id, start, end],
    queryFn: () => AdminSecurityAPI.statement(row.admin_id, iso(start), iso(end, true)),
    enabled: open,
    staleTime: 0,
    refetchInterval: open ? 8000 : false,
  });

  const pdf = useMutation({
    mutationFn: () => AdminSecurityAPI.pdf(row.admin_id, iso(start), iso(end, true)),
    onSuccess: (blob: Blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "security-" + row.user_code + ".pdf";
      // Firefox ignores a click on a detached anchor; revoking synchronously
      // can beat the save in Safari.
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast.success("Ledger PDF downloaded");
    },
    onError: (e: any) => toast.error(e?.message || "Could not build the PDF"),
  });

  const rows: any[] = st?.rows || [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl">
        <DialogHeader>
          <DialogTitle className="text-base">
            Security ledger — {row.full_name || row.user_code}{" "}
            <span className="font-mono text-xs text-muted-foreground">{row.user_code}</span>
          </DialogTitle>
        </DialogHeader>

        {/* The other half of the relationship, read alongside the collateral
            instead of from a different screen. */}
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
            <span>
              <span className="text-muted-foreground">Payable now</span>{" "}
              <span className="font-bold tabular-nums">
                {formatINR(st?.payable_balance ?? row.payable_balance)}
              </span>
            </span>
            <span>
              <span className="text-muted-foreground">Users lost</span>{" "}
              <span className="font-bold tabular-nums text-buy">{formatINR(st?.total_games_in ?? 0)}</span>
            </span>
            <span>
              <span className="text-muted-foreground">Users won</span>{" "}
              <span className="font-bold tabular-nums text-sell">{formatINR(st?.total_games_out ?? 0)}</span>
            </span>
            <span>
              <span className="text-muted-foreground">Brokerage</span>{" "}
              <span className="font-bold tabular-nums text-sell">{formatINR(st?.total_brokerage ?? 0)}</span>
            </span>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className="text-[10px] uppercase tracking-wider text-muted-foreground">From</label>
              <Input
                type="date"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                className="h-8 w-[8.5rem]"
              />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-muted-foreground">To</label>
              <Input
                type="date"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                className="h-8 w-[8.5rem]"
              />
            </div>
            <Button size="sm" loading={pdf.isPending} onClick={() => pdf.mutate()}>
              <Download className="size-4" /> PDF
            </Button>
          </div>
        </div>

        <div className="max-h-[55vh] overflow-auto">
          <table className="w-full min-w-[54rem] text-sm">
            <thead className="sticky top-0 bg-card">
              <tr className="border-y border-border text-[11px] uppercase tracking-wider text-muted-foreground">
                <th className="py-2 text-left font-medium">Date</th>
                <th className="py-2 text-left font-medium">Type</th>
                <th className="py-2 text-left font-medium">Vch No.</th>
                <th className="py-2 text-left font-medium">Client</th>
                <th className="py-2 text-left font-medium">Particulars</th>
                <th className="py-2 text-left font-medium">Narration</th>
                <th className="py-2 text-right font-medium">Debit</th>
                <th className="py-2 text-right font-medium">Credit</th>
                <th className="py-2 text-right font-medium">Balance</th>
                <th className="py-2 text-right font-medium">Payable</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              <tr className="border-b border-border/50">
                <td className="py-2">{dmy(st?.start)}</td>
                <td colSpan={3} />
                <td className="py-2 text-muted-foreground">Opening Balance</td>
                <td />
                <td className="py-2 text-right">
                  {st?.opening_side === "Dr" ? cell(st?.opening_balance) : ""}
                </td>
                <td className="py-2 text-right">
                  {st?.opening_side === "Cr" ? cell(st?.opening_balance) : ""}
                </td>
                <td className="whitespace-nowrap py-2 text-right font-medium">
                  {total(st?.opening_balance)} {st?.opening_side}
                </td>
                <td />
              </tr>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-border/40 hover:bg-muted/40">
                  <td className="whitespace-nowrap py-2">
                    {dmy(r.entry_date)}
                    <span className="block text-[10px] text-muted-foreground">{hms(r.entry_date)}</span>
                  </td>
                  <td className="py-2">{r.voucher_type}</td>
                  <td className="py-2 font-mono text-[11px]">{r.voucher_no}</td>
                  <td className="whitespace-nowrap py-2" title={r.client_name || ""}>
                    <span className="font-mono text-[11px]">{r.client_code}</span>
                  </td>
                  <td className="py-2">{r.particulars}</td>
                  <td className="py-2 text-muted-foreground">{r.narration}</td>
                  <td className="py-2 text-right text-buy">{cell(r.debit)}</td>
                  <td className="py-2 text-right text-sell">{cell(r.credit)}</td>
                  <td className="whitespace-nowrap py-2 text-right font-medium">
                    {total(r.balance)} {r.balance_side}
                  </td>
                  <td className="py-2 text-right tabular-nums text-muted-foreground">
                    {cell(r.payable_balance)}
                  </td>
                </tr>
              ))}
              {isLoading && (
                <tr>
                  <td colSpan={10} className="py-6 text-center text-muted-foreground">
                    Loading…
                  </td>
                </tr>
              )}
              {!isLoading && rows.length === 0 && (
                <tr>
                  <td colSpan={10} className="py-6 text-center text-muted-foreground">
                    No movement in this period.
                  </td>
                </tr>
              )}
            </tbody>
            <tfoot className="tabular-nums">
              <tr className="border-t border-border font-medium">
                <td colSpan={6} className="py-2 text-right text-muted-foreground">
                  Total
                </td>
                <td className="py-2 text-right">{total(st?.total_debit)}</td>
                <td className="py-2 text-right">{total(st?.total_credit)}</td>
                <td colSpan={2} />
              </tr>
              <tr>
                <td colSpan={6} className="py-1 text-right text-muted-foreground">
                  {st?.closing_side === "Dr" ? "Debit Balance" : "Credit Balance"}
                </td>
                <td className="py-1 text-right">
                  {st?.closing_side === "Cr" ? total(st?.closing_balance) : ""}
                </td>
                <td className="py-1 text-right">
                  {st?.closing_side === "Dr" ? total(st?.closing_balance) : ""}
                </td>
                <td className="py-1 text-right font-medium">
                  {total(st?.payable_balance)}
                </td>
              </tr>
              <tr className="border-t border-border font-bold">
                <td colSpan={6} className="py-2 text-right">
                  Grand Total
                </td>
                <td className="py-2 text-right">{total(st?.grand_total)}</td>
                <td className="py-2 text-right">{total(st?.grand_total)}</td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          </table>
        </div>

        <p className="text-[11px] text-muted-foreground">
          Credit = collateral they lodged · Debit = a games loss or your brokerage ate into it.
          A Cr balance is what you are holding of theirs. Payable is what their book's
          losses have earned them, as it stood at each entry.
        </p>
      </DialogContent>
    </Dialog>
  );
}
