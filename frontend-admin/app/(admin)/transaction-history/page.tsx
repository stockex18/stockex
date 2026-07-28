"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Layers, Wallet as WalletIcon, Gamepad2 } from "lucide-react";
import { TransactionHistoryAPI } from "@/lib/api";
import { PageHeader } from "@/components/common/PageHeader";

function inr(n: number) {
  const v = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `🪙${v}`;
}

function RecTile({ label, value, pos, accent }: { label: string; value?: number; pos?: boolean; accent?: boolean }) {
  return (
    <div className={`rounded-lg border p-2.5 ${accent ? "border-primary/40 bg-primary/5" : "border-border/60 bg-background"}`}>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`mt-0.5 text-sm font-bold tabular-nums ${accent ? "text-primary" : pos ? "text-emerald-500" : "text-foreground"}`}>
        {inr(Number(value ?? 0))}
      </div>
    </div>
  );
}

export default function TransactionHistoryPage() {
  const [source, setSource] = useState("all");
  const [adminId, setAdminId] = useState("");
  const [showRecon, setShowRecon] = useState(true);

  const { data, isFetching } = useQuery({
    queryKey: ["admin", "transaction-history", source, adminId],
    queryFn: () => TransactionHistoryAPI.list({ source, admin_id: adminId || undefined, limit: 500 }),
  });

  const rows: any[] = data?.rows ?? [];
  const games = data?.games ?? [];
  const admins = data?.admins ?? [];
  const isSuper = !!data?.is_super;

  const recon = useQuery({
    queryKey: ["admin", "transaction-history", "reconciliation"],
    queryFn: () => TransactionHistoryAPI.reconciliation(),
    enabled: isSuper,
    refetchInterval: 15000,
  });

  // Source tabs: All · Trading · every game.
  const tabs = useMemo(
    () => [
      { key: "all", label: "All", icon: Layers },
      { key: "trading", label: "Trading", icon: WalletIcon },
      ...games.map((g) => ({ key: g.key, label: g.label, icon: Gamepad2 })),
    ],
    [games],
  );

  return (
    <div className="space-y-4">
      <PageHeader title="Transaction History" description={`${rows.length} entries`} />

      {/* ── SA Ledger reconciliation — per admin: given out vs came back ── */}
      {isSuper && (
        <div className="rounded-lg border border-border bg-card">
          <button
            type="button"
            onClick={() => setShowRecon((s) => !s)}
            className="flex w-full items-center justify-between px-4 py-3 text-left"
          >
            <span className="flex items-center gap-2 text-sm font-semibold">
              <WalletIcon className="size-4 text-primary" /> Ledger reconciliation (per admin)
            </span>
            <span className="text-xs text-muted-foreground">{showRecon ? "Hide ▲" : "Show ▼"}</span>
          </button>
          {showRecon && (() => {
            const t = recon.data?.totals ?? {};
            const rrows: any[] = recon.data?.rows ?? [];
            const allMatched = !!t.all_matched;
            return (
              <div className="space-y-3 border-t border-border px-4 py-3">
                {/* Match banner — does every admin's wallet reconcile? */}
                <div className={`flex items-center justify-between rounded-lg border px-3 py-2 text-sm font-semibold ${allMatched ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-600" : "border-red-500/40 bg-red-500/10 text-red-600"}`}>
                  <span>{allMatched ? "✓ All admin wallets reconcile exactly" : "✗ Mismatch — some wallets don't tie out"}</span>
                  <span className="text-xs font-normal">total delta {inr(Number(t.delta ?? 0))}</span>
                </div>

                {/* Grand-total strip */}
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <RecTile label="Funded to admins" value={t.funded} />
                  <RecTile label="To users / brokers" value={t.to_users} />
                  <RecTile label="Admins' wallets now" value={t.wallet_now} accent />
                  <RecTile label="SA income (to SA)" value={t.to_sa} pos accent />
                </div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  <RecTile label="SA main wallet" value={t.sa_main} />
                  <RecTile label="SA kuber pool" value={t.sa_kuber} />
                  <RecTile label="SA total now" value={t.sa_total_now} accent />
                </div>

                {/* Per-admin tie-out table: Funded − ToUsers + Trading − ToSA + Games + Other = Wallet */}
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[900px] text-sm">
                    <thead>
                      <tr className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                        <th className="py-2 pr-3">Admin</th>
                        <th className="py-2 pr-3 text-right">Funded in</th>
                        <th className="py-2 pr-3 text-right">− To users/brokers</th>
                        <th className="py-2 pr-3 text-right">+ Trading</th>
                        <th className="py-2 pr-3 text-right">− To SA</th>
                        <th className="py-2 pr-3 text-right">± Games/Other</th>
                        <th className="py-2 pr-3 text-right">= Wallet now</th>
                        <th className="py-2 text-right">Match</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rrows.map((r) => (
                        <tr key={r.admin_id} className="border-b border-border/50 last:border-0">
                          <td className="py-2 pr-3">
                            <div className="font-medium">{r.admin_name || r.admin_code}</div>
                            <div className="text-[11px] text-muted-foreground">{r.admin_code}</div>
                          </td>
                          <td className="py-2 pr-3 text-right tabular-nums">{inr(r.funded)}</td>
                          <td className="py-2 pr-3 text-right tabular-nums text-red-500">{inr(r.to_users)}</td>
                          <td className={`py-2 pr-3 text-right tabular-nums ${r.trading < 0 ? "text-red-500" : "text-emerald-500"}`}>{inr(r.trading)}</td>
                          <td className={`py-2 pr-3 text-right tabular-nums ${r.to_sa < 0 ? "text-emerald-500" : "text-red-500"}`}>{inr(r.to_sa)}</td>
                          <td className="py-2 pr-3 text-right tabular-nums text-muted-foreground">{inr((r.games || 0) + (r.other || 0))}</td>
                          <td className="py-2 pr-3 text-right font-bold tabular-nums">{inr(r.wallet_now)}</td>
                          <td className="py-2 text-right">
                            {r.matched
                              ? <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[11px] font-bold text-emerald-600">✓</span>
                              : <span className="rounded bg-red-500/15 px-1.5 py-0.5 text-[11px] font-bold text-red-600">Δ{inr(r.delta)}</span>}
                          </td>
                        </tr>
                      ))}
                      {rrows.length === 0 && (
                        <tr><td colSpan={8} className="py-4 text-center text-muted-foreground">Loading…</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
                <p className="text-[11px] text-muted-foreground">
                  Every admin wallet is fully explained: <b>Funded in − To users/brokers + Trading (admin-book)
                  − To SA + Games/Other = Wallet now</b>. A green ✓ means it ties out to the paisa (no leak).
                  “SA income (to SA)” = brokerage + PnL share that came back to you. “SA total now” = your
                  main + kuber — your live ledger balance.
                </p>
              </div>
            );
          })()}
        </div>
      )}

      {/* Filters */}
      <div className="space-y-2">
        <div className="flex flex-wrap gap-1.5">
          {tabs.map((t) => {
            const Icon = t.icon;
            const active = source === t.key;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setSource(t.key)}
                className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                  active
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground"
                }`}
              >
                <Icon className="size-3.5" />
                {t.label}
              </button>
            );
          })}
        </div>
        {isSuper && admins.length > 0 && (
          <select
            value={adminId}
            onChange={(e) => setAdminId(e.target.value)}
            className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-xs sm:w-64"
          >
            <option value="">All admins (whole platform)</option>
            {admins.map((a) => (
              <option key={a.id} value={a.id}>
                {a.label}
              </option>
            ))}
          </select>
        )}
      </div>

      {isFetching && !data ? (
        <div className="rounded-lg border border-border p-8 text-center text-xs text-muted-foreground">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="rounded-lg border border-border p-8 text-center text-xs text-muted-foreground">
          No transactions for this filter.
        </div>
      ) : (
        <>
          {/* Mobile: stacked cards */}
          <div className="space-y-2 md:hidden">
            {rows.map((r) => (
              <TxnCard key={r.id} r={r} />
            ))}
          </div>

          {/* Desktop: table */}
          <div className="hidden overflow-x-auto rounded-lg border border-border md:block">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-semibold">When</th>
                  <th className="px-3 py-2 text-left font-semibold">Source</th>
                  <th className="px-3 py-2 text-left font-semibold">Category</th>
                  <th className="px-3 py-2 text-left font-semibold">User</th>
                  <th className="px-3 py-2 text-left font-semibold">Admin</th>
                  <th className="px-3 py-2 text-left font-semibold">Detail</th>
                  <th className="px-3 py-2 text-right font-semibold">Amount</th>
                  <th className="px-3 py-2 text-right font-semibold">Balance</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-t border-border/60 hover:bg-muted/15">
                    <td className="whitespace-nowrap px-3 py-2 font-tabular text-xs text-muted-foreground">
                      {r.date ? new Date(r.date).toLocaleString() : "—"}
                    </td>
                    <td className="px-3 py-2">
                      <SourceBadge label={r.source_label} isTrading={r.source === "trading"} />
                    </td>
                    <td className="px-3 py-2 text-xs">{r.category}</td>
                    <td className="px-3 py-2">
                      <div className="flex flex-col leading-tight">
                        <span className="text-xs font-medium">{r.user_name || r.user_code}</span>
                        <span className="font-mono text-[10px] text-muted-foreground">{r.user_code}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">{r.admin_name}</td>
                    <td className="max-w-[280px] truncate px-3 py-2 text-xs text-muted-foreground" title={r.description}>
                      {r.description || "—"}
                    </td>
                    <td
                      className={`whitespace-nowrap px-3 py-2 text-right font-tabular font-semibold tabular-nums ${
                        r.amount < 0 ? "text-destructive" : "text-emerald-600 dark:text-emerald-400"
                      }`}
                    >
                      {r.amount < 0 ? "−" : "+"}
                      {inr(r.amount)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right font-tabular tabular-nums text-muted-foreground">
                      {inr(r.balance_after)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function SourceBadge({ label, isTrading }: { label: string; isTrading: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide ${
        isTrading
          ? "bg-sky-500/15 text-sky-600 dark:text-sky-300"
          : "bg-violet-500/15 text-violet-600 dark:text-violet-300"
      }`}
    >
      {isTrading ? <WalletIcon className="size-2.5" /> : <Gamepad2 className="size-2.5" />}
      {label}
    </span>
  );
}

function TxnCard({ r }: { r: any }) {
  return (
    <div className="rounded-xl border border-border/60 bg-card p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <SourceBadge label={r.source_label} isTrading={r.source === "trading"} />
          <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            {r.category}
          </span>
        </div>
        <span className="shrink-0 font-tabular text-[10px] text-muted-foreground">
          {r.date ? new Date(r.date).toLocaleString() : "—"}
        </span>
      </div>
      <div className="mt-2 flex items-center justify-between gap-2 text-xs">
        <div className="flex flex-col leading-tight">
          <span className="font-medium">{r.user_name || r.user_code}</span>
          <span className="font-mono text-[10px] text-muted-foreground">
            {r.user_code} · {r.admin_name}
          </span>
        </div>
        <div
          className={`font-tabular text-base font-semibold tabular-nums ${
            r.amount < 0 ? "text-destructive" : "text-emerald-600 dark:text-emerald-400"
          }`}
        >
          {r.amount < 0 ? "−" : "+"}
          {inr(r.amount)}
        </div>
      </div>
      {r.description ? <p className="mt-1.5 text-[11px] leading-snug text-muted-foreground">{r.description}</p> : null}
    </div>
  );
}
