"use client";

/**
 * Delivery & Pledge — NSE/BSE equity delivery orders, the shares pledged
 * against them, and each user's pledge against their cash.
 *
 * The rules live in backend/app/services/pledge_service.py: a delivery buy
 * is paid in full, its shares give `haircut` % as margin usable ONLY for
 * NSE/BSE F&O, and stop-out is measured against cash alone.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Landmark, Save } from "lucide-react";
import { SettingsAPI, TradingAPI } from "@/lib/api";
import { PageHeader } from "@/components/common/PageHeader";
import { DataTable, type Column } from "@/components/common/DataTable";
import { AdminBadge, AdminFilter } from "@/components/admin/AdminScope";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAdminAuthStore } from "@/stores/authStore";
import { cn, formatINR, pnlColor } from "@/lib/utils";

type Tab = "orders" | "holdings" | "summary";

const TABS: { id: Tab; label: string }[] = [
  { id: "orders", label: "Delivery Orders" },
  { id: "holdings", label: "Pledged Holdings" },
  { id: "summary", label: "Pledge Summary" },
];

const KEY_ENABLED = "delivery_pledge.enabled";
const KEY_HAIRCUT = "delivery_pledge.haircut_pct";
const KEY_USERS = "delivery_pledge.user_codes";

/** Backend timestamps are UTC; show them in IST. */
function fmtTime(v?: string | null) {
  if (!v) return "—";
  const s = /[zZ]|[+-]\d\d:?\d\d$/.test(v) ? v : `${v}Z`;
  const d = new Date(s);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function UserCell({ r }: { r: any }) {
  return (
    <div className="flex flex-col items-start gap-0.5 leading-tight">
      <span className="font-medium">{r.user_name || "—"}</span>
      <span className="text-[11px] text-muted-foreground">{r.user_code || r.user_id?.slice(-6)}</span>
      <AdminBadge id={r.assigned_admin_id} name={r.assigned_admin_name} />
    </div>
  );
}

export default function DeliveryPledgePage() {
  const admin = useAdminAuthStore((s) => s.admin);
  const isSuper = String(admin?.role ?? "").toUpperCase() === "SUPER_ADMIN";
  const [tab, setTab] = useState<Tab>("orders");
  const [adminId, setAdminId] = useState("");
  const [side, setSide] = useState("");
  const params = useMemo(() => ({ admin_id: adminId || undefined }), [adminId]);

  const orders = useQuery({
    queryKey: ["admin", "pledge", "orders", params, side],
    queryFn: () => TradingAPI.pledgeOrders({ ...params, side: side || undefined }),
    enabled: tab === "orders",
    refetchInterval: 10_000,
  });
  const holdings = useQuery({
    queryKey: ["admin", "pledge", "holdings", params],
    queryFn: () => TradingAPI.pledgeHoldings(params),
    enabled: tab === "holdings",
    refetchInterval: 10_000,
  });
  const summary = useQuery({
    queryKey: ["admin", "pledge", "summary", params],
    queryFn: () => TradingAPI.pledgeSummary(params),
    enabled: tab === "summary",
    refetchInterval: 10_000,
  });

  const orderCols: Column<any>[] = [
    { key: "user", header: "User", render: (r) => <UserCell r={r} /> },
    { key: "symbol", header: "Symbol" },
    { key: "exchange", header: "Exch" },
    {
      key: "action",
      header: "Side",
      render: (r) => (
        <span className={cn("font-semibold", r.action === "BUY" ? "text-emerald-500" : "text-red-500")}>
          {r.action}
        </span>
      ),
    },
    { key: "quantity", header: "Qty", align: "right" },
    { key: "price", header: "Price", align: "right", render: (r) => formatINR(r.price) },
    { key: "value", header: "Value", align: "right", render: (r) => formatINR(r.value) },
    {
      key: "is_pledge",
      header: "Pledge",
      render: (r) =>
        r.is_pledge ? (
          <span className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber-500">
            PLEDGED
          </span>
        ) : (
          <span className="text-[11px] text-muted-foreground">—</span>
        ),
    },
    {
      key: "status",
      header: "Status",
      render: (r) => (
        <span title={r.rejection_reason || undefined} className="text-xs">
          {r.status}
        </span>
      ),
    },
    { key: "created_at", header: "Time", render: (r) => fmtTime(r.executed_at || r.created_at) },
  ];

  const holdingCols: Column<any>[] = [
    { key: "user", header: "User", render: (r) => <UserCell r={r} /> },
    { key: "symbol", header: "Symbol" },
    { key: "quantity", header: "Qty", align: "right" },
    { key: "avg_price", header: "Avg", align: "right", render: (r) => formatINR(r.avg_price) },
    { key: "ltp", header: "LTP", align: "right", render: (r) => formatINR(r.ltp) },
    { key: "invested", header: "Invested", align: "right", render: (r) => formatINR(r.invested) },
    { key: "current_value", header: "Current", align: "right", render: (r) => formatINR(r.current_value) },
    {
      key: "pledge_margin",
      header: "Pledge margin",
      align: "right",
      render: (r) => <span className="font-semibold text-amber-500">{formatINR(r.pledge_margin)}</span>,
    },
    { key: "pnl", header: "P&L", align: "right", render: (r) => <span className={pnlColor(r.pnl)}>{formatINR(r.pnl)}</span> },
  ];

  const summaryCols: Column<any>[] = [
    { key: "user", header: "User", render: (r) => <UserCell r={r} /> },
    { key: "cash", header: "Cash", align: "right", render: (r) => formatINR(r.cash) },
    { key: "holdings_value", header: "Holdings", align: "right", render: (r) => formatINR(r.holdings_value) },
    { key: "pledge_limit", header: "Pledge limit", align: "right", render: (r) => formatINR(r.pledge_limit) },
    { key: "pledge_used", header: "Used", align: "right", render: (r) => formatINR(r.pledge_used) },
    { key: "pledge_available", header: "Free", align: "right", render: (r) => formatINR(r.pledge_available) },
    {
      key: "pledge_deficit",
      header: "Gap",
      align: "right",
      render: (r) =>
        Number(r.pledge_deficit) > 0 ? (
          <span className="font-semibold text-red-500">{formatINR(r.pledge_deficit)}</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    { key: "fno_pnl", header: "F&O P&L", align: "right", render: (r) => <span className={pnlColor(r.fno_pnl)}>{formatINR(r.fno_pnl)}</span> },
    {
      key: "loss_pct",
      header: "Loss % of cash",
      align: "right",
      render: (r) => (
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-xs font-bold",
            r.loss_pct >= 80 ? "bg-red-500/15 text-red-500" : r.loss_pct >= 50 ? "bg-amber-500/15 text-amber-500" : "text-muted-foreground",
          )}
        >
          {Number(r.loss_pct).toFixed(1)}%
        </span>
      ),
    },
  ];

  const active = tab === "orders" ? orders : tab === "holdings" ? holdings : summary;
  const cols = tab === "orders" ? orderCols : tab === "holdings" ? holdingCols : summaryCols;
  const rows = (active.data as any[] | undefined) ?? undefined;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Delivery & Pledge"
        description="Equity delivery orders, shares pledged against them, and each user's pledge margin against cash."
      />

      {isSuper && <PledgeSettingsCard />}

      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg border border-border p-0.5">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                tab === t.id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        {tab === "orders" && (
          <select
            value={side}
            onChange={(e) => setSide(e.target.value)}
            className="h-9 rounded-md border border-input bg-background px-2 text-sm"
          >
            <option value="">BUY + SELL</option>
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        )}
        <AdminFilter value={adminId} onChange={setAdminId} className="ml-auto" />
      </div>

      <DataTable
        columns={cols}
        rows={rows}
        keyExtractor={(r: any) => r.id || r.user_id}
        loading={active.isFetching && !rows}
      />
    </div>
  );
}

/** Super-admin switch. Off by default; a user-code list lets it go live for
 *  one demo account first. */
function PledgeSettingsCard() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["admin", "settings", "delivery_pledge"],
    queryFn: () => SettingsAPI.platformList("delivery_pledge"),
  });
  const [enabled, setEnabled] = useState(false);
  const [haircut, setHaircut] = useState("50");
  const [codes, setCodes] = useState("");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    if (!data || hydrated) return;
    const by: Record<string, any> = {};
    for (const row of data as any[]) by[row.setting_key ?? row.key] = row.setting_value ?? row.value;
    setEnabled(["true", "1", "on", "yes"].includes(String(by[KEY_ENABLED] ?? "").toLowerCase()) || by[KEY_ENABLED] === true);
    if (by[KEY_HAIRCUT] != null) setHaircut(String(by[KEY_HAIRCUT]));
    setCodes(String(by[KEY_USERS] ?? ""));
    setHydrated(true);
  }, [data, hydrated]);

  const pct = Number(haircut);
  const validPct = Number.isFinite(pct) && pct >= 0 && pct <= 100;

  const save = useMutation({
    mutationFn: async () => {
      await SettingsAPI.platformSet(KEY_ENABLED, enabled);
      await SettingsAPI.platformSet(KEY_HAIRCUT, pct);
      await SettingsAPI.platformSet(KEY_USERS, codes.trim());
    },
    onSuccess: () => {
      toast.success("Delivery pledge settings saved");
      qc.invalidateQueries({ queryKey: ["admin", "settings", "delivery_pledge"] });
    },
    onError: (e: any) => toast.error(e?.message || "Could not save"),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Landmark className="size-5 text-primary" />
          Delivery pledge
        </CardTitle>
        <CardDescription>
          A delivery (CNC) buy on NSE/BSE equity is paid in full and pledged. Pledged shares give the
          haircut % below as margin for NSE/BSE F&amp;O only — never for M2M loss. Stop-out is on cash.
          Positions opened before switching on are not affected.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 md:grid-cols-3">
          <label className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="size-4" />
            Enabled
          </label>
          <div className="space-y-1.5">
            <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Pledge margin (% of share value)
            </div>
            <Input type="number" min={0} max={100} value={haircut} onChange={(e) => setHaircut(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Only these users (optional)
            </div>
            <Input value={codes} onChange={(e) => setCodes(e.target.value)} placeholder="CL123, CL456 — blank = everyone" />
          </div>
        </div>
        <div className="rounded-md border border-border bg-muted/10 px-3 py-2 text-xs">
          Example: 2,00,000 in the NSE wallet, buy 1,50,000 of shares → cash 50,000, pledge{" "}
          {validPct ? formatINR((150000 * pct) / 100) : "—"}, F&amp;O margin{" "}
          {validPct ? formatINR(50000 + (150000 * pct) / 100) : "—"}.
        </div>
        <Button type="button" onClick={() => save.mutate()} loading={save.isPending} disabled={!validPct || save.isPending}>
          <Save className="size-4" />
          Save
        </Button>
      </CardContent>
    </Card>
  );
}
