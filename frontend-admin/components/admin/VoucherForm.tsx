"use client";

/**
 * Post a voucher the way an accountant would: one amount moving BETWEEN two
 * accounts, not a debit typed into one book and a credit typed into another
 * and hoped to match.
 *
 * The form only ever produces a balanced pair — same amount, one Dr, one Cr —
 * so the trial balance it feeds can never drift. The server checks it again
 * anyway; that check is the whole point of double entry.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowRight, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LedgerBooksAPI } from "@/lib/api";

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function VoucherForm({
  books,
  onDone,
}: {
  books: any[];
  onDone: () => void;
}) {
  const [date, setDate] = useState(today());
  const [vtype, setVtype] = useState("Rcpt");
  const [vno, setVno] = useState("");
  const [fromId, setFromId] = useState("");
  const [toId, setToId] = useState("");
  const [amount, setAmount] = useState("");
  const [narration, setNarration] = useState("");

  const post = useMutation({
    mutationFn: () =>
      LedgerBooksAPI.postVoucher({
        entry_date: new Date(date + "T00:00:00").toISOString(),
        voucher_type: vtype,
        voucher_no: vno,
        narration,
        // Debit what RECEIVES the value, credit what GIVES it — the two legs
        // are built from one amount, so they cannot disagree.
        legs: [
          { book_id: toId, debit: Number(amount) },
          { book_id: fromId, credit: Number(amount) },
        ],
      }),
    onSuccess: () => {
      toast.success("Voucher posted");
      setAmount("");
      setVno("");
      setNarration("");
      onDone();
    },
    onError: (e: any) => toast.error(e?.message || "Could not post the voucher"),
  });

  const amt = Number(amount);
  const valid = !!date && !!fromId && !!toId && fromId !== toId && Number.isFinite(amt) && amt > 0;
  const nameOf = (id: string) => books.find((b) => b.id === id)?.name || "";

  return (
    <div className="rounded-xl border border-border/60 bg-muted/30 p-3">
      <div className="mb-2 text-[10px] uppercase tracking-wider text-muted-foreground">
        New voucher — one amount, two accounts
      </div>

      <div className="grid gap-2 md:grid-cols-12">
        <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="h-9 md:col-span-2" />
        <select
          value={vtype}
          onChange={(e) => setVtype(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-2 text-sm outline-none focus:ring-1 focus:ring-ring md:col-span-1"
        >
          <option value="Rcpt">Rcpt</option>
          <option value="Pymt">Pymt</option>
          <option value="Jrnl">Jrnl</option>
        </select>
        <Input value={vno} onChange={(e) => setVno(e.target.value)} placeholder="Vch no." className="h-9 md:col-span-2" />

        <select
          value={fromId}
          onChange={(e) => setFromId(e.target.value)}
          title="The account the money comes FROM — credited"
          className="h-9 rounded-md border border-input bg-background px-2 text-sm outline-none focus:ring-1 focus:ring-ring md:col-span-3"
        >
          <option value="">From account (Cr)…</option>
          {books.map((b) => (
            <option key={b.id} value={b.id}>{b.name}</option>
          ))}
        </select>

        <select
          value={toId}
          onChange={(e) => setToId(e.target.value)}
          title="The account the money goes TO — debited"
          className="h-9 rounded-md border border-input bg-background px-2 text-sm outline-none focus:ring-1 focus:ring-ring md:col-span-3"
        >
          <option value="">To account (Dr)…</option>
          {books.map((b) => (
            <option key={b.id} value={b.id}>{b.name}</option>
          ))}
        </select>

        <Input
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="Amount"
          inputMode="decimal"
          className="h-9 md:col-span-1"
        />
      </div>

      <div className="mt-2 grid gap-2 md:grid-cols-12">
        <Input
          value={narration}
          onChange={(e) => setNarration(e.target.value)}
          placeholder="Narration"
          className="h-9 md:col-span-10"
        />
        <Button
          size="sm"
          disabled={!valid}
          loading={post.isPending}
          onClick={() => post.mutate()}
          className="md:col-span-2"
        >
          <Plus className="size-4" /> Post
        </Button>
      </div>

      {/* Show the entry as it will be written, so nobody has to hold the
          Dr/Cr convention in their head while typing. */}
      {valid && (
        <p className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
          <span className="text-buy">Dr</span> {nameOf(toId)}
          <ArrowRight className="size-3" />
          <span className="text-sell">Cr</span> {nameOf(fromId)}
          <span className="font-medium tabular-nums">
            {amt.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </p>
      )}
      {fromId && toId && fromId === toId && (
        <p className="mt-2 text-[11px] text-sell">Pick two different accounts.</p>
      )}
    </div>
  );
}
