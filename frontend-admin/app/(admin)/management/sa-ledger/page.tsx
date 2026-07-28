"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Coins, Wallet, TrendingUp, Receipt, Gamepad2, ArrowDownToLine, Plus, X } from "lucide-react";

import { SaLedgerAPI } from "@/lib/api";
import { formatINR } from "@/lib/utils";
import { useAdminAuthStore } from "@/stores/authStore";
import { PageHeader } from "@/components/common/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

function Money({ v, bold }: { v: any; bold?: boolean }) {
  const n = Number(v) || 0;
  return <span className={`tabular-nums ${bold ? "font-bold" : ""} ${n < 0 ? "text-red-500" : n > 0 ? "text-emerald-500" : ""}`}>{formatINR(v)}</span>;
}
function Tile({ label, value, accent }: { label: string; value: any; accent?: boolean }) {
  return (
    <div className={`rounded-lg border p-2.5 ${accent ? "border-primary/40 bg-primary/5" : "border-border/60 bg-background"}`}>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`mt-0.5 text-sm font-bold tabular-nums ${accent ? "text-primary" : "text-foreground"}`}>{formatINR(Number(value ?? 0))}</div>
    </div>
  );
}

export default function SaLedgerPage() {
  const admin = useAdminAuthStore((s) => s.admin);
  const qc = useQueryClient();
  const [topupOpen, setTopupOpen] = useState(false);
  const [topupAmt, setTopupAmt] = useState("");
  const [drillAdmin, setDrillAdmin] = useState<{ id: string; name: string } | null>(null);

  const q = useQuery({
    queryKey: ["sa-ledger"],
    queryFn: () => SaLedgerAPI.get(),
    enabled: admin?.role === "SUPER_ADMIN",
    refetchInterval: 15000,
  });
  const topup = useMutation({
    mutationFn: (amt: number) => SaLedgerAPI.cashTopup(amt),
    onSuccess: () => { toast.success("Cash wallet topped up"); setTopupOpen(false); setTopupAmt(""); qc.invalidateQueries({ queryKey: ["sa-ledger"] }); },
    onError: (e: any) => toast.error(e?.response?.data?.error?.message || e.message || "Failed"),
  });
  const drill = useQuery({
    queryKey: ["sa-ledger", "drill", drillAdmin?.id],
    queryFn: () => SaLedgerAPI.drill(drillAdmin!.id),
    enabled: !!drillAdmin,
  });

  if (admin?.role !== "SUPER_ADMIN") {
    return <div className="rounded-md border border-border bg-card p-6 text-sm text-muted-foreground">Only the super admin can view the ledger.</div>;
  }

  const cash = q.data?.cash ?? {};
  const rows: any[] = q.data?.rows ?? [];
  const t = q.data?.totals ?? {};

  return (
    <div className="space-y-4">
      <PageHeader title="Super Admin Ledger" description="Clear, section-wise money map — cash, funding, PnL, brokerage, games — every wallet reconciles." />

      {/* ── 1. CASH WALLET ─────────────────────────────────────── */}
      <Card>
        <CardHeader className="flex-row items-center justify-between pb-3">
          <CardTitle className="flex items-center gap-2"><Coins className="size-4 text-primary" /> Cash Wallet</CardTitle>
          <Button size="sm" onClick={() => setTopupOpen(true)}><Plus className="size-4" /> Top up</Button>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            <Tile label="Topped up (in)" value={cash.topped_up} />
            <Tile label="Given to admins" value={cash.given_to_admins} />
            <Tile label="Cash remaining" value={cash.cash_balance} accent />
            <Tile label="Main wallet" value={cash.main} />
            <Tile label="Kuber pool" value={cash.kuber} />
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">
            Cash remaining = Topped up − Given to admins. Funding an admin draws down this pool. (Kuber = separate house/games pool.)
          </p>
        </CardContent>
      </Card>

      {/* Grand-total strip */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        <Tile label="Funded to admins" value={t.funded} />
        <Tile label="To users/brokers" value={t.to_users} />
        <Tile label="Admin wallets now" value={t.wallet_now} />
        <Tile label="House PnL (users)" value={t.house_gain} />
        <Tile label="Brokerage" value={t.brokerage} />
        <Tile label="Games (house)" value={t.games} />
        <Tile label="Back to SA" value={t.back_to_sa} accent />
      </div>

      {/* ── 2. FUNDING & BALANCES ──────────────────────────────── */}
      <Section title="Funding & balances" icon={<Wallet className="size-4 text-primary" />}
        cols={["Admin", "Funded by SA", "To users/brokers", "Wallet now", "Match"]}
        rows={rows} render={(r) => (
          <>
            <AdminCell r={r} onDrill={() => setDrillAdmin({ id: r.admin_id, name: r.admin_name || r.admin_code })} />
            <td className="py-2 pr-3 text-right"><Money v={r.funded} /></td>
            <td className="py-2 pr-3 text-right text-red-500 tabular-nums">{formatINR(r.to_users)}</td>
            <td className="py-2 pr-3 text-right font-bold tabular-nums">{formatINR(r.wallet_now)}</td>
            <td className="py-2 text-right">{r.matched ? <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[11px] font-bold text-emerald-600">✓</span> : <span className="rounded bg-red-500/15 px-1.5 py-0.5 text-[11px] font-bold text-red-600">Δ{formatINR(r.delta)}</span>}</td>
          </>
        )} />

      {/* ── 3. TRADING PnL ─────────────────────────────────────── */}
      <Section title="Trading PnL (users → house)" icon={<TrendingUp className="size-4 text-primary" />}
        cols={["Admin", "Users' net PnL", "House gain"]}
        rows={rows.filter((r) => r.user_pnl !== 0 || r.house_gain !== 0)} render={(r) => (
          <>
            <AdminCell r={r} onDrill={() => setDrillAdmin({ id: r.admin_id, name: r.admin_name || r.admin_code })} />
            <td className="py-2 pr-3 text-right"><Money v={r.user_pnl} /></td>
            <td className="py-2 text-right"><Money v={r.house_gain} bold /></td>
          </>
        )} note="Users' net PnL: + means users profited (house paid). House gain = −users' PnL (user loss = house win)." />

      {/* ── 4. BROKERAGE ───────────────────────────────────────── */}
      <Section title="Brokerage (users → house)" icon={<Receipt className="size-4 text-primary" />}
        cols={["Admin", "Brokerage collected"]}
        rows={rows.filter((r) => r.brokerage !== 0)} render={(r) => (
          <>
            <AdminCell r={r} onDrill={() => setDrillAdmin({ id: r.admin_id, name: r.admin_name || r.admin_code })} />
            <td className="py-2 text-right"><Money v={r.brokerage} bold /></td>
          </>
        )} note="Click an admin to see per-broker + per-user brokerage." />

      {/* ── 5. GAMES ───────────────────────────────────────────── */}
      <Section title="Games (users → house)" icon={<Gamepad2 className="size-4 text-primary" />}
        cols={["Admin", "House games P&L"]}
        rows={rows.filter((r) => r.games !== 0)} render={(r) => (
          <>
            <AdminCell r={r} onDrill={() => setDrillAdmin({ id: r.admin_id, name: r.admin_name || r.admin_code })} />
            <td className="py-2 text-right"><Money v={r.games} bold /></td>
          </>
        )} note="+ means the house won from this admin's users at games; − means the house paid out." />

      {/* ── 6. BACK TO SA ──────────────────────────────────────── */}
      <Section title="Back to SA (admin-book income)" icon={<ArrowDownToLine className="size-4 text-primary" />}
        cols={["Admin", "PnL share", "Brokerage share", "Back to SA"]}
        rows={rows.filter((r) => r.back_to_sa !== 0)} render={(r) => (
          <>
            <AdminCell r={r} onDrill={() => setDrillAdmin({ id: r.admin_id, name: r.admin_name || r.admin_code })} />
            <td className="py-2 pr-3 text-right"><Money v={r.back_pnl} /></td>
            <td className="py-2 pr-3 text-right"><Money v={r.back_bkg} /></td>
            <td className="py-2 text-right"><Money v={r.back_to_sa} bold /></td>
          </>
        )} note="What the per-trade admin-book returned to your wallet (PnL share + brokerage share)." />

      {/* Top-up dialog */}
      <Dialog open={topupOpen} onOpenChange={setTopupOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>Top up cash wallet</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <Input type="number" placeholder="Amount 🪙" value={topupAmt} onChange={(e) => setTopupAmt(e.target.value)} />
            <Button className="w-full" loading={topup.isPending} disabled={!(Number(topupAmt) > 0)} onClick={() => topup.mutate(Number(topupAmt))}>Add to cash wallet</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Drill dialog */}
      <Dialog open={!!drillAdmin} onOpenChange={(o) => !o && setDrillAdmin(null)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader><DialogTitle className="flex items-center gap-2">{drillAdmin?.name} — breakdown</DialogTitle></DialogHeader>
          <div className="max-h-[70vh] space-y-4 overflow-y-auto">
            <div>
              <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Per broker — brokerage</div>
              <MiniTable cols={["Broker", "Brokerage"]} rows={drill.data?.brokers ?? []} render={(b: any) => (
                <><td className="py-1.5 pr-3"><div className="font-medium">{b.broker_name || b.broker_code}</div><div className="text-[11px] text-muted-foreground">{b.broker_code}</div></td><td className="py-1.5 text-right"><Money v={b.brokerage} /></td></>
              )} loading={drill.isLoading} />
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Per user — PnL / brokerage / games</div>
              <MiniTable cols={["User", "User PnL", "House gain", "Brokerage", "Games"]} rows={drill.data?.users ?? []} render={(u: any) => (
                <>
                  <td className="py-1.5 pr-3"><div className="font-medium">{u.user_name || u.user_code}</div><div className="text-[11px] text-muted-foreground">{u.user_code}</div></td>
                  <td className="py-1.5 pr-3 text-right"><Money v={u.user_pnl} /></td>
                  <td className="py-1.5 pr-3 text-right"><Money v={u.house_gain} /></td>
                  <td className="py-1.5 pr-3 text-right"><Money v={u.brokerage} /></td>
                  <td className="py-1.5 text-right"><Money v={u.games_house} /></td>
                </>
              )} loading={drill.isLoading} />
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function AdminCell({ r, onDrill }: { r: any; onDrill: () => void }) {
  return (
    <td className="py-2 pr-3">
      <button className="text-left hover:underline" onClick={onDrill}>
        <div className="font-medium">{r.admin_name || r.admin_code}</div>
        <div className="text-[11px] text-muted-foreground">{r.admin_code}</div>
      </button>
    </td>
  );
}

function Section({ title, icon, cols, rows, render, note }: { title: string; icon: React.ReactNode; cols: string[]; rows: any[]; render: (r: any) => React.ReactNode; note?: string }) {
  return (
    <Card>
      <CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-base">{icon} {title}</CardTitle></CardHeader>
      <CardContent className="overflow-x-auto">
        {rows.length === 0 ? <div className="py-3 text-sm text-muted-foreground">Nothing yet.</div> : (
          <table className="w-full min-w-[520px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                {cols.map((c, i) => <th key={c} className={`py-2 pr-3 ${i === 0 ? "" : "text-right"}`}>{c}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => <tr key={r.admin_id} className="border-b border-border/50 last:border-0">{render(r)}</tr>)}
            </tbody>
          </table>
        )}
        {note && <p className="mt-2 text-[11px] text-muted-foreground">{note}</p>}
      </CardContent>
    </Card>
  );
}

function MiniTable({ cols, rows, render, loading }: { cols: string[]; rows: any[]; render: (r: any) => React.ReactNode; loading?: boolean }) {
  if (loading) return <div className="py-2 text-sm text-muted-foreground">Loading…</div>;
  if (rows.length === 0) return <div className="py-2 text-sm text-muted-foreground">Nothing.</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[480px] text-sm">
        <thead><tr className="border-b border-border text-left text-[10px] uppercase tracking-wide text-muted-foreground">{cols.map((c, i) => <th key={c} className={`py-1.5 pr-3 ${i === 0 ? "" : "text-right"}`}>{c}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i} className="border-b border-border/40 last:border-0">{render(r)}</tr>)}</tbody>
      </table>
    </div>
  );
}
