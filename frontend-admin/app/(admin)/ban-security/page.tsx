"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Ban, Search, Trash2, ChevronDown, Check, Users } from "lucide-react";
import { BanSecurityAPI, InstrumentAdminAPI, ManagementAPI } from "@/lib/api";
import { PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// Segment filter tabs → the admin segment-row name the backend resolves
// (netting_segment). Mirrors the trading terminal's watchlist filters.
const SEG_TABS: { label: string; ns: string }[] = [
  { label: "All", ns: "" },
  { label: "NSE EQ", ns: "NSE_EQ" },
  { label: "NSE Fut", ns: "NSE_STK_FUT" },
  { label: "NSE Opt", ns: "NSE_STK_OPT" },
  { label: "Index Fut", ns: "NSE_IDX_FUT" },
  { label: "Index Opt", ns: "NSE_IDX_OPT" },
  { label: "BSE EQ", ns: "BSE_EQ" },
  { label: "BSE Fut", ns: "BSE_FUT" },
  { label: "BSE Opt", ns: "BSE_OPT" },
  { label: "MCX Fut", ns: "MCX_FUT" },
  { label: "MCX Opt", ns: "MCX_OPT" },
  { label: "Commodities", ns: "COMMODITIES" },
  { label: "Forex", ns: "FOREX" },
  { label: "Crypto", ns: "CRYPTO" },
  { label: "Crypto Opt", ns: "CRYPTO_OPT" },
  { label: "Indices", ns: "INDICES" },
  { label: "Stocks", ns: "STOCKS" },
];

export default function BanSecurityPage() {
  const [q, setQ] = useState("");
  const [seg, setSeg] = useState(""); // selected netting_segment ("" = all)
  // Selected admin ids — the ban applies to each selected admin's user pool.
  const [scopes, setScopes] = useState<Set<string>>(new Set<string>());
  const [adminsOpen, setAdminsOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const { data: bans, refetch } = useQuery<any[]>({
    queryKey: ["admin", "ban-security"],
    queryFn: () => BanSecurityAPI.list(),
  });

  const { data: search, isFetching } = useQuery({
    queryKey: ["admin", "ban-inst-search", q, seg],
    queryFn: () =>
      InstrumentAdminAPI.list({
        q: q.trim() || undefined,
        netting_segment: seg || undefined,
        page_size: 25,
      }),
    // Search once there's a query OR a segment picked (browse a segment).
    enabled: q.trim().length >= 2 || !!seg,
    staleTime: 4000,
  });

  const { data: admins } = useQuery({
    queryKey: ["admin", "ban-admins"],
    queryFn: () => ManagementAPI.listSubAdmins({ page_size: 200 }),
  });
  const adminList = useMemo(
    () => (admins?.items ?? []).filter((a: any) => (a.role ?? "ADMIN") === "ADMIN"),
    [admins],
  );
  const allAdmins = adminList.length > 0 && adminList.every((a: any) => scopes.has(a.id));

  function toggle(id: string) {
    setScopes((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }
  function toggleAllAdmins() {
    setScopes((prev) => {
      const next = new Set(prev);
      if (adminList.every((a: any) => next.has(a.id))) {
        adminList.forEach((a: any) => next.delete(a.id));
      } else {
        adminList.forEach((a: any) => next.add(a.id));
      }
      return next;
    });
  }

  async function ban(token: string, symbol: string) {
    const targets = [...scopes];
    if (targets.length === 0) {
      toast.error("Select at least one admin");
      setAdminsOpen(true);
      return;
    }
    setBusy(token);
    try {
      for (const s of targets) await BanSecurityAPI.ban({ token, admin_id: s });
      toast.success(`${symbol} banned for ${targets.length} admin pool(s)`);
      setQ("");
      refetch();
    } catch (e: any) {
      toast.error(e?.message ?? "Ban failed");
    } finally {
      setBusy(null);
    }
  }

  async function unban(id: string, symbol: string) {
    setBusy(id);
    try {
      await BanSecurityAPI.unban(id);
      toast.success(`${symbol} unbanned`);
      refetch();
    } catch (e: any) {
      toast.error(e?.message ?? "Unban failed");
    } finally {
      setBusy(null);
    }
  }

  const selectedCount = scopes.size;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader title="Ban Security" description="Block a stock — close-only + frozen P&L for open positions" />

      <div className="rounded-xl border border-border bg-card p-4 space-y-4">
        {/* ── Admin selector (collapsed by default) ── */}
        <div>
          <label className="text-xs font-medium text-muted-foreground">Ban for (admin pools)</label>
          <button
            type="button"
            onClick={() => setAdminsOpen((v) => !v)}
            className="mt-1 flex w-full items-center justify-between rounded-lg border border-border bg-background px-3 py-2.5 text-sm hover:bg-muted/50 transition-colors"
          >
            <span className="flex items-center gap-2">
              <Users className="h-4 w-4 text-muted-foreground" />
              {selectedCount === 0
                ? "Select admins…"
                : allAdmins
                  ? `All admins (${selectedCount})`
                  : `${selectedCount} admin${selectedCount > 1 ? "s" : ""} selected`}
            </span>
            <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", adminsOpen && "rotate-180")} />
          </button>

          {adminsOpen && (
            <div className="mt-2 max-h-56 space-y-1 overflow-y-auto rounded-lg border border-border bg-background p-2">
              <button
                type="button"
                onClick={toggleAllAdmins}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium hover:bg-muted/60"
              >
                <span className={cn("flex h-4 w-4 items-center justify-center rounded border", allAdmins ? "border-primary bg-primary text-primary-foreground" : "border-border")}>
                  {allAdmins && <Check className="h-3 w-3" />}
                </span>
                Select all admins
              </button>
              <div className="my-1 border-t border-border" />
              {adminList.map((a: any) => {
                const on = scopes.has(a.id);
                return (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => toggle(a.id)}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted/60"
                  >
                    <span className={cn("flex h-4 w-4 shrink-0 items-center justify-center rounded border", on ? "border-primary bg-primary text-primary-foreground" : "border-border")}>
                      {on && <Check className="h-3 w-3" />}
                    </span>
                    <span className="truncate">{a.full_name || a.user_code}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* ── Stock search + segment tabs ── */}
        <div>
          <label className="text-xs font-medium text-muted-foreground">Search stock to ban</label>
          <div className="mt-1 flex items-center gap-2 rounded-lg border border-border bg-background px-3">
            <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="RELIANCE, NIFTY, BTCUSD…"
              className="w-full bg-transparent py-2.5 text-sm outline-none"
            />
          </div>

          {/* Segment filter tabs — horizontal scroll on small screens */}
          <div className="mt-2 flex gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {SEG_TABS.map((t) => (
              <button
                key={t.ns || "all"}
                type="button"
                onClick={() => setSeg(t.ns)}
                className={cn(
                  "shrink-0 rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                  seg === t.ns
                    ? "border-primary bg-primary/15 text-primary"
                    : "border-border text-muted-foreground hover:bg-muted/50",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>

          {(q.trim().length >= 2 || !!seg) && (
            <div className="mt-2 max-h-72 divide-y divide-border overflow-y-auto rounded-lg border border-border">
              {isFetching && (search?.items ?? []).length === 0 && (
                <div className="px-3 py-3 text-sm text-muted-foreground">Searching…</div>
              )}
              {!isFetching && (search?.items ?? []).length === 0 && (
                <div className="px-3 py-3 text-sm text-muted-foreground">No instruments found.</div>
              )}
              {(search?.items ?? []).map((i: any) => (
                <div key={i.token} className="flex items-center justify-between gap-2 px-3 py-2.5">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{i.symbol}</div>
                    <div className="truncate text-xs text-muted-foreground">{i.segment}</div>
                  </div>
                  <Button
                    size="sm"
                    variant="destructive"
                    className="shrink-0"
                    disabled={busy === i.token}
                    onClick={() => ban(i.token, i.symbol)}
                  >
                    <Ban className="mr-1 h-3.5 w-3.5" /> Ban
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Banned list ── */}
      <div className="rounded-xl border border-border bg-card">
        <div className="border-b border-border px-4 py-3 text-sm font-semibold">Banned securities</div>
        <div className="divide-y divide-border">
          {(bans ?? []).length === 0 && (
            <div className="px-4 py-6 text-center text-sm text-muted-foreground">Nothing banned.</div>
          )}
          {(bans ?? []).map((b: any) => (
            <div key={b.id} className="flex items-center justify-between gap-2 px-4 py-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{b.symbol}</div>
                <div className="truncate text-xs text-muted-foreground">
                  {b.scope_label} · freeze @ {b.freeze_price}
                </div>
              </div>
              <Button
                size="sm"
                variant="outline"
                className="shrink-0"
                disabled={busy === b.id}
                onClick={() => unban(b.id, b.symbol)}
              >
                <Trash2 className="mr-1 h-3.5 w-3.5" /> Unban
              </Button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
