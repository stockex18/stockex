"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDownLeft, ArrowUpRight, BarChart3, Receipt, TrendingDown, TrendingUp } from "lucide-react";
import { ReportsAPI } from "@/lib/api";
import { PageHeader } from "@/components/common/PageHeader";
import { DataTable, type Column } from "@/components/common/DataTable";
import { ReportPdfButton } from "@/components/common/ReportPdfButton";
import { DateRangeBar, toIsoFrom, toIsoTo, type DateRange } from "@/components/common/DateRangeBar";
import { Card } from "@/components/ui/card";
import { cn, formatINR, pnlColor } from "@/lib/utils";
import { ListSkeleton, Skeleton } from "@/components/common/Skeleton";

export default function PnlReportPage() {
  // Default to last 30 days so first paint matches the historical
  // page title ("Last 30 days · By symbol") and the backend default.
  const [range, setRange] = useState<DateRange>(() => {
    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - 30);
    const iso = (d: Date) =>
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    return { from: iso(from), to: iso(to) };
  });

  const params = useMemo(
    () => ({ from_date: toIsoFrom(range.from), to_date: toIsoTo(range.to) }),
    [range],
  );

  const { data, isFetching } = useQuery({
    queryKey: ["reports", "pnl", params],
    queryFn: () => ReportsAPI.pnl(params),
    placeholderData: (prev) => prev,
  });

  const rows = (data?.by_symbol ?? []) as any[];
  const firstLoad = isFetching && !data;
  const netPnl = Number(data?.net_pnl ?? 0);
  // GROSS = realised P&L before brokerage (net + charges), straight from the
  // backend. NOT (sell_value − buy_value) — that turned the unmatched leg of
  // any open/reopened position into a phantom multi-crore loss (the backend
  // now sums Trade.pnl_inr, FIFO quantity-matched, so this stays sane).
  const grossPnl = Number(data?.total_realized ?? 0);
  const charges = Number(data?.total_charges ?? 0);

  const cols: Column<any>[] = [
    { key: "symbol", header: "Symbol", render: (r) => <span className="font-medium">{r.symbol}</span> },
    { key: "buy_qty", header: "Buy qty", align: "right" },
    { key: "sell_qty", header: "Sell qty", align: "right" },
    { key: "buy_value", header: "Buy value", align: "right", render: (r) => formatINR(r.buy_value) },
    { key: "sell_value", header: "Sell value", align: "right", render: (r) => formatINR(r.sell_value) },
    { key: "charges", header: "Charges", align: "right", render: (r) => <span className="text-muted-foreground">{formatINR(r.charges)}</span> },
    {
      key: "pnl",
      header: "Net P&L",
      align: "right",
      render: (r) => (
        <span className={cn("font-semibold tabular-nums", pnlColor(r.pnl))}>
          {Number(r.pnl) > 0 ? "+" : ""}
          {formatINR(r.pnl)}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="P&L report"
        description="Realised profit & loss grouped by symbol."
        actions={<ReportPdfButton kind="pnl" params={params} />}
      />

      <DateRangeBar value={range} onChange={setRange} />

      <div data-tour="rep-summary" className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat
          label="Trades"
          value={String(data?.total_trades ?? 0)}
          icon={BarChart3}
          loading={firstLoad}
        />
        <Stat
          label="Gross P&L"
          value={formatINR(grossPnl)}
          icon={grossPnl >= 0 ? ArrowUpRight : ArrowDownLeft}
          tone={grossPnl >= 0 ? "profit" : grossPnl < 0 ? "loss" : "muted"}
          loading={firstLoad}
        />
        <Stat
          label="Charges"
          value={formatINR(charges)}
          icon={Receipt}
          tone="muted"
          loading={firstLoad}
        />
        <Stat
          label="Net P&L"
          value={formatINR(netPnl)}
          icon={netPnl >= 0 ? TrendingUp : TrendingDown}
          tone={netPnl >= 0 ? "profit" : netPnl < 0 ? "loss" : "muted"}
          emphasis
          loading={firstLoad}
        />
      </div>

      {/* Desktop: standard table. Mobile: stacked cards because a 7-column
          table on a 360-wide screen forces horizontal scrolling — the
          operator's 21-May UX feedback was specifically that this page
          looked broken on phone. */}
      <div data-tour="rep-table" className="hidden md:block">
        <DataTable
          columns={cols}
          rows={rows}
          keyExtractor={(r) => r.symbol}
          loading={isFetching && !data}
          empty="No trades in the selected period."
        />
      </div>
      <div data-tour="rep-table" className="md:hidden">
        <MobileSymbolList rows={rows} loading={isFetching && !data} />
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  icon: Icon,
  tone = "default",
  emphasis = false,
  loading = false,
}: {
  label: string;
  value: string;
  icon?: any;
  tone?: "default" | "profit" | "loss" | "muted";
  emphasis?: boolean;
  /** First load: show a placeholder, not a misleading 0.00. */
  loading?: boolean;
}) {
  const toneClass =
    tone === "profit"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "loss"
      ? "text-red-600 dark:text-red-400"
      : tone === "muted"
      ? "text-muted-foreground"
      : "";
  // Subtle tinted surface for the money tiles so Gross / Net P&L pop without
  // shouting — neutral tiles (Trades, Charges) stay plain.
  const toneSurface =
    tone === "profit"
      ? "border-emerald-500/20 bg-emerald-500/[0.06]"
      : tone === "loss"
      ? "border-red-500/20 bg-red-500/[0.06]"
      : "";
  return (
    <Card
      className={cn(
        "p-3 sm:p-4",
        toneSurface,
        emphasis && "ring-1 ring-inset ring-primary/25"
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[10px] font-medium uppercase tracking-wider text-muted-foreground sm:text-[11px]">
          {label}
        </span>
        {Icon && (
          <Icon
            className={cn("size-4 shrink-0", toneClass || "text-muted-foreground/50")}
          />
        )}
      </div>
      <div
        className={cn(
          "mt-1.5 text-lg font-bold tabular-nums sm:text-2xl",
          toneClass
        )}
      >
        {loading ? <Skeleton className="my-1 h-6 w-24 sm:h-7" /> : value}
      </div>
    </Card>
  );
}

function MobileSymbolList({ rows, loading }: { rows: any[]; loading: boolean }) {
  if (loading && rows.length === 0) {
    return (
      <Card className="overflow-hidden p-0">
        <ListSkeleton rows={5} />
      </Card>
    );
  }
  if (rows.length === 0) {
    return (
      <Card className="p-6 text-center text-sm text-muted-foreground">
        No trades in the selected period.
      </Card>
    );
  }
  return (
    <div className="space-y-2.5">
      {rows.map((r) => {
        const pnl = Number(r.pnl ?? 0);
        const accent =
          pnl > 0 ? "border-l-emerald-500" : pnl < 0 ? "border-l-red-500" : "border-l-border";
        const pnlBadge =
          pnl > 0
            ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
            : pnl < 0
            ? "bg-red-500/10 text-red-600 dark:text-red-400"
            : "bg-muted text-muted-foreground";
        return (
          <Card key={r.symbol} className={cn("border-l-4 p-3", accent)}>
            {/* Header: symbol + P&L badge */}
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-sm font-semibold">{r.symbol}</span>
              <span
                className={cn(
                  "shrink-0 rounded-full px-2 py-0.5 text-xs font-bold tabular-nums",
                  pnlBadge
                )}
              >
                {pnl > 0 ? "+" : ""}
                {formatINR(pnl)}
              </span>
            </div>

            {/* Buy / Sell two-column block */}
            <div className="mt-3 grid grid-cols-2 gap-3">
              <div className="rounded-lg bg-muted/40 p-2">
                <div className="text-[10px] font-medium uppercase tracking-wide text-emerald-600/80 dark:text-emerald-400/80">
                  Buy
                </div>
                <div className="mt-0.5 text-xs tabular-nums">{r.buy_qty ?? 0} qty</div>
                <div className="text-xs font-medium tabular-nums">{formatINR(r.buy_value)}</div>
              </div>
              <div className="rounded-lg bg-muted/40 p-2">
                <div className="text-[10px] font-medium uppercase tracking-wide text-red-600/80 dark:text-red-400/80">
                  Sell
                </div>
                <div className="mt-0.5 text-xs tabular-nums">{r.sell_qty ?? 0} qty</div>
                <div className="text-xs font-medium tabular-nums">{formatINR(r.sell_value)}</div>
              </div>
            </div>

            {/* Charges footer */}
            <div className="mt-2.5 flex items-center justify-between border-t border-border/50 pt-2 text-xs">
              <span className="text-muted-foreground">Charges</span>
              <span className="tabular-nums text-muted-foreground">{formatINR(r.charges)}</span>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

