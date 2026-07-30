"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Coins, ArrowLeft } from "lucide-react";

import { AdminBookAPI } from "@/lib/api";
import { formatINR, signedINR } from "@/lib/utils";
import { useAdminAuthStore } from "@/stores/authStore";
import { PageHeader } from "@/components/common/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// Colour a signed money string green (≥0) / red (<0).
function Money({ v, bold }: { v: string | number; bold?: boolean }) {
  const n = Number(v) || 0;
  return (
    <span
      className={`tabular-nums ${bold ? "font-bold" : ""} ${
        n < 0 ? "text-red-500" : "text-emerald-500"
      }`}
    >
      {signedINR(v)}
    </span>
  );
}

export default function SaEarningsPage() {
  const admin = useAdminAuthStore((s) => s.admin);
  const [view, setView] = useState<"drill" | "txns">("drill");
  const [sel, setSel] = useState<
    | { level: "admins" }
    | { level: "users"; adminId: string; adminName: string }
    | { level: "trades"; adminId: string; adminName: string; userId: string; userName: string }
  >({ level: "admins" });

  const perAdmin = useQuery({
    queryKey: ["sa-earnings", "admins"],
    queryFn: () => AdminBookAPI.report(),
    enabled: admin?.role === "SUPER_ADMIN",
  });
  const perUser = useQuery({
    queryKey: ["sa-earnings", "users", sel.level === "users" || sel.level === "trades" ? (sel as any).adminId : null],
    queryFn: () => AdminBookAPI.users((sel as any).adminId),
    enabled: sel.level === "users",
  });
  const perTrade = useQuery({
    queryKey: [
      "sa-earnings", "trades",
      sel.level === "trades" ? sel.adminId : null,
      sel.level === "trades" ? sel.userId : null,
    ],
    queryFn: () => AdminBookAPI.trades((sel as any).adminId, (sel as any).userId),
    enabled: sel.level === "trades",
  });
  const txns = useQuery({
    queryKey: ["sa-earnings", "txns"],
    queryFn: () => AdminBookAPI.transactions({ limit: 300 }),
    enabled: admin?.role === "SUPER_ADMIN" && view === "txns",
    refetchInterval: view === "txns" ? 5000 : false,
  });

  if (admin?.role !== "SUPER_ADMIN") {
    return (
      <div className="rounded-md border border-border bg-card p-6 text-sm text-muted-foreground">
        Only the super admin can view SA earnings.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="SA Earnings"
        description="Per-trade PnL share + brokerage the super-admin earned from each admin's book. Drill: admin → user → trade."
      />

      {/* View toggle: drill-down vs flat transaction feed */}
      <div className="inline-flex rounded-lg border border-border p-0.5 text-sm">
        <button
          className={`rounded-md px-3 py-1.5 font-medium ${view === "drill" ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground"}`}
          onClick={() => setView("drill")}
        >
          By admin
        </button>
        <button
          className={`rounded-md px-3 py-1.5 font-medium ${view === "txns" ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground"}`}
          onClick={() => setView("txns")}
        >
          All transactions
        </button>
      </div>

      {/* ── Flat transaction feed — every per-trade SA earning, newest first ── */}
      {view === "txns" && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2">
              <Coins className="size-4 text-primary" /> SA incoming — per trade
            </CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            {txns.isLoading && <div className="py-4 text-sm text-muted-foreground">Loading…</div>}
            {!txns.isLoading && (txns.data || []).length === 0 && (
              <div className="py-4 text-sm text-muted-foreground">
                No entries yet. Turn ON “Per-trade admin-book” in Admin Management; every closing trade then lands here.
              </div>
            )}
            {(txns.data || []).length > 0 && (
              <table className="w-full min-w-[900px] text-sm">
                <thead className="text-left text-xs uppercase text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2">When</th>
                    <th className="py-2">Admin</th>
                    <th className="py-2">User</th>
                    <th className="py-2">Symbol</th>
                    <th className="py-2 text-right">House PnL</th>
                    <th className="py-2 text-right">SA PnL share</th>
                    <th className="py-2 text-right">SA Brokerage</th>
                    <th className="py-2 text-right">SA net</th>
                  </tr>
                </thead>
                <tbody>
                  {(txns.data || []).map((r: any) => (
                    <tr key={r.trade_id} className="border-b border-border/60">
                      <td className="py-2 text-[11px] text-muted-foreground">
                        {r.booked_at ? new Date(r.booked_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) : "—"}
                      </td>
                      <td className="py-2">
                        <div className="font-medium">{r.admin_name || r.admin_code || "—"}</div>
                        <div className="text-[11px] text-muted-foreground">{r.pnl_pct}% / {r.bkg_pct}%</div>
                      </td>
                      <td className="py-2">
                        <div className="font-medium">{r.user_name || r.user_code || "—"}</div>
                        {r.user_name && <div className="text-[11px] text-muted-foreground">{r.user_code}</div>}
                      </td>
                      <td className="py-2">{r.symbol || r.segment}</td>
                      <td className="py-2 text-right"><Money v={r.house_pnl} /></td>
                      <td className="py-2 text-right"><Money v={r.sa_pnl_share} /></td>
                      <td className="py-2 text-right"><Money v={r.sa_bkg_share} /></td>
                      <td className="py-2 text-right"><Money v={r.sa_net} bold /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      )}

      {/* Breadcrumb (drill view only) */}
      {view === "drill" && (
      <>
      <div className="flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
        <button className="hover:text-foreground" onClick={() => setSel({ level: "admins" })}>
          All admins
        </button>
        {(sel.level === "users" || sel.level === "trades") && (
          <>
            <ChevronRight className="size-3.5" />
            <button
              className="hover:text-foreground"
              onClick={() => setSel({ level: "users", adminId: (sel as any).adminId, adminName: (sel as any).adminName })}
            >
              {(sel as any).adminName}
            </button>
          </>
        )}
        {sel.level === "trades" && (
          <>
            <ChevronRight className="size-3.5" />
            <span className="text-foreground">{sel.userName}</span>
          </>
        )}
      </div>

      {/* ── Level 1: per admin ── */}
      {sel.level === "admins" && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2">
              <Coins className="size-4 text-primary" /> Earnings by admin
            </CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            {perAdmin.isLoading && <div className="py-4 text-sm text-muted-foreground">Loading…</div>}
            {!perAdmin.isLoading && (perAdmin.data || []).length === 0 && (
              <div className="py-4 text-sm text-muted-foreground">
                No earnings yet. (Turn ON “Per-trade admin-book” in Admin Management and let trades close.)
              </div>
            )}
            {(perAdmin.data || []).length > 0 && (
              <table className="w-full min-w-[720px] text-sm">
                <thead className="text-left text-xs uppercase text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2">Admin</th>
                    <th className="py-2 text-right">PnL share</th>
                    <th className="py-2 text-right">Brokerage share</th>
                    <th className="py-2 text-right">SA net</th>
                    <th className="py-2 text-right">Users</th>
                    <th className="py-2 text-right">Trades</th>
                    <th className="py-2" />
                  </tr>
                </thead>
                <tbody>
                  {(perAdmin.data || []).map((r: any) => (
                    <tr
                      key={r.admin_id}
                      className="cursor-pointer border-b border-border/60 hover:bg-muted/40"
                      onClick={() =>
                        setSel({ level: "users", adminId: r.admin_id, adminName: r.admin_name || r.admin_code || r.admin_id })
                      }
                    >
                      <td className="py-2">
                        <div className="font-medium">{r.admin_name || "—"}</div>
                        <div className="text-[11px] text-muted-foreground">{r.admin_code}</div>
                      </td>
                      <td className="py-2 text-right"><Money v={r.sa_pnl_share} /></td>
                      <td className="py-2 text-right"><Money v={r.sa_bkg_share} /></td>
                      <td className="py-2 text-right"><Money v={r.sa_net} bold /></td>
                      <td className="py-2 text-right tabular-nums">{r.user_count}</td>
                      <td className="py-2 text-right tabular-nums">{r.trades}</td>
                      <td className="py-2 text-right"><ChevronRight className="size-4 text-muted-foreground" /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      )}

      {/* ── Level 2: per user (one admin) ── */}
      {sel.level === "users" && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <button onClick={() => setSel({ level: "admins" })}>
                <ArrowLeft className="size-4" />
              </button>
              {sel.adminName} — earnings by user
            </CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            {perUser.isLoading && <div className="py-4 text-sm text-muted-foreground">Loading…</div>}
            {!perUser.isLoading && (perUser.data || []).length === 0 && (
              <div className="py-4 text-sm text-muted-foreground">No entries for this admin.</div>
            )}
            {(perUser.data || []).length > 0 && (
              <table className="w-full min-w-[680px] text-sm">
                <thead className="text-left text-xs uppercase text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2">User</th>
                    <th className="py-2 text-right">PnL share</th>
                    <th className="py-2 text-right">Brokerage share</th>
                    <th className="py-2 text-right">SA net</th>
                    <th className="py-2 text-right">Trades</th>
                    <th className="py-2" />
                  </tr>
                </thead>
                <tbody>
                  {(perUser.data || []).map((r: any) => (
                    <tr
                      key={r.user_id}
                      className="cursor-pointer border-b border-border/60 hover:bg-muted/40"
                      onClick={() =>
                        setSel({
                          level: "trades", adminId: sel.adminId, adminName: sel.adminName,
                          userId: r.user_id, userName: r.user_name || r.user_code || r.user_id,
                        })
                      }
                    >
                      <td className="py-2">
                        <div className="font-medium">{r.user_name || "—"}</div>
                        <div className="text-[11px] text-muted-foreground">{r.user_code}</div>
                      </td>
                      <td className="py-2 text-right"><Money v={r.sa_pnl_share} /></td>
                      <td className="py-2 text-right"><Money v={r.sa_bkg_share} /></td>
                      <td className="py-2 text-right"><Money v={r.sa_net} bold /></td>
                      <td className="py-2 text-right tabular-nums">{r.trades}</td>
                      <td className="py-2 text-right"><ChevronRight className="size-4 text-muted-foreground" /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      )}

      {/* ── Level 3: per trade (one user) ── */}
      {sel.level === "trades" && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <button onClick={() => setSel({ level: "users", adminId: sel.adminId, adminName: sel.adminName })}>
                <ArrowLeft className="size-4" />
              </button>
              {sel.userName} — per-trade
            </CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            {perTrade.isLoading && <div className="py-4 text-sm text-muted-foreground">Loading…</div>}
            {!perTrade.isLoading && (perTrade.data || []).length === 0 && (
              <div className="py-4 text-sm text-muted-foreground">No trades for this user.</div>
            )}
            {(perTrade.data || []).length > 0 && (
              <table className="w-full min-w-[820px] text-sm">
                <thead className="text-left text-xs uppercase text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2">Symbol</th>
                    <th className="py-2 text-right">House PnL</th>
                    <th className="py-2 text-right">Brokerage</th>
                    <th className="py-2 text-right">SA PnL {""}%</th>
                    <th className="py-2 text-right">SA Brok</th>
                    <th className="py-2 text-right">SA net</th>
                    <th className="py-2 text-right">When</th>
                  </tr>
                </thead>
                <tbody>
                  {(perTrade.data || []).map((r: any) => (
                    <tr key={r.trade_id} className="border-b border-border/60">
                      <td className="py-2">
                        <div className="font-medium">{r.symbol || r.segment}</div>
                        <div className="text-[11px] text-muted-foreground">
                          {r.pnl_pct}% / {r.bkg_pct}%
                        </div>
                      </td>
                      <td className="py-2 text-right"><Money v={r.house_pnl} /></td>
                      <td className="py-2 text-right tabular-nums">{formatINR(r.brokerage)}</td>
                      <td className="py-2 text-right"><Money v={r.sa_pnl_share} /></td>
                      <td className="py-2 text-right"><Money v={r.sa_bkg_share} /></td>
                      <td className="py-2 text-right"><Money v={r.sa_net} bold /></td>
                      <td className="py-2 text-right text-[11px] text-muted-foreground">
                        {r.booked_at ? new Date(r.booked_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      )}
      </>
      )}
    </div>
  );
}
