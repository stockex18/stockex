"use client";

/**
 * Portfolio leverage cap — the aggregate limit, made visible.
 *
 * It bounds a WALLET's TOTAL open exposure at `balance × cap`, whatever
 * leverage each individual instrument allows. It exists because the per-order
 * funds check cannot see blended drift: a high-leverage leg locks little
 * margin for large notional, freeing room a low-leverage leg then spends, so
 * the book's combined leverage creeps past the intended maximum even though
 * every order passed its own check.
 *
 * Until now it lived only in the backend config as a hardcoded 33.33 for
 * NSE/BSE. It appeared nowhere in this panel, so an admin who had set 50×
 * per-instrument margin had no way to discover why orders were being refused
 * at 33.33× — two rules that contradict each other, with only one of them on
 * screen. That is what this card is for.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { SettingsAPI } from "@/lib/api";
import { useAdminAuthStore } from "@/stores/authStore";

const PREFIX = "portfolio.max_leverage.";

/** Only the INR-native wallets are enforceable today. Crypto and forex quote
 *  notional in USD against an INR balance, so a cap there would be comparing
 *  two currencies — they stay off until that is normalised. */
const WALLETS: { kind: string; label: string; hint: string }[] = [
  { kind: "NSE_BSE", label: "NSE / BSE", hint: "Equity, F&O, index" },
  { kind: "MCX", label: "MCX", hint: "Commodities" },
];

export function PortfolioCapCard() {
  const admin = useAdminAuthStore((st) => st.admin);
  const role = String(admin?.role || "");
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const isSuperAdmin = role === "SUPER_ADMIN";

  const { data: rows, isLoading } = useQuery({
    queryKey: ["platform-settings", "portfolio"],
    queryFn: () => SettingsAPI.platformList("portfolio"),
    enabled: isSuperAdmin,
    staleTime: 10_000,
  });

  const saved = (kind: string): string => {
    const row = (rows || []).find((r: any) => r?.key === PREFIX + kind);
    return row?.value == null ? "" : String(row.value);
  };

  const save = useMutation({
    mutationFn: ({ kind, value }: { kind: string; value: number }) =>
      SettingsAPI.platformSet(PREFIX + kind, value),
    onSuccess: (_d, v) => {
      toast.success(
        v.value === 0
          ? `${v.kind}: cap removed — no aggregate limit`
          : `${v.kind}: cap set to ${v.value}×`,
      );
      qc.invalidateQueries({ queryKey: ["platform-settings", "portfolio"] });
    },
    onError: (e: any) => toast.error(e?.message || "Could not save the cap"),
  });

  if (!isSuperAdmin) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Portfolio leverage cap</CardTitle>
        <CardDescription>
          Bounds a wallet&apos;s <strong>total</strong> open exposure at{" "}
          <span className="font-mono">balance × cap</span> — separate from the
          per-instrument leverage in Segment Settings, and applied on top of it.
          <br />
          <span className="text-foreground">0 = no aggregate limit.</span>
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {WALLETS.map(({ kind, label, hint }) => {
          const current = saved(kind);
          const value = draft[kind] ?? current;
          const dirty = draft[kind] != null && draft[kind] !== current;
          return (
            <div key={kind} className="flex flex-wrap items-end gap-3">
              <div className="min-w-[9rem]">
                <Label className="text-xs">{label}</Label>
                <p className="text-[11px] text-muted-foreground">{hint}</p>
              </div>
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  min={0}
                  step="0.01"
                  inputMode="decimal"
                  value={value}
                  placeholder={isLoading ? "…" : "0"}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, [kind]: e.target.value }))
                  }
                  className="h-9 w-28 font-tabular tabular-nums"
                />
                <span className="text-sm text-muted-foreground">×</span>
              </div>
              <Button
                size="sm"
                disabled={!dirty}
                loading={save.isPending && save.variables?.kind === kind}
                onClick={() => {
                  const n = Number(draft[kind]);
                  if (!Number.isFinite(n) || n < 0) {
                    toast.error("Enter 0 or a positive number");
                    return;
                  }
                  save.mutate({ kind, value: n });
                  setDraft((d) => {
                    const { [kind]: _drop, ...rest } = d;
                    return rest;
                  });
                }}
              >
                Save
              </Button>
              {current !== "" && Number(current) === 0 && (
                <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  no limit
                </span>
              )}
            </div>
          );
        })}

        {/* The reason this cap exists, kept next to the control that removes
            it — otherwise "0" looks like the obvious answer to every rejected
            order, and the drift it prevents is invisible until it is not. */}
        <div className="flex gap-2 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-[12px] leading-relaxed">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-amber-500" />
          <div>
            <p className="font-semibold text-amber-600 dark:text-amber-400">
              What this protects against
            </p>
            <p className="mt-0.5 text-muted-foreground">
              A per-order margin check only sees one order. A high-leverage leg
              locks little margin for large notional, freeing room a
              low-leverage leg then spends — so the book&apos;s combined
              leverage drifts above what you intended while every single order
              passes its own check. This cap is the only thing that sees the
              whole book.
            </p>
            <p className="mt-1 text-muted-foreground">
              Set it <strong>at or above</strong> your highest per-instrument
              leverage, or users hit it on trades you meant to allow. Set{" "}
              <strong>0</strong> only if you accept unbounded blended leverage.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
