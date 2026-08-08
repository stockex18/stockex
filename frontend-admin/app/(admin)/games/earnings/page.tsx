"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { AdminGamesAPI } from "@/lib/api";
import { usePager, Pager } from "@/components/common/Pager";

export default function GamesEarningsPage() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["admin", "games", "earnings"],
    queryFn: () => AdminGamesAPI.hierarchyEarnings(),
    refetchInterval: 8000,
  });
  const pg = usePager((data as any[]) || [], 20);

  const release = useMutation({
    mutationFn: ({ userId, amount }: { userId: string; amount: number }) =>
      AdminGamesAPI.releaseHierarchyEarnings(userId, amount),
    onSuccess: () => {
      toast.success("Released to main wallet");
      qc.invalidateQueries({ queryKey: ["admin", "games", "earnings"] });
    },
    onError: (e: any) => toast.error(e?.message || "Release failed"),
  });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Games Earnings"
        description="Held games commission per admin/broker (temporary wallet). Release moves it to their main wallet."
      />
      <Card>
        <CardContent className="space-y-1 p-4">
          {(data || []).length === 0 && (
            <div className="py-8 text-center text-sm text-muted-foreground">No held commission.</div>
          )}
          {pg.slice.map((r: any) => (
            <div key={r.user_id} className="flex items-center justify-between border-b border-border/60 py-3 last:border-0">
              <div className="min-w-0">
                <div className="font-semibold">{r.full_name} <span className="text-xs text-muted-foreground">· {r.user_code} · {r.role}</span></div>
                <div className="text-xs text-muted-foreground">
                  Earned 🪙{Number(r.temporary_total_earned).toLocaleString("en-IN")} · Released 🪙{Number(r.temporary_total_released).toLocaleString("en-IN")}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="text-right">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Held</div>
                  <div className="font-bold tabular-nums text-primary">🪙{Number(r.temporary_balance).toLocaleString("en-IN")}</div>
                </div>
                <Button
                  size="sm"
                  disabled={release.isPending}
                  onClick={() => release.mutate({ userId: r.user_id, amount: Number(r.temporary_balance) })}
                >
                  Release all
                </Button>
              </div>
            </div>
          ))}
          <Pager {...pg} />
        </CardContent>
      </Card>
    </div>
  );
}
