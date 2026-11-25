"use client";

import { useState, Suspense } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { AlertsAPI } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/common/PageHeader";
import { DataTable, type Column } from "@/components/common/DataTable";
import { StatusPill } from "@/components/common/StatusPill";

import { PageTourAuto } from "@/components/tour/PageTourAuto";
import { PushOptIn } from "@/components/common/PushOptIn";
import { NewAlertDialog } from "@/components/alerts/NewAlertDialog";
import { cn } from "@/lib/utils";

function fmtNum(v: string | number | null | undefined): string {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : "—";
}

function firedAt(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export default function AlertsPage() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["alerts"],
    queryFn: () => AlertsAPI.list(),
    // The live "price_alert" event refreshes this at once; this only covers
    // a dropped socket.
    refetchInterval: 15_000,
  });
  const [open, setOpen] = useState(false);

  async function remove(id: string) {
    try {
      await AlertsAPI.delete(id);
      toast.success("Deleted");
      qc.invalidateQueries({ queryKey: ["alerts"] });
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  const cols: Column<any>[] = [
    { key: "symbol", header: "Symbol" },
    { key: "alert_type", header: "Type", render: (r) => <StatusPill status={r.alert_type.replace("_", " ")} /> },
    { key: "target_price", header: "Target", align: "right" },
    {
      key: "is_triggered",
      header: "Triggered",
      render: (r) =>
        r.is_triggered ? (
          <span className="leading-tight">
            <span className="block font-semibold text-emerald-500">
              Yes{r.triggered_price ? ` @ ${r.triggered_price}` : ""}
            </span>
            {r.triggered_at && (
              <span className="block text-[11px] text-muted-foreground">{firedAt(r.triggered_at)}</span>
            )}
          </span>
        ) : (
          "No"
        ),
    },
    { key: "note", header: "Note" },
    { key: "created_at", header: "Created", render: (r) => new Date(r.created_at).toLocaleDateString() },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (r) => (
        <Button variant="ghost" size="icon" onClick={() => remove(r.id)} aria-label="Delete">
          <Trash2 className="size-4 text-destructive" />
        </Button>
      ),
    },
  ];

  const rows: any[] = data ?? [];

  return (
    <div className="space-y-4">
      <Suspense fallback={null}>
        <PageTourAuto id="alerts" />
      </Suspense>
      <PageHeader
        title="Price alerts"
        actions={
          <Button data-tour="al-new" onClick={() => setOpen(true)}>
            <Plus className="size-4" /> New alert
          </Button>
        }
      />
      <NewAlertDialog open={open} onOpenChange={setOpen} />
      <PushOptIn variant="banner" />

      {/* Wide screens: the table. */}
      <div data-tour="al-list" className="hidden sm:block">
        <DataTable columns={cols} rows={data} keyExtractor={(r) => r.id} />
      </div>

      {/* Phones: one card per alert, delete always in reach (the table pushed
          it off-screen to the right). */}
      <div className="space-y-2 sm:hidden">
        {rows.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border px-4 py-10 text-center text-sm text-muted-foreground">
            No alerts yet. Tap <span className="font-semibold text-foreground">New alert</span>, or the 🔔 on a
            symbol in Market.
          </div>
        ) : (
          rows.map((r) => {
            const above = r.alert_type === "LTP_ABOVE";
            return (
              <div
                key={r.id}
                className={cn(
                  "flex items-start justify-between gap-3 rounded-xl border bg-card p-3",
                  r.is_triggered ? "border-emerald-500/40" : "border-border",
                )}
              >
                <div className="min-w-0 space-y-1">
                  <div className="truncate text-sm font-bold">{r.symbol}</div>
                  <div className="text-sm">
                    <span className={cn("font-semibold", above ? "text-buy" : "text-sell")}>
                      {above ? "Rises above" : "Falls below"}
                    </span>{" "}
                    <span className="font-tabular tabular-nums">{fmtNum(r.target_price)}</span>
                  </div>
                  {r.is_triggered ? (
                    <div className="text-xs font-semibold text-emerald-500">
                      Hit{r.triggered_price ? ` at ${fmtNum(r.triggered_price)}` : ""}
                      {r.triggered_at ? ` · ${firedAt(r.triggered_at)}` : ""}
                    </div>
                  ) : (
                    <div className="text-xs text-muted-foreground">Waiting</div>
                  )}
                  {r.note && <div className="truncate text-xs text-muted-foreground">Note: {r.note}</div>}
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="shrink-0"
                  onClick={() => remove(r.id)}
                  aria-label={`Delete alert for ${r.symbol}`}
                >
                  <Trash2 className="size-4 text-destructive" />
                </Button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
