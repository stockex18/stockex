"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ShieldCheck,
  ArrowDownToLine,
  ArrowUpFromLine,
  Wallet,
  Search,
  Gamepad2,
} from "lucide-react";
import { PageHeader } from "@/components/common/PageHeader";
import { usePager, Pager } from "@/components/common/Pager";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { AdminSecurityAPI, ManagementAPI } from "@/lib/api";
import { formatINR, signedINR } from "@/lib/utils";
import { cn } from "@/lib/utils";

// Same five modes as the funding flow, so a security receipt is recorded the
// same way money is recorded everywhere else on this panel.
const MODES = [
  { v: "CASH", label: "StockEx Coin" },
  { v: "CHEQUE", label: "Cheque" },
  { v: "BANKING", label: "Banking" },
  { v: "UPI", label: "UPI" },
  { v: "OTHERS", label: "Others" },
];

const ENTRY_LABEL: Record<string, string> = {
  DEPOSIT: "Received",
  WITHDRAW: "Returned",
  SA_TOPUP: "Top-up (my wallet)",
  GAMES_PNL: "Games",
  ADJUSTMENT: "Adjustment",
};

export default function SecurityMoneyPage() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");

  const { data: rows, isLoading } = useQuery<any[]>({
    queryKey: ["admin", "security-money"],
    queryFn: () => AdminSecurityAPI.list(),
    refetchInterval: 10000,
  });

  const { data: entries } = useQuery<any[]>({
    queryKey: ["admin", "security-money", "entries"],
    queryFn: () => AdminSecurityAPI.entries(undefined, 200),
    refetchInterval: 10000,
  });

  const list = rows ?? [];
  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return list;
    return list.filter(
      (r) =>
        String(r.user_code || "").toLowerCase().includes(s) ||
        String(r.full_name || "").toLowerCase().includes(s),
    );
  }, [list, q]);

  const totalSec = list.reduce((s, r) => s + Number(r.security_balance || 0), 0);
  const totalPay = list.reduce((s, r) => s + Number(r.payable_balance || 0), 0);
  const pg = usePager(entries ?? [], 25);

  return (
    <div className="space-y-6 pb-24 md:pb-6">
      <PageHeader
        title="Security Money"
        description="Collateral each admin has lodged, and what you still owe them back."
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Card className="border-primary/30">
          <CardContent className="p-5">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground">
              <ShieldCheck className="size-4 text-primary" /> Total security held
            </div>
            <div className="mt-1 text-3xl font-bold tabular-nums text-primary">{formatINR(totalSec)}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              Falls when their users lose in games, rises when their users win
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground">
              <Wallet className="size-4" /> Total payable
            </div>
            <div className="mt-1 text-3xl font-bold tabular-nums">{formatINR(totalPay)}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              Owed from their book's losses — deposits don't create it, top-ups clear it
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3 pb-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-primary" /> Per admin
            </CardTitle>
            <CardDescription>Record what an admin gave you, return it, or fund it yourself.</CardDescription>
          </div>
          <div className="relative w-full max-w-xs">
            <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search code or name"
              className="pl-8"
            />
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {isLoading ? (
            <div className="py-6 text-center text-sm text-muted-foreground">Loading…</div>
          ) : filtered.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">
              No security recorded yet. Add one below.
            </div>
          ) : (
            filtered.map((r) => <AdminRow key={r.admin_id} row={r} onDone={() => qc.invalidateQueries({ queryKey: ["admin", "security-money"] })} />)
          )}
          <NewEntryRow onDone={() => qc.invalidateQueries({ queryKey: ["admin", "security-money"] })} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2">
            <Gamepad2 className="size-4 text-primary" /> Security ledger
          </CardTitle>
          <CardDescription>Every movement — deposits, returns, top-ups and games results.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {(entries ?? []).length === 0 ? (
            <div className="py-6 text-sm text-muted-foreground">Nothing yet.</div>
          ) : (
            <>
              <table className="w-full min-w-[620px] text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                    <th className="py-2 pr-3">When</th>
                    <th className="py-2 pr-3">Type</th>
                    <th className="py-2 pr-3">Detail</th>
                    <th className="py-2 pr-3 text-right">Amount</th>
                    <th className="py-2 text-right">Security after</th>
                  </tr>
                </thead>
                <tbody>
                  {pg.slice.map((e) => (
                    <tr key={e.id} className="border-b border-border/50 last:border-0">
                      <td className="py-2 pr-3 text-[11px] text-muted-foreground">
                        {e.created_at
                          ? new Date(e.created_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })
                          : "—"}
                      </td>
                      <td className="py-2 pr-3 text-xs font-medium">
                        {ENTRY_LABEL[e.entry_type] || e.entry_type}
                      </td>
                      <td className="py-2 pr-3 text-xs text-muted-foreground">{e.narration}</td>
                      <td
                        className={cn(
                          "py-2 pr-3 text-right font-bold tabular-nums",
                          Number(e.amount) < 0 ? "text-sell" : "text-buy",
                        )}
                      >
                        {signedINR(e.amount)}
                      </td>
                      <td className="py-2 text-right tabular-nums">{formatINR(e.security_after)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Pager {...pg} />
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function AdminRow({ row, onDone }: { row: any; onDone: () => void }) {
  const [amount, setAmount] = useState("");
  const [mode, setMode] = useState("CASH");

  const amt = Number(amount);
  const valid = Number.isFinite(amt) && amt > 0;
  const sec = Number(row.security_balance || 0);

  const run = (fn: () => Promise<any>, label: string) =>
    useMutationLike(fn, label, () => {
      setAmount("");
      onDone();
    });

  const deposit = run(() => AdminSecurityAPI.deposit(row.admin_id, amt, mode), "Security received");
  const withdraw = run(() => AdminSecurityAPI.withdraw(row.admin_id, amt, mode), "Security returned");
  const topup = run(() => AdminSecurityAPI.topup(row.admin_id, amt), "Topped up from your wallet");
  const busy = deposit.isPending || withdraw.isPending || topup.isPending;

  return (
    <div className="rounded-xl border border-border/60 bg-card p-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">{row.full_name || row.user_code}</span>
            <span className="font-mono text-xs text-muted-foreground">{row.user_code}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs">
            <span>
              <span className="text-muted-foreground">Security</span>{" "}
              <span className="font-bold tabular-nums text-primary">{formatINR(sec)}</span>
            </span>
            <span>
              <span className="text-muted-foreground">Payable</span>{" "}
              <span className="font-bold tabular-nums">{formatINR(row.payable_balance)}</span>
            </span>
            <span>
              <span className="text-muted-foreground">Users lost</span>{" "}
              <span className="font-bold tabular-nums text-buy">{formatINR(row.total_games_in)}</span>
            </span>
            <span>
              <span className="text-muted-foreground">Users won</span>{" "}
              <span className="font-bold tabular-nums text-sell">{formatINR(row.total_games_out)}</span>
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-2 lg:w-[30rem]">
          <div className="flex items-center gap-2">
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              className="h-9 rounded-md border border-input bg-background px-2 text-sm outline-none focus:ring-1 focus:ring-ring"
            >
              {MODES.map((m) => (
                <option key={m.v} value={m.v}>
                  {m.label}
                </option>
              ))}
            </select>
            <Input
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="Amount"
              inputMode="decimal"
              className="h-9 flex-1"
            />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <Button size="sm" disabled={!valid || busy} loading={deposit.isPending} onClick={deposit.run}
              title="They gave you money — security up, payable untouched">
              <ArrowDownToLine className="size-4" /> Received
            </Button>
            <Button size="sm" variant="outline" disabled={!valid || busy || amt > sec} loading={withdraw.isPending}
              onClick={withdraw.run}
              title={amt > sec ? `Only ${formatINR(sec)} held` : "Return it — security down, payable untouched"}>
              <ArrowUpFromLine className="size-4" /> Return
            </Button>
            <Button size="sm" variant="secondary" disabled={!valid || busy} loading={topup.isPending}
              onClick={topup.run}
              title="Fund it from your own wallet — security up, payable down (settles what you owe)">
              <Wallet className="size-4" /> Top-up
            </Button>
          </div>
          {valid && amt > sec && (
            <p className="text-[10px] text-muted-foreground">
              Return needs {formatINR(amt)} — only {formatINR(sec)} held.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

/** Add security for an admin who has no row yet — pick them by code. */
function NewEntryRow({ onDone }: { onDone: () => void }) {
  const [code, setCode] = useState("");
  const [amount, setAmount] = useState("");
  const [mode, setMode] = useState("CASH");

  const { data: admins } = useQuery<any[]>({
    queryKey: ["admin", "sub-admins", "for-security"],
    // listSubAdmins returns { items, meta } — unwrap to the rows we match on.
    queryFn: async () => ((await ManagementAPI.listSubAdmins({ page_size: 200 }))?.items ?? []),
    staleTime: 60_000,
  });

  const match = useMemo(() => {
    const s = code.trim().toLowerCase();
    if (!s) return null;
    return (
      (admins ?? []).find(
        (a: any) =>
          String(a.user_code || "").toLowerCase() === s ||
          String(a.full_name || "").toLowerCase() === s,
      ) ?? null
    );
  }, [admins, code]);

  const amt = Number(amount);
  const valid = Number.isFinite(amt) && amt > 0 && !!match;

  const add = useMutationLike(
    () => AdminSecurityAPI.deposit(match!.id, amt, mode),
    "Security recorded",
    () => {
      setCode("");
      setAmount("");
      onDone();
    },
  );

  return (
    <div className="rounded-xl border border-dashed border-border/70 p-3">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Add security for an admin
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <Input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="Admin ID / code (e.g. ADM77376465)"
          className="h-9 sm:w-64"
        />
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-2 text-sm outline-none focus:ring-1 focus:ring-ring"
        >
          {MODES.map((m) => (
            <option key={m.v} value={m.v}>
              {m.label}
            </option>
          ))}
        </select>
        <Input
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="Amount"
          inputMode="decimal"
          className="h-9 sm:w-40"
        />
        <Button size="sm" disabled={!valid || add.isPending} loading={add.isPending} onClick={add.run}>
          <ArrowDownToLine className="size-4" /> Record
        </Button>
      </div>
      {code.trim() && !match && (
        <p className="mt-1 text-[11px] text-muted-foreground">No admin matches that code.</p>
      )}
      {match && (
        <p className="mt-1 text-[11px] text-muted-foreground">
          → {match.full_name || match.user_code} ({match.user_code})
        </p>
      )}
    </div>
  );
}

/** Thin wrapper so each button gets its own pending state + uniform toasts. */
function useMutationLike(fn: () => Promise<any>, okMsg: string, onOk: () => void) {
  const m = useMutation({
    mutationFn: fn,
    onSuccess: () => {
      toast.success(okMsg);
      onOk();
    },
    onError: (e: any) => toast.error(e?.message || "Failed"),
  });
  return { isPending: m.isPending, run: () => m.mutate() };
}
