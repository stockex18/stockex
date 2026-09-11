"use client";

/**
 * Record money moved with one admin, through one ledger.
 *
 * This is deliberately SEPARATE from the coin buttons on My Wallet. Adding or
 * deducting an admin's coins used to write a ledger line as a side effect,
 * which tied together two things that are not the same event:
 *
 *   coins   the platform's internal balance for that admin
 *   ledger  real money that arrived by cheque, UPI or bank
 *
 * They happen at different times, in different amounts, and either can happen
 * without the other — an admin can pay ₹5 lakh by cheque today against coins
 * given last week. Posting one from the other made both wrong, so the super
 * admin now records each on its own screen.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowDownToLine, ArrowUpFromLine, BookOpen, Check, ShieldCheck } from "lucide-react";
import { AdminMeAPI, LedgerBooksAPI } from "@/lib/api";
import { useAdminAuthStore } from "@/stores/authStore";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Direction = "RECEIVED" | "PAID";

function money(v: number): string {
  if (!Number.isFinite(v) || v <= 0) return "0.00";
  return v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function todayISO(): string {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

export function AdminEntryForm() {
  const qc = useQueryClient();

  const { data: members } = useQuery({
    queryKey: ["admin", "me", "members"],
    queryFn: () => AdminMeAPI.members(),
  });
  const { data: modes } = useQuery({
    queryKey: ["ledger-payment-modes"],
    queryFn: () => LedgerBooksAPI.paymentModes(),
  });

  const admins: any[] = useMemo(
    () => (members || []).filter((m: any) => m?.user_code),
    [members],
  );
  const ledgers: { code: string; label: string }[] = modes || [];

  // Security money is the super-admin's account with an admin — that
  // admin's games and brokerage settle against it — so only the super admin
  // gets the choice. Normal (P&L) is the plain ledger line it always was.
  const isSuper = useAdminAuthStore(
    (s) => String(s.admin?.role ?? "").toUpperCase() === "SUPER_ADMIN",
  );
  const [account, setAccount] = useState<"PNL" | "SECURITY">("PNL");
  const isSec = isSuper && account === "SECURITY";
  const [direction, setDirection] = useState<Direction>("RECEIVED");
  const [code, setCode] = useState("");
  const [mode, setMode] = useState("");
  const [date, setDate] = useState(todayISO());
  const [amount, setAmount] = useState("");
  const [narration, setNarration] = useState("");

  const amt = Number(amount);
  const valid = !!code && !!mode && Number.isFinite(amt) && amt > 0 && !!date;

  const who = admins.find((a) => a.user_code === code);
  const whoLabel = who ? `${who.full_name || who.user_code} (${who.user_code})` : "";
  const ledgerLabel = ledgers.find((l) => l.code === mode)?.label || mode;
  const isIn = direction === "RECEIVED";

  const post = useMutation({
    mutationFn: () =>
      LedgerBooksAPI.adminEntry({
        user_code: code,
        direction,
        amount: amt,
        mode,
        entry_date: new Date(date + "T00:00:00").toISOString(),
        narration: narration.trim() || undefined,
        account: isSec ? "SECURITY" : "PNL",
      }),
    onSuccess: () => {
      toast.success(
        `${isSec ? "Security " : ""}${isIn ? "Received" : "Paid"} 🪙${money(amt)} · ${ledgerLabel} · ${code}`,
      );
      qc.invalidateQueries({ queryKey: ["admin", "security-money"] });
      setAmount("");
      setNarration("");
      // Every view of this money re-reads: the ledger itself, the party
      // account, the day book and both trial balances.
      for (const k of [
        ["ledger-books"],
        ["ledger-parties"],
        ["ledger-statement"],
        ["ledger-party-statement"],
        ["ledger-daybook"],
        ["ledger-trial"],
      ]) {
        qc.invalidateQueries({ queryKey: k });
      }
    },
    onError: (e: any) => toast.error(e?.message || "Could not post the entry"),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BookOpen className="size-5 text-primary" />
          Record money with an admin
        </CardTitle>
        <CardDescription>
          Real money only — what actually reached you or left you, and through
          which ledger. Coins are a separate thing and live on My Wallet; an
          entry here moves no coins, and adding coins there posts nothing here.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        {isSuper && (
          <div className="grid grid-cols-2 gap-2 rounded-xl border border-border p-1">
            {([
              ["PNL", "Normal (P&L)", BookOpen],
              ["SECURITY", "Security Money", ShieldCheck],
            ] as const).map(([k, label, Icon]) => (
              <button
                key={k}
                type="button"
                onClick={() => setAccount(k)}
                className={cn(
                  "flex items-center justify-center gap-1.5 rounded-lg py-2 text-sm font-medium transition",
                  account === k ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className="size-4" /> {label}
              </button>
            ))}
          </div>
        )}

        {/* Direction first — it changes what every field below means, so it
            reads as a choice rather than a checkbox tucked in a corner. */}
        <div className="grid grid-cols-2 gap-3">
          {([
            ["RECEIVED", "Received", "They gave you money", ArrowDownToLine],
            ["PAID", "Paid", "You gave them money", ArrowUpFromLine],
          ] as const).map(([k, label, sub, Icon]) => {
            const on = direction === k;
            const good = k === "RECEIVED";
            return (
              <button
                key={k}
                type="button"
                onClick={() => setDirection(k)}
                className={cn(
                  "flex items-start gap-3 rounded-xl border p-3 text-left transition",
                  on
                    ? good
                      ? "border-buy/60 bg-buy/10"
                      : "border-sell/60 bg-sell/10"
                    : "border-border bg-muted/10 hover:bg-muted/20",
                )}
              >
                <Icon
                  className={cn(
                    "mt-0.5 size-5 shrink-0",
                    on ? (good ? "text-buy" : "text-sell") : "text-muted-foreground",
                  )}
                />
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5 font-semibold">
                    {label}
                    {on && <Check className="size-3.5" />}
                  </span>
                  <span className="block text-xs text-muted-foreground">{sub}</span>
                </span>
              </button>
            );
          })}
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Admin">
            <select
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="h-10 w-full rounded-md border border-input bg-background px-2 text-sm outline-none focus:ring-1 focus:ring-ring"
            >
              <option value="">Pick an admin…</option>
              {admins.map((a) => (
                <option key={a.user_code} value={a.user_code}>
                  {(a.full_name || a.user_code) + " · " + a.user_code}
                </option>
              ))}
            </select>
          </Field>

          <Field
            label="Ledger"
            hint={ledgers.length === 0 ? "Create one on the Accounts tab first" : undefined}
          >
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              className="h-10 w-full rounded-md border border-input bg-background px-2 text-sm outline-none focus:ring-1 focus:ring-ring"
            >
              <option value="">Cash / Cheque / UPI / bank…</option>
              {ledgers.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Amount">
            <Input
              type="number"
              inputMode="decimal"
              min={0}
              step="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0.00"
              className="tabular-nums"
            />
          </Field>

          <Field label="Date" hint={isSec ? "Security entries are dated today" : undefined}>
            <Input
              type="date"
              value={isSec ? todayISO() : date}
              onChange={(e) => setDate(e.target.value)}
              disabled={isSec}
            />
          </Field>

          <div className="md:col-span-2">
            <Field label="Narration" hint="Optional — defaults to the direction and code">
              <Input
                value={narration}
                onChange={(e) => setNarration(e.target.value)}
                placeholder={isIn ? `Received from ${code || "…"}` : `Paid to ${code || "…"}`}
              />
            </Field>
          </div>
        </div>

        {/* What is about to be written, in ledger terms. A posted line is hard
            to unsee, so it should be readable BEFORE the click, not after. */}
        <div
          className={cn(
            "rounded-xl border px-4 py-3 text-sm",
            valid ? (isIn ? "border-buy/40 bg-buy/5" : "border-sell/40 bg-sell/5") : "border-border bg-muted/10",
          )}
        >
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            This will post
          </div>
          {valid ? (
            <div className="mt-1 space-y-0.5">
              <div>
                <span className="font-medium">{ledgerLabel}</span>
                {" ledger — "}
                <span className={cn("font-semibold", isIn ? "text-buy" : "text-sell")}>
                  {isIn ? "Debit" : "Credit"} 🪙{money(amt)}
                </span>
              </div>
              <div className="text-xs text-muted-foreground">
                {whoLabel}
                {" · "}
                {isSec
                  ? isIn
                    ? "their SECURITY goes UP by this much — shows in their Security Money ledger"
                    : "their SECURITY comes DOWN by this much — shows in their Security Money ledger"
                  : isIn
                    ? "their account with you goes UP by this much"
                    : "their account with you comes DOWN by this much"}
                {" · no coins move"}
              </div>
            </div>
          ) : (
            <div className="mt-1 text-muted-foreground">
              Pick an admin, a ledger and an amount.
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          <Button
            type="button"
            disabled={!valid || post.isPending}
            loading={post.isPending}
            onClick={() => post.mutate()}
          >
            {isIn ? <ArrowDownToLine className="size-4" /> : <ArrowUpFromLine className="size-4" />}
            Post entry
          </Button>
          <span className="text-xs text-muted-foreground">
            Lands in the {ledgerLabel || "chosen"} ledger and in that admin&apos;s account.
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </label>
      {children}
      {hint && <p className="text-[10px] text-muted-foreground">{hint}</p>}
    </div>
  );
}
