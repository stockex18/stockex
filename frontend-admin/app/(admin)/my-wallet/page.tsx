"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Wallet,
  Coins,
  Clock,
  PiggyBank,
  Vault,
  RefreshCw,
  ArrowLeftRight,
  Users,
  Search,
  ArrowRightLeft,
  Send,
  ReceiptText,
  ChevronRight,
  ArrowDownToLine,
  ArrowUpFromLine,
} from "lucide-react";
import { PageHeader } from "@/components/common/PageHeader";
import { usePager, Pager } from "@/components/common/Pager";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { AdminMeAPI, AdminKuberAPI, AdminFundAPI, AdminBookAPI } from "@/lib/api";
import { useAdminAuthStore } from "@/stores/authStore";
import { formatINR, signedINR } from "@/lib/utils";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<string, string> = {
  PENDING: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  FINALIZED: "bg-primary/10 text-primary",
  PAID: "bg-buy/15 text-buy",
  SETTLED: "bg-buy/15 text-buy",
};

const ROLE_LABEL: Record<string, string> = {
  SUPER_ADMIN: "Super admin",
  ADMIN: "Admin",
  BROKER: "Broker",
};

// How the money was received before generating coins into a member's wallet.
const FUND_MODES = [
  { v: "CASH", label: "StockEx Coin" },
  { v: "CHEQUE", label: "Cheque" },
  { v: "BANKING", label: "Banking" },
  { v: "UPI", label: "UPI" },
  { v: "OTHERS", label: "Others" },
];
const MODE_LABEL: Record<string, string> = Object.fromEntries(FUND_MODES.map((m) => [m.v, m.label]));

export default function MyWalletPage() {
  const role = useAdminAuthStore((s) => s.admin?.role) ?? "";
  const isSA = role === "SUPER_ADMIN";
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["admin", "me", "wallet"],
    queryFn: () => AdminMeAPI.wallet(),
    refetchInterval: 15000,
  });

  const held = Number(data?.temporary_balance ?? 0);
  const available = Number(data?.available_balance ?? 0);
  const outstanding = Number(data?.settlement_outstanding ?? 0);
  const history: any[] = data?.settlement_history || [];

  const releaseAll = useMutation({
    mutationFn: () => AdminMeAPI.releaseCommission(),
    onSuccess: (res: any) => {
      toast.success(`Moved ${formatINR(res?.released ?? held)} to main wallet`);
      qc.invalidateQueries({ queryKey: ["admin", "me", "wallet"] });
      qc.invalidateQueries({ queryKey: ["admin", "me", "ledger"] });
    },
    onError: (e: any) => toast.error(e?.message || "Release failed"),
  });

  return (
    <div className="space-y-6 pb-24 md:pb-6">
      <PageHeader
        title="My Wallet"
        description="Your balance, member funding and recent activity."
      />

      {/* ── Balance cards ─────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <BalanceCard
          icon={<Wallet className="size-5" />}
          label="Available balance"
          value={formatINR(available)}
          hint={isSA ? "Main wallet" : "Your float — dispensable to members"}
          accent
        />

        {isSA && <KuberBalanceCard />}

        <BalanceCard
          icon={<Coins className="size-5" />}
          label="Games earning (held)"
          value={formatINR(held)}
          hint={held > 0 ? "Move to your main wallet" : "Nothing held"}
          warn={held > 0}
          action={
            held > 0 ? (
              <Button
                size="sm"
                className="mt-3 w-full sm:w-auto"
                loading={releaseAll.isPending}
                onClick={() => releaseAll.mutate()}
              >
                <ArrowRightLeft className="size-4" /> Transfer to main
              </Button>
            ) : undefined
          }
          footer={
            <div className="mt-3 grid grid-cols-2 gap-2 border-t border-border/50 pt-2 text-[11px]">
              <div>
                <div className="uppercase tracking-wide text-muted-foreground">Earned</div>
                <div className="font-bold tabular-nums">{formatINR(data?.temporary_total_earned ?? 0)}</div>
              </div>
              <div>
                <div className="uppercase tracking-wide text-muted-foreground">Released</div>
                <div className="font-bold tabular-nums text-buy">{formatINR(data?.temporary_total_released ?? 0)}</div>
              </div>
            </div>
          }
        />

        <BalanceCard
          icon={<PiggyBank className="size-5" />}
          label="Settlement outstanding"
          value={formatINR(outstanding)}
          hint="Unrecovered dues (record only)"
          danger={outstanding > 0}
        />
      </div>

      {/* ── Total coins generated (SUPER_ADMIN only) ──────────────── */}
      {isSA && <CoinGenerationBox />}

      {/* ── Kuber controls (SUPER_ADMIN only) ─────────────────────── */}
      {isSA && <KuberControls />}

      {/* ── Admin-book: per-trade PnL + brokerage coming in from admins ── */}
      {isSA && <SaAdminBookSection />}

      {/* ── Fund my members ───────────────────────────────────────── */}
      <FundMembersSection role={role} />

      {/* ── Per-trade earnings (what came to this node from trading) ── */}
      <TradeEarningsSection />

      {/* ── Recent ledger ─────────────────────────────────────────── */}
      <LedgerSection />

      {/* ── P&L-share settlements ─────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>P&amp;L-share settlements</CardTitle>
          <CardDescription>Your weekly trading P&amp;L-share settlement history.</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="py-6 text-center text-sm text-muted-foreground">Loading…</div>
          ) : history.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">No settlements yet.</div>
          ) : (
            <>
              {/* Mobile: stacked cards */}
              <div className="space-y-2 md:hidden">
                {history.map((h, i) => (
                  <div key={i} className="rounded-xl border border-border/60 bg-card p-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-muted-foreground">
                        {fmtRange(h.period_start, h.period_end)}
                      </span>
                      <StatusPill status={h.status} />
                    </div>
                    <div className="mt-2 flex items-end justify-between border-t border-border/50 pt-2">
                      <div>
                        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Net house P&amp;L</div>
                        <div className="font-tabular text-sm tabular-nums">{formatINR(h.net_house_pnl)}</div>
                      </div>
                      <div className="text-right">
                        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Your share</div>
                        <div className="font-tabular text-base font-bold tabular-nums text-buy">{formatINR(h.share)}</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              {/* Desktop: table */}
              <div className="hidden overflow-x-auto md:block">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                      <th className="py-2 pr-3 font-medium">Period</th>
                      <th className="py-2 pr-3 font-medium">Status</th>
                      <th className="py-2 pr-3 text-right font-medium">Net house P&amp;L</th>
                      <th className="py-2 text-right font-medium">Your share</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((h, i) => (
                      <tr key={i} className="border-b border-border/50 last:border-0">
                        <td className="py-2 pr-3 text-muted-foreground">{fmtRange(h.period_start, h.period_end)}</td>
                        <td className="py-2 pr-3"><StatusPill status={h.status} /></td>
                        <td className="py-2 pr-3 text-right font-tabular tabular-nums">{formatINR(h.net_house_pnl)}</td>
                        <td className="py-2 text-right font-tabular font-bold tabular-nums text-buy">{formatINR(h.share)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* ── Admin-book: per-trade PnL + brokerage the SA earns from admins ──
   Per-admin total cards + a live per-trade PnL/Brokerage transaction feed,
   right on the wallet page so it's clear where the money is coming from. */
function SaAdminBookSection() {
  const perAdmin = useQuery({
    queryKey: ["admin", "admin-book", "report"],
    queryFn: () => AdminBookAPI.report(),
    refetchInterval: 8000,
  });
  const txns = useQuery({
    queryKey: ["admin", "admin-book", "txns", "wallet"],
    queryFn: () => AdminBookAPI.transactions({ limit: 300 }),
    refetchInterval: 8000,
  });

  const admins: any[] = perAdmin.data || [];
  const rows: any[] = txns.data || [];
  const txPg = usePager(rows, 20);
  const totSa = admins.reduce((s, a) => s + (Number(a.sa_net) || 0), 0);
  const totPnl = admins.reduce((s, a) => s + (Number(a.sa_pnl_share) || 0), 0);
  const totBkg = admins.reduce((s, a) => s + (Number(a.sa_bkg_share) || 0), 0);

  const empty = admins.length === 0 && rows.length === 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Coins className="size-4 text-primary" /> Earnings from admins (per trade)
        </CardTitle>
        <CardDescription>
          Live PnL share + brokerage the super-admin skims from each admin&apos;s book on every
          closing trade. Full drill-down in Management → SA Earnings.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {empty ? (
          <div className="py-6 text-center text-sm text-muted-foreground">
            No earnings yet. Turn ON “Per-trade admin-book” in Admin Management; every closing
            trade then lands here.
          </div>
        ) : (
          <>
            {/* Grand total strip */}
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-xl border border-border/60 bg-card p-3">
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Total PnL share</div>
                <div className="mt-1 text-lg font-bold tabular-nums text-buy">{formatINR(totPnl)}</div>
              </div>
              <div className="rounded-xl border border-border/60 bg-card p-3">
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Total brokerage</div>
                <div className="mt-1 text-lg font-bold tabular-nums text-buy">{formatINR(totBkg)}</div>
              </div>
              <div className="rounded-xl border border-primary/40 bg-primary/5 p-3">
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Net to SA</div>
                <div className="mt-1 text-lg font-bold tabular-nums text-primary">{formatINR(totSa)}</div>
              </div>
            </div>

            {/* Per-admin cards — how much is coming from each admin */}
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                By admin
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {admins.map((a) => (
                  <div key={a.admin_id} className="rounded-xl border border-border/60 bg-card p-3">
                    <div className="flex items-center justify-between">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold">{a.admin_name || a.admin_code}</div>
                        <div className="text-[11px] text-muted-foreground">{a.admin_code} · {a.trades} trades</div>
                      </div>
                      <div className="text-right">
                        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Net</div>
                        <div className="text-base font-bold tabular-nums text-buy">{formatINR(a.sa_net)}</div>
                      </div>
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-2 border-t border-border/50 pt-2 text-[11px]">
                      <div>
                        <span className="text-muted-foreground">PnL: </span>
                        <span className="font-medium tabular-nums">{formatINR(a.sa_pnl_share)}</span>
                      </div>
                      <div className="text-right">
                        <span className="text-muted-foreground">Brok: </span>
                        <span className="font-medium tabular-nums">{formatINR(a.sa_bkg_share)}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Per-trade PnL / Brokerage transaction feed */}
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Transactions — per trade
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                      <th className="py-2 pr-3 font-medium">When</th>
                      <th className="py-2 pr-3 font-medium">Admin · User</th>
                      <th className="py-2 pr-3 font-medium">Symbol</th>
                      <th className="py-2 pr-3 text-right font-medium">PnL</th>
                      <th className="py-2 pr-3 text-right font-medium">Brokerage</th>
                      <th className="py-2 text-right font-medium">Net</th>
                    </tr>
                  </thead>
                  <tbody>
                    {txPg.slice.map((r) => (
                      <tr key={r.trade_id} className="border-b border-border/50 last:border-0">
                        <td className="py-2 pr-3 text-[11px] text-muted-foreground">
                          {r.booked_at ? new Date(r.booked_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) : "—"}
                        </td>
                        <td className="py-2 pr-3">
                          <div className="text-xs font-medium">{r.user_name || r.user_code || "—"}</div>
                          <div className="text-[11px] text-muted-foreground">
                            {r.user_code || ""}{r.admin_name || r.admin_code ? ` · ${r.admin_name || r.admin_code}` : ""}
                          </div>
                        </td>
                        <td className="py-2 pr-3 text-xs">{r.symbol || r.segment}</td>
                        <td className={cn("py-2 pr-3 text-right tabular-nums", Number(r.sa_pnl_share) < 0 ? "text-sell" : "text-buy")}>
                          {signedINR(r.sa_pnl_share)}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-buy">{signedINR(r.sa_bkg_share)}</td>
                        <td className={cn("py-2 text-right font-bold tabular-nums", Number(r.sa_net) < 0 ? "text-sell" : "text-buy")}>
                          {signedINR(r.sa_net)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager {...txPg} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

/* ── Kuber balance card (reads house-summary; SA only) ──────────── */
function KuberBalanceCard() {
  const { data } = useQuery({
    queryKey: ["admin", "me", "house-summary"],
    queryFn: () => AdminMeAPI.houseSummary(),
    refetchInterval: 15000,
  });
  return (
    <BalanceCard
      icon={<Vault className="size-5" />}
      label="Kuber pool"
      value={formatINR(data?.kuber_balance ?? 0)}
      hint="Distributable house pool (🪙100 cr cap)"
      accent
    />
  );
}

/* ── Kuber controls — top-up + main↔kuber transfer (SA only) ────── */
function KuberControls() {
  const qc = useQueryClient();
  const [amount, setAmount] = useState("");

  const { data } = useQuery({
    queryKey: ["admin", "me", "house-summary"],
    queryFn: () => AdminMeAPI.houseSummary(),
    refetchInterval: 15000,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["admin", "me", "house-summary"] });
    qc.invalidateQueries({ queryKey: ["admin", "me", "wallet"] });
  };

  const bootstrap = useMutation({
    mutationFn: () => AdminKuberAPI.bootstrap(),
    onSuccess: () => { toast.success("Kuber pool topped up to 🪙100 cr"); refresh(); },
    onError: (e: any) => toast.error(e?.message || "Failed"),
  });
  const transfer = useMutation({
    mutationFn: (dir: "to_kuber" | "to_main") => AdminKuberAPI.transfer(dir, Number(amount)),
    onSuccess: () => { toast.success("Transfer complete"); setAmount(""); refresh(); },
    onError: (e: any) => toast.error(e?.message || "Transfer failed"),
  });

  const amt = Number(amount);
  const valid = Number.isFinite(amt) && amt > 0;

  return (
    <Card className="overflow-hidden border-primary/30">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Vault className="size-4 text-primary" /> Kuber pool
        </CardTitle>
        <CardDescription>Move funds between your main wallet and the distributable house pool.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Kuber balance</div>
            <div className="mt-1 text-2xl font-bold tabular-nums text-primary">{formatINR(data?.kuber_balance ?? 0)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Main wallet</div>
            <div className="mt-1 text-2xl font-bold tabular-nums">{formatINR(data?.house_wallet_balance ?? 0)}</div>
          </div>
        </div>

        <div className="flex flex-col gap-2 border-t border-border pt-3 sm:flex-row sm:items-end">
          <div className="flex-1">
            <label className="text-xs text-muted-foreground">Transfer amount</label>
            <Input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" inputMode="decimal" />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" disabled={!valid || transfer.isPending} onClick={() => transfer.mutate("to_kuber")}>
              <ArrowLeftRight className="size-4" /> Main → Kuber
            </Button>
            <Button variant="outline" size="sm" disabled={!valid || transfer.isPending} onClick={() => transfer.mutate("to_main")}>
              <ArrowLeftRight className="size-4" /> Kuber → Main
            </Button>
            <Button size="sm" loading={bootstrap.isPending} onClick={() => bootstrap.mutate()}>
              <RefreshCw className="size-4" /> Top up to 🪙100 cr
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

/* ── Fund my members ────────────────────────────────────────────── */
/* ── Total coins generated → click for per-admin + payment-mode breakdown ── */
function CoinGenerationBox() {
  const [open, setOpen] = useState(false);
  const { data } = useQuery({
    queryKey: ["admin", "fund", "coin-summary"],
    queryFn: () => AdminFundAPI.coinSummary(),
    refetchInterval: 20000,
  });
  const total = Number(data?.total_generated ?? 0);
  const admins: any[] = data?.admins || [];

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="w-full rounded-2xl border border-primary/30 bg-primary/5 p-5 text-left transition hover:bg-primary/10"
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-primary">
            <Coins className="size-5" /> Total coins generated
          </div>
          <ChevronRight className="size-4 text-primary" />
        </div>
        <div className="mt-2 text-3xl font-extrabold tabular-nums">{formatINR(total)}</div>
        <div className="mt-1 text-xs text-muted-foreground">
          Across {admins.length} admin{admins.length === 1 ? "" : "s"} · tap for per-admin &amp; payment-mode breakdown
        </div>
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Coins generated — per admin</DialogTitle>
            <DialogDescription>
              How much you generated for each admin, how many times, and by which payment mode.
            </DialogDescription>
          </DialogHeader>
          {admins.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">Nothing generated yet.</div>
          ) : (
            <div className="max-h-[60vh] space-y-2 overflow-y-auto">
              {admins.map((a) => (
                <div key={a.id} className="rounded-xl border border-border/60 bg-card p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate font-medium">{a.full_name || a.user_code}</div>
                      <div className="font-mono text-xs text-muted-foreground">{a.user_code}</div>
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="text-lg font-bold tabular-nums">{formatINR(a.total)}</div>
                      <div className="text-[11px] text-muted-foreground">
                        {a.count} generation{a.count === 1 ? "" : "s"}
                      </div>
                    </div>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5 border-t border-border/50 pt-2">
                    {Object.entries(a.by_mode || {}).map(([m, amt]) => (
                      <span key={m} className="rounded bg-muted px-2 py-0.5 text-[11px]">
                        <span className="text-muted-foreground">{MODE_LABEL[m] || m}:</span>{" "}
                        <span className="font-bold tabular-nums">{formatINR(Number(amt))}</span>
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

function FundMembersSection({ role }: { role: string }) {
  const qc = useQueryClient();
  const [query, setQuery] = useState("");

  const { data: members, isLoading } = useQuery({
    queryKey: ["admin", "me", "members"],
    queryFn: () => AdminMeAPI.members(),
    refetchInterval: 20000,
  });

  const list: any[] = useMemo(() => {
    const rows = members || [];
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (m) =>
        String(m.user_code || "").toLowerCase().includes(q) ||
        String(m.full_name || "").toLowerCase().includes(q),
    );
  }, [members, query]);

  const targetLabel =
    role === "SUPER_ADMIN" ? "admins" : role === "ADMIN" ? "brokers" : "sub-brokers";

  const onFunded = () => {
    qc.invalidateQueries({ queryKey: ["admin", "me", "members"] });
    qc.invalidateQueries({ queryKey: ["admin", "me", "wallet"] });
    qc.invalidateQueries({ queryKey: ["admin", "me", "house-summary"] });
    qc.invalidateQueries({ queryKey: ["admin", "me", "ledger"] });
    qc.invalidateQueries({ queryKey: ["admin", "fund", "coin-summary"] });
  };

  return (
    <Card>
      <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Users className="size-4" /> Fund my members
          </CardTitle>
          <CardDescription>Add funds to your {targetLabel} from your available balance.</CardDescription>
        </div>
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search code or name"
            className="pl-8"
          />
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="py-6 text-center text-sm text-muted-foreground">Loading…</div>
        ) : (members || []).length === 0 ? (
          <div className="py-8 text-center text-sm text-muted-foreground">
            No {targetLabel} under you yet.
          </div>
        ) : list.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted-foreground">No members match “{query}”.</div>
        ) : (
          <div className="space-y-2">
            {list.map((m) => (
              <MemberRow key={m.id} member={m} onFunded={onFunded} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MemberRow({ member, onFunded }: { member: any; onFunded: () => void }) {
  const [amount, setAmount] = useState("");
  const [mode, setMode] = useState("CASH");
  const [open, setOpen] = useState(false);

  const fund = useMutation({
    mutationFn: () => AdminFundAPI.addToMember(member.id, Number(amount), undefined, mode),
    onSuccess: () => {
      toast.success(
        `Funded ${member.user_code || member.full_name} · ${formatINR(Number(amount))} · ${MODE_LABEL[mode]}`,
      );
      setAmount("");
      onFunded();
    },
    onError: (e: any) => toast.error(e?.message || "Funding failed"),
  });

  const given = Number(member.given_by_parent ?? 0);
  const deployed = Number(member.deployed_total ?? 0);
  const balance = Number(member.available_balance ?? 0);
  const held = Number(member.temporary_balance ?? 0);
  const usedPct = given > 0 ? Math.min(100, Math.round((deployed / given) * 100)) : 0;

  const amt = Number(amount);
  const valid = Number.isFinite(amt) && amt > 0;

  return (
    <>
      <div className="rounded-xl border border-border/60 bg-card p-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          {/* Clickable identity + fund-usage summary → opens full breakdown */}
          <button type="button" onClick={() => setOpen(true)} className="group min-w-0 flex-1 text-left">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium group-hover:underline">{member.full_name || member.user_code}</span>
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
                {ROLE_LABEL[member.role] || member.role}
              </span>
              <span className="font-mono text-xs text-muted-foreground">{member.user_code}</span>
              <ChevronRight className="size-3.5 text-muted-foreground transition group-hover:translate-x-0.5" />
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
              <Stat label="Given by you" value={formatINR(given)} />
              <Stat label="Deployed" value={formatINR(deployed)} tone="sell" />
              <Stat label="Balance" value={formatINR(balance)} tone="buy" />
              {held > 0 && <Stat label="Held" value={formatINR(held)} tone="amber" />}
            </div>
            {given > 0 && (
              <div className="mt-2 max-w-xs">
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${usedPct}%` }} />
                </div>
                <div className="mt-1 text-[10px] text-muted-foreground">{usedPct}% deployed · tap for full breakdown</div>
              </div>
            )}
          </button>
          {/* Fund control — amount + payment mode (how the money was received) */}
          <div className="flex items-center gap-2 md:w-[22rem]">
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              className="h-9 rounded-md border border-input bg-background px-2 text-sm outline-none focus:ring-1 focus:ring-ring"
              title="How you received this money"
            >
              {FUND_MODES.map((m) => (
                <option key={m.v} value={m.v}>{m.label}</option>
              ))}
            </select>
            <Input
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="Amount"
              inputMode="decimal"
              className="h-9 flex-1"
            />
            <Button size="sm" disabled={!valid || fund.isPending} loading={fund.isPending} onClick={() => fund.mutate()}>
              <Send className="size-4" /> Add
            </Button>
          </div>
        </div>
      </div>
      <MemberDetailDialog memberId={member.id} open={open} onOpenChange={setOpen} />
    </>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "buy" | "sell" | "amber" }) {
  const c =
    tone === "buy" ? "text-buy"
      : tone === "sell" ? "text-sell"
      : tone === "amber" ? "text-amber-600 dark:text-amber-400"
      : "text-foreground";
  return (
    <span className="inline-flex items-baseline gap-1">
      <span className="uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className={cn("font-bold tabular-nums", c)}>{value}</span>
    </span>
  );
}

/* ── Member fund-usage breakdown (click a member → how they used the money) ── */
function MemberDetailDialog({
  memberId, open, onOpenChange,
}: {
  memberId: string;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["admin", "me", "member-detail", memberId],
    queryFn: () => AdminMeAPI.memberFundDetail(memberId),
    enabled: open,
  });

  const m = data?.member;
  const s: any = data?.summary || {};
  const ledger: any[] = data?.ledger || [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {m?.full_name || m?.user_code || "Member"}
            {m?.role && (
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
                {ROLE_LABEL[m.role] || m.role}
              </span>
            )}
          </DialogTitle>
          <DialogDescription>
            {m?.user_code ? `${m.user_code} — ` : ""}how they used the funds you gave them.
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="py-10 text-center text-sm text-muted-foreground">Loading…</div>
        ) : (
          <div className="space-y-4">
            {/* Headline: given → deployed → balance */}
            <div className="grid grid-cols-3 gap-2">
              <BigStat label="Given by you" value={formatINR(s.given_by_parent ?? 0)} icon={<ArrowDownToLine className="size-3.5" />} tone="primary" />
              <BigStat label="Deployed" value={formatINR(s.deployed_total ?? 0)} icon={<ArrowUpFromLine className="size-3.5" />} tone="sell" />
              <BigStat label="Balance left" value={formatINR(s.current_balance ?? 0)} icon={<Wallet className="size-3.5" />} tone="buy" />
            </div>

            {/* Detailed breakdown (only rows with a value) */}
            <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
              <MiniStat label="To users (deposits)" value={formatINR(s.deployed_to_users ?? 0)} />
              {Number(s.funded_to_downline) > 0 && <MiniStat label="To brokers below" value={formatINR(s.funded_to_downline)} />}
              {Number(s.returned_from_users) > 0 && <MiniStat label="Returned by users" value={formatINR(s.returned_from_users)} />}
              {Number(s.pulled_back) > 0 && <MiniStat label="Pulled back by you" value={formatINR(s.pulled_back)} />}
              {Number(s.games_earned) > 0 && <MiniStat label="Games commission" value={formatINR(s.games_earned)} />}
              {Number(s.held) > 0 && <MiniStat label="Games held" value={formatINR(s.held)} />}
            </div>

            {/* Full ledger */}
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Full activity</div>
              {ledger.length === 0 ? (
                <div className="py-6 text-center text-sm text-muted-foreground">No fund activity yet.</div>
              ) : (
                <div className="max-h-72 overflow-y-auto rounded-lg border border-border/60">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 bg-card">
                      <tr className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                        <th className="px-3 py-2 font-medium">Type</th>
                        <th className="px-3 py-2 font-medium">Narration</th>
                        <th className="px-3 py-2 text-right font-medium">Amount</th>
                        <th className="px-3 py-2 text-right font-medium">Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ledger.map((r) => (
                        <tr key={r.id} className="border-b border-border/40 last:border-0">
                          <td className="px-3 py-2">
                            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
                              {prettyType(r.type)}
                            </span>
                          </td>
                          <td className="max-w-[220px] truncate px-3 py-2 text-muted-foreground">{r.narration || "—"}</td>
                          <td className={cn("px-3 py-2 text-right font-bold tabular-nums", Number(r.amount) >= 0 ? "text-buy" : "text-sell")}>
                            {signed(r.amount)}
                          </td>
                          <td className="px-3 py-2 text-right text-xs text-muted-foreground">{fmtDateTime(r.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function BigStat({ label, value, icon, tone }: { label: string; value: string; icon: React.ReactNode; tone: "primary" | "buy" | "sell" }) {
  const c = tone === "buy" ? "text-buy" : tone === "sell" ? "text-sell" : "text-primary";
  return (
    <div className="rounded-lg border border-border/60 bg-card p-3">
      <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground">
        {icon}
        {label}
      </div>
      <div className={cn("mt-1 text-base font-bold tabular-nums sm:text-lg", c)}>{value}</div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/50 bg-muted/30 px-2.5 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="font-bold tabular-nums">{value}</div>
    </div>
  );
}

/* ── Per-trade earnings — what came to THIS node (admin/broker/sub-broker)
   from each closing trade: admin-book PnL/brokerage, SA share, broker markup. */
function TradeEarningsSection() {
  const { data, isLoading } = useQuery({
    queryKey: ["admin", "me", "trade-earnings"],
    queryFn: () => AdminMeAPI.tradeEarnings(100),
    refetchInterval: 8000,
  });
  const rows: any[] = data || [];
  const total = rows.reduce((s, r) => s + (Number(r.amount) || 0), 0);

  const TYPE_LABEL: Record<string, string> = {
    ADMIN_BOOK_PNL: "PnL (book)",
    ADMIN_BOOK_BROKERAGE: "Brokerage (book)",
    SA_PNL_SHARE: "PnL share",
    SA_BROKERAGE_SHARE: "Brokerage share",
    BROKER_CASCADE_BROKERAGE: "Brokerage markup",
    PATTI_PNL: "Patti PnL",
    PATTI_BROKERAGE: "Patti brokerage",
  };

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between pb-3">
        <CardTitle className="flex items-center gap-2">
          <Coins className="size-4 text-primary" /> Trade earnings (per trade)
        </CardTitle>
        {rows.length > 0 && (
          <span className={`text-sm font-bold tabular-nums ${total < 0 ? "text-sell" : "text-buy"}`}>
            {signedINR(total)}
          </span>
        )}
      </CardHeader>
      <CardContent className="overflow-x-auto">
        {isLoading ? (
          <div className="py-4 text-sm text-muted-foreground">Loading…</div>
        ) : rows.length === 0 ? (
          <div className="py-4 text-sm text-muted-foreground">
            Nothing yet — earnings from your users&apos; / brokers&apos; trades will appear here per trade.
          </div>
        ) : (
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                <th className="py-2 pr-3">When</th>
                <th className="py-2 pr-3">Type</th>
                <th className="py-2 pr-3">From</th>
                <th className="py-2 text-right">Amount</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-border/50 last:border-0">
                  <td className="py-2 pr-3 text-[11px] text-muted-foreground">
                    {r.created_at ? new Date(r.created_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) : "—"}
                  </td>
                  <td className="py-2 pr-3 text-xs font-medium">{TYPE_LABEL[r.type] || r.type}</td>
                  <td className="py-2 pr-3 text-xs text-muted-foreground">{r.narration}</td>
                  <td className={`py-2 text-right font-bold tabular-nums ${Number(r.amount) < 0 ? "text-sell" : "text-buy"}`}>
                    {signedINR(r.amount)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

/* ── Recent ledger ──────────────────────────────────────────────── */
function LedgerSection() {
  const { data, isLoading } = useQuery({
    queryKey: ["admin", "me", "ledger"],
    queryFn: () => AdminMeAPI.ledger(200),
    refetchInterval: 20000,
  });

  const rows: any[] = data || [];
  const pg = usePager(rows, 20);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ReceiptText className="size-4" /> Recent ledger
        </CardTitle>
        <CardDescription>Funding received, opening fund, transfers and releases.</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="py-6 text-center text-sm text-muted-foreground">Loading…</div>
        ) : rows.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted-foreground">No activity yet.</div>
        ) : (
          <>
            {/* Mobile: stacked cards */}
            <div className="space-y-2 md:hidden">
              {pg.slice.map((r) => (
                <div key={r.id} className="rounded-xl border border-border/60 bg-card p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
                      {prettyType(r.type)}
                    </span>
                    <span className={cn("font-bold tabular-nums", Number(r.amount) >= 0 ? "text-buy" : "text-sell")}>
                      {signed(r.amount)}
                    </span>
                  </div>
                  <div className="mt-1 truncate text-xs text-muted-foreground">{r.narration || "—"}</div>
                  <div className="mt-0.5 text-[10px] text-muted-foreground">{fmtDateTime(r.created_at)}</div>
                </div>
              ))}
            </div>
            {/* Desktop: table */}
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">Type</th>
                    <th className="py-2 pr-3 font-medium">Narration</th>
                    <th className="py-2 pr-3 text-right font-medium">Amount</th>
                    <th className="py-2 text-right font-medium">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {pg.slice.map((r) => (
                    <tr key={r.id} className="border-b border-border/50 last:border-0">
                      <td className="py-2 pr-3">
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
                          {prettyType(r.type)}
                        </span>
                      </td>
                      <td className="max-w-[320px] truncate py-2 pr-3 text-muted-foreground">{r.narration || "—"}</td>
                      <td className={cn("py-2 pr-3 text-right font-bold tabular-nums", Number(r.amount) >= 0 ? "text-buy" : "text-sell")}>
                        {signed(r.amount)}
                      </td>
                      <td className="py-2 text-right text-xs text-muted-foreground">{fmtDateTime(r.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager {...pg} />
          </>
        )}
      </CardContent>
    </Card>
  );
}

/* ── helpers ────────────────────────────────────────────────────── */
function signed(v: number | string) {
  const n = Number(v);
  const s = formatINR(Math.abs(n));
  return n < 0 ? `- ${s}` : `+ ${s}`;
}

function prettyType(t?: string) {
  if (!t) return "—";
  return String(t).replace(/_/g, " ");
}

function fmtDateTime(x?: string) {
  if (!x) return "—";
  const d = new Date(x);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function fmtRange(a?: string, b?: string) {
  if (!a) return "—";
  const d = (x: string) => new Date(x).toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
  return b ? `${d(a)} – ${d(b)}` : d(a);
}

function StatusPill({ status }: { status: string }) {
  const cls = STATUS_TONE[String(status).toUpperCase()] || "bg-muted text-muted-foreground";
  return <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide", cls)}>{status}</span>;
}

function BalanceCard({
  icon, label, value, hint, accent, warn, danger, action, footer,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint: string;
  accent?: boolean;
  warn?: boolean;
  danger?: boolean;
  action?: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <Card className={cn("overflow-hidden", accent && "border-primary/30", warn && "border-amber-500/40", danger && "border-sell/40")}>
      <CardContent className="relative p-5">
        <span
          aria-hidden
          className={cn(
            "pointer-events-none absolute -right-8 -top-8 size-28 rounded-full blur-2xl",
            accent ? "bg-primary/10" : warn ? "bg-amber-500/10" : danger ? "bg-sell/10" : "bg-muted",
          )}
        />
        <div className="flex items-center gap-2">
          <span className={cn(
            "grid size-9 place-items-center rounded-lg",
            accent ? "bg-primary/10 text-primary"
              : warn ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
              : danger ? "bg-sell/15 text-sell"
              : "bg-muted text-muted-foreground",
          )}>
            {icon}
          </span>
          <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
        </div>
        <div className={cn("mt-3 text-2xl font-bold tabular-nums sm:text-3xl", accent && "text-primary", danger && "text-sell")}>{value}</div>
        <div className="mt-1 text-xs text-muted-foreground">{hint}</div>
        {action}
        {footer}
      </CardContent>
    </Card>
  );
}
