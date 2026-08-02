"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Ban, Search, Trash2 } from "lucide-react";
import { BanSecurityAPI, InstrumentAdminAPI, ManagementAPI } from "@/lib/api";
import { PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";

export default function BanSecurityPage() {
  const [q, setQ] = useState("");
  const [scope, setScope] = useState<string>("GLOBAL"); // "GLOBAL" or admin id
  const [busy, setBusy] = useState<string | null>(null);

  const { data: bans, refetch } = useQuery<any[]>({
    queryKey: ["admin", "ban-security"],
    queryFn: () => BanSecurityAPI.list(),
  });

  const { data: search } = useQuery({
    queryKey: ["admin", "ban-inst-search", q],
    queryFn: () => InstrumentAdminAPI.list({ q, page_size: 15 }),
    enabled: q.trim().length >= 2,
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

  async function ban(token: string, symbol: string) {
    setBusy(token);
    try {
      await BanSecurityAPI.ban({ token, admin_id: scope === "GLOBAL" ? null : scope });
      toast.success(`${symbol} banned`);
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

  return (
    <div className="space-y-6">
      <PageHeader title="Ban Security" subtitle="Block a stock — close-only + frozen P&L for open positions" />

      <div className="rounded-lg border border-border bg-card p-4 space-y-4">
        <div>
          <label className="text-xs font-medium text-muted-foreground">Ban for</label>
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
          >
            <option value="GLOBAL">All users (global)</option>
            {adminList.map((a: any) => (
              <option key={a.id} value={a.id}>
                {(a.full_name || a.user_code) + " — this admin's users"}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-xs font-medium text-muted-foreground">Search stock to ban</label>
          <div className="mt-1 flex items-center gap-2 rounded-md border border-border bg-background px-3">
            <Search className="h-4 w-4 text-muted-foreground" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="RELIANCE, NIFTY, BTCUSD…"
              className="w-full bg-transparent py-2 text-sm outline-none"
            />
          </div>
          {q.trim().length >= 2 && (
            <div className="mt-2 max-h-64 divide-y divide-border overflow-y-auto rounded-md border border-border">
              {(search?.items ?? []).length === 0 && (
                <div className="px-3 py-2 text-sm text-muted-foreground">No instruments</div>
              )}
              {(search?.items ?? []).map((i: any) => (
                <div key={i.token} className="flex items-center justify-between px-3 py-2">
                  <div>
                    <div className="text-sm font-medium">{i.symbol}</div>
                    <div className="text-xs text-muted-foreground">{i.segment}</div>
                  </div>
                  <Button
                    size="sm"
                    variant="destructive"
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

      <div className="rounded-lg border border-border bg-card">
        <div className="border-b border-border px-4 py-3 text-sm font-semibold">Banned securities</div>
        <div className="divide-y divide-border">
          {(bans ?? []).length === 0 && (
            <div className="px-4 py-6 text-center text-sm text-muted-foreground">Nothing banned.</div>
          )}
          {(bans ?? []).map((b: any) => (
            <div key={b.id} className="flex items-center justify-between px-4 py-3">
              <div>
                <div className="text-sm font-medium">{b.symbol}</div>
                <div className="text-xs text-muted-foreground">
                  {b.scope_label} · freeze @ {b.freeze_price}
                </div>
              </div>
              <Button
                size="sm"
                variant="outline"
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
