"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Users, GitBranch } from "lucide-react";
import { AdminDemoAPI } from "@/lib/api";
import { useAdminAuthStore } from "@/stores/authStore";
import { PageHeader } from "@/components/common/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Kind = "users" | "brokers";
type Status = "pending" | "converted";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "—";
  }
}

export default function DemoAccountsPage() {
  const [kind, setKind] = useState<Kind>("users");
  const [status, setStatus] = useState<Status>("pending");

  const { data, isLoading } = useQuery({
    queryKey: ["admin", "demo", kind, status],
    queryFn: () => AdminDemoAPI.list({ kind, status, page: 1, page_size: 100 }),
    refetchInterval: 30_000,
  });

  const counts = data?.counts ?? {};
  const items: any[] = data?.items ?? [];

  const kindTabs: { id: Kind; label: string; icon: any }[] = [
    { id: "users", label: "Demo Users", icon: Users },
    { id: "brokers", label: "Demo Brokers", icon: GitBranch },
  ];
  const statusTabs: { id: Status; label: string; countKey: string }[] = [
    { id: "pending", label: "Not converted", countKey: `${kind}_pending` },
    { id: "converted", label: "Converted", countKey: `${kind}_converted` },
  ];
  // Copy only — the backend already scopes a broker's rows to their own
  // signups and 403s the ADMIN tier outright.
  const isBroker = useAdminAuthStore((s) => s.admin?.role) === "BROKER";

  return (
    <div className="space-y-5">
      <PageHeader
        title="Demo"
        description={
          isBroker
            ? "Demo signups that chose you — and which of them converted to a real account."
            : "Who signed up on demo and who converted to a real account."
        }
      />

      {/* Kind toggle: Users / Brokers */}
      <div className="flex flex-wrap gap-2">
        {kindTabs.map((t) => {
          const Icon = t.icon;
          const active = kind === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setKind(t.id)}
              className={cn(
                "flex items-center gap-2 rounded-lg border px-3.5 py-2 text-sm font-semibold transition-colors",
                active
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border bg-card text-muted-foreground hover:bg-muted/40",
              )}
            >
              <Icon className="size-4" /> {t.label}
            </button>
          );
        })}
      </div>

      {/* Status tabs with count badges */}
      <div className="flex flex-wrap gap-2">
        {statusTabs.map((t) => {
          const active = status === t.id;
          const n = counts[t.countKey] ?? 0;
          return (
            <button
              key={t.id}
              onClick={() => setStatus(t.id)}
              className={cn(
                "flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors",
                active
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-muted-foreground hover:bg-muted/40",
              )}
            >
              {t.label}
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.5 text-[10px] font-bold tabular-nums",
                  active ? "bg-primary-foreground/20" : "bg-muted",
                )}
              >
                {n}
              </span>
            </button>
          );
        })}
      </div>

      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                <th className="px-4 py-3">Code</th>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Mobile</th>
                <th className="px-4 py-3 text-right">
                  {status === "converted" ? "Converted at" : "Signed up"}
                </th>
                {kind === "brokers" && status === "pending" && (
                  <th className="px-4 py-3 text-right">Virtual float</th>
                )}
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-muted-foreground">
                    Loading…
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-muted-foreground">
                    No {status === "converted" ? "converted" : "demo"} {kind} yet.
                  </td>
                </tr>
              ) : (
                items.map((u) => (
                  <tr key={u.id} className="border-b border-border/60 last:border-0">
                    <td className="px-4 py-3 font-mono text-xs">{u.user_code}</td>
                    <td className="px-4 py-3 font-medium">{u.full_name}</td>
                    <td className="px-4 py-3 text-muted-foreground">{u.email}</td>
                    <td className="px-4 py-3 tabular-nums text-muted-foreground">{u.mobile}</td>
                    <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                      {status === "converted" ? fmtDate(u.converted_at) : fmtDate(u.created_at)}
                    </td>
                    {kind === "brokers" && status === "pending" && (
                      <td className="px-4 py-3 text-right tabular-nums">🪙{u.wallet_balance}</td>
                    )}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
