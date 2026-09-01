"use client";

/**
 * Day book — every voucher in the period, one row per VOUCHER rather than per
 * line, with its legs underneath. That is the shape that makes double entry
 * readable: you see the whole "Cash Dr / Shivam Cr" movement together instead
 * of two rows in two different accounts.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Input } from "@/components/ui/input";
import { LedgerBooksAPI } from "@/lib/api";

function money(v: unknown): string {
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

function hm(v?: string | null): string {
  if (!v) return "";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("en-GB", { hour12: false, timeZone: "Asia/Kolkata" }).slice(0, 5);
}

export function DayBook() {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["day-book", start, end],
    queryFn: () =>
      LedgerBooksAPI.dayBook(
        start ? new Date(start + "T00:00:00").toISOString() : undefined,
        end ? new Date(end + "T23:59:59").toISOString() : undefined,
      ),
    staleTime: 0,
    refetchInterval: 15000,
  });

  const rows: any[] = data || [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label className="text-[10px] uppercase tracking-wider text-muted-foreground">From</label>
          <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="h-9 w-[9.5rem]" />
        </div>
        <div>
          <label className="text-[10px] uppercase tracking-wider text-muted-foreground">To</label>
          <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="h-9 w-[9.5rem]" />
        </div>
        <span className="pb-2 text-xs text-muted-foreground">{rows.length} vouchers</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[40rem] text-sm">
          <thead>
            <tr className="border-y border-border text-[11px] uppercase tracking-wider text-muted-foreground">
              <th className="py-2 text-left font-medium">Date</th>
              <th className="py-2 text-left font-medium">Type</th>
              <th className="py-2 text-left font-medium">Vch No.</th>
              <th className="py-2 text-left font-medium">Accounts</th>
              <th className="py-2 text-left font-medium">Narration</th>
              <th className="py-2 text-right font-medium">Amount</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map((v) => (
              <tr key={v.voucher_id} className="border-b border-border/40 align-top hover:bg-muted/40">
                <td className="whitespace-nowrap py-2">
                  {dmy(v.entry_date)}
                  <span className="block text-[10px] text-muted-foreground">{hm(v.entry_date)}</span>
                </td>
                <td className="py-2">{v.voucher_type}</td>
                <td className="py-2 font-mono text-[11px]">{v.voucher_no}</td>
                <td className="py-2">
                  {(v.legs || []).map((l: any, i: number) => (
                    <span key={i} className="block text-[12px]">
                      {Number(l.debit) > 0 ? (
                        <>
                          <span className="text-buy">Dr</span> {l.book}{" "}
                          <span className="text-muted-foreground">{money(l.debit)}</span>
                        </>
                      ) : (
                        <>
                          <span className="pl-3 text-sell">Cr</span> {l.book}{" "}
                          <span className="text-muted-foreground">{money(l.credit)}</span>
                        </>
                      )}
                    </span>
                  ))}
                </td>
                <td className="py-2 text-muted-foreground">{v.narration}</td>
                <td className="whitespace-nowrap py-2 text-right font-medium">{money(v.amount)}</td>
              </tr>
            ))}
            {isLoading && (
              <tr>
                <td colSpan={6} className="py-6 text-center text-muted-foreground">Loading…</td>
              </tr>
            )}
            {!isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={6} className="py-6 text-center text-muted-foreground">
                  No vouchers in this period.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
