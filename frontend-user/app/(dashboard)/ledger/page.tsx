"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Gamepad2, Wallet as WalletIcon, Layers } from "lucide-react";
import { LedgerAPI, GamesAPI } from "@/lib/api";
import { PageHeader } from "@/components/common/PageHeader";
import { Pagination } from "@/components/common/Pagination";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, formatINR, pnlColor } from "@/lib/utils";
import { ALL_GAME_IDS, GAME_META, SETTINGS_KEY } from "@/lib/games/ids";

// game_key (GameSettings key) → human title, e.g. "niftyBracket" → "Nifty Bracket".
const GAME_KEY_TITLE: Record<string, string> = {};
for (const id of ALL_GAME_IDS) GAME_KEY_TITLE[SETTINGS_KEY[id]] = GAME_META[id].title;

type Source = "all" | "trading" | "games";

type UnifiedRow = {
  id: string;
  date: string;
  source: "trading" | "games";
  type: string;
  label: string;
  is_settlement: boolean;
  particulars: string;
  debit: number;
  credit: number;
  balance: number;
};

const SOURCES: { id: Source; label: string; icon: any }[] = [
  { id: "all", label: "All", icon: Layers },
  { id: "trading", label: "Trading", icon: WalletIcon },
  { id: "games", label: "Games", icon: Gamepad2 },
];

/** Normalise one games-wallet ledger entry into the shared row shape. */
function gamesRowToUnified(r: any): UnifiedRow {
  const kind = String(r?.meta?.kind || "").toUpperCase();
  const amt = Number(r.amount) || 0;
  const isCredit = String(r.entry_type).toUpperCase() === "CREDIT";
  const gameTitle = r.game_key ? GAME_KEY_TITLE[r.game_key] || r.game_key : null;

  // Category label + type by the kind of games movement.
  let label = isCredit ? "Credit" : "Debit";
  let type = "GAMES";
  if (kind === "BET") {
    label = "Ticket";
    type = "GAMES_BET";
  } else if (kind === "WIN") {
    label = "Win";
    type = "GAMES_WIN";
  } else if (kind === "TRANSFER_IN") {
    label = "Transfer in";
    type = "GAMES_TXN";
  } else if (kind === "TRANSFER_OUT" || kind === "TRANSFER_OUT_REVERT") {
    label = "Transfer out";
    type = "GAMES_TXN";
  } else if (kind === "REFERRAL") {
    label = "Referral";
    type = "GAMES_WIN";
  }

  // Detail: prefix the game title so "which game" is obvious.
  const desc = r.description || label;
  const particulars = gameTitle ? `${gameTitle} · ${desc}` : desc;

  return {
    id: `g_${r.id}`,
    date: r.created_at,
    source: "games",
    type,
    label,
    is_settlement: false,
    particulars,
    debit: isCredit ? 0 : amt,
    credit: isCredit ? amt : 0,
    balance: Number(r.balance_after) || 0,
  };
}

export default function UserLedgerPage() {
  const [source, setSource] = useState<Source>("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  // Trading ledger — last 30 days (backend sorts asc then limits).
  const range = useMemo(() => {
    const now = new Date();
    const start = new Date(now);
    start.setMonth(start.getMonth() - 1);
    return { from_date: start.toISOString(), to_date: now.toISOString() };
  }, []);
  const {
    data: tradingData,
    isFetching: tradingLoading,
    isError: tradingFailed,
    refetch: refetchTrading,
  } = useQuery({
    queryKey: ["ledger", range],
    queryFn: () => LedgerAPI.list({ ...range, limit: 1000 }),
    enabled: source !== "games",
  });
  // Games-wallet ledger — recent activity (bets / wins / transfers).
  const {
    data: gamesData,
    isFetching: gamesLoading,
    isError: gamesFailed,
    refetch: refetchGames,
  } = useQuery({
    queryKey: ["games", "ledger", "all"],
    queryFn: () => GamesAPI.ledger({ limit: 1000 }),
    enabled: source !== "trading",
  });

  const tradingRows: UnifiedRow[] = useMemo(
    () =>
      ((tradingData?.rows ?? []) as any[]).map((r) => ({
        id: `t_${r.id}`,
        date: r.date,
        source: "trading" as const,
        type: r.type,
        label: r.label,
        is_settlement: !!r.is_settlement,
        particulars: r.particulars,
        debit: Number(r.debit) || 0,
        credit: Number(r.credit) || 0,
        balance: Number(r.balance) || 0,
      })),
    [tradingData]
  );
  const gamesRows: UnifiedRow[] = useMemo(
    () => ((gamesData ?? []) as any[]).map(gamesRowToUnified),
    [gamesData]
  );

  const rows = useMemo(() => {
    const pick =
      source === "trading" ? tradingRows : source === "games" ? gamesRows : [...tradingRows, ...gamesRows];
    return [...pick].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
  }, [source, tradingRows, gamesRows]);

  const pagedRows = useMemo(() => {
    const start = (page - 1) * pageSize;
    return rows.slice(start, start + pageSize);
  }, [rows, page, pageSize]);

  const isFetching = source === "games" ? gamesLoading : source === "trading" ? tradingLoading : tradingLoading || gamesLoading;
  const hasData = source === "games" ? !!gamesData : source === "trading" ? !!tradingData : !!tradingData || !!gamesData;

  // A failed call used to land on "No transactions yet." — the same screen an
  // account with no history gets. Say it plainly instead, and give the user
  // the one button that fixes it.
  const failed =
    source === "games" ? !!gamesFailed : source === "trading" ? !!tradingFailed : !!tradingFailed || !!gamesFailed;
  const retry = () => {
    if (source !== "games") refetchTrading();
    if (source !== "trading") refetchGames();
  };

  // Games summary (tickets bought / winnings / current games balance).
  const gamesSummary = useMemo(() => {
    let tickets = 0;
    let won = 0;
    for (const r of gamesRows) {
      if (r.type === "GAMES_BET") tickets += r.debit;
      if (r.type === "GAMES_WIN") won += r.credit;
    }
    const balance = gamesRows.length ? gamesRows[0].balance : 0; // newest row's running balance
    return { tickets, won, balance };
  }, [gamesRows]);

  const totalSettlementBooked = Number(tradingData?.total_settlement_booked ?? 0);

  return (
    <div className="space-y-4">
      <PageHeader title="Ledger" description={`${rows.length} entries`} />

      {/* Source selector — Trading account / Games wallet / All together. */}
      <div className="flex flex-wrap gap-2">
        {SOURCES.map((s) => {
          const Icon = s.icon;
          const active = source === s.id;
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => {
                setSource(s.id);
                setPage(1);
              }}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors",
                active
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground"
              )}
            >
              <Icon className="size-3.5" />
              {s.label}
            </button>
          );
        })}
      </div>

      {/* Summary cards — Trading shows opening/closing/net; Games shows
          tickets/winnings/balance. "All" hides them (two independent wallets
          don't share one running balance). */}
      {source === "trading" && (
        <div className={cn("grid grid-cols-2 gap-3", totalSettlementBooked > 0 ? "md:grid-cols-4" : "md:grid-cols-3")}>
          <SummaryCard label="Opening balance" value={formatINR(tradingData?.opening_balance)} />
          <SummaryCard label="Closing balance" value={formatINR(tradingData?.closing_balance)} />
          <SummaryCard
            label="Net change"
            value={formatINR((tradingData?.closing_balance ?? 0) - (tradingData?.opening_balance ?? 0))}
            valueClass={pnlColor((tradingData?.closing_balance ?? 0) - (tradingData?.opening_balance ?? 0))}
          />
          {totalSettlementBooked > 0 && (
            <Card className="border-amber-500/40 bg-amber-500/10">
              <CardHeader className="pb-2">
                <CardDescription className="flex items-center gap-1.5 text-amber-700 dark:text-amber-300">
                  <AlertCircle className="size-3.5" /> Settlement booked
                </CardDescription>
                <CardTitle className="font-tabular text-xl font-bold text-amber-700 dark:text-amber-300">
                  {formatINR(totalSettlementBooked)}
                </CardTitle>
                <p className="pt-1 text-[10px] text-muted-foreground">Informational — not deducted from your balance.</p>
              </CardHeader>
            </Card>
          )}
        </div>
      )}
      {source === "games" && (
        <div className="grid grid-cols-3 gap-3">
          <SummaryCard label="Games balance" value={formatINR(gamesSummary.balance)} />
          <SummaryCard label="Tickets bought" value={formatINR(gamesSummary.tickets)} valueClass="text-destructive" />
          <SummaryCard label="Winnings" value={formatINR(gamesSummary.won)} valueClass="text-emerald-600 dark:text-emerald-400" />
        </div>
      )}

      {failed && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs">
          <span className="flex items-center gap-1.5 text-destructive">
            <AlertCircle className="size-3.5 shrink-0" />
            Could not load your ledger{rows.length > 0 ? " fully" : ""}. Nothing is missing from your
            account — this is a connection problem.
          </span>
          <button
            type="button"
            onClick={retry}
            disabled={isFetching}
            className="rounded-md border border-destructive/50 px-2.5 py-1 font-semibold text-destructive transition-colors hover:bg-destructive/15 disabled:opacity-50"
          >
            {isFetching ? "Retrying…" : "Retry"}
          </button>
        </div>
      )}

      {source !== "games" && tradingData?.truncated && (
        <p className="text-[11px] text-muted-foreground">
          Showing your most recent {Number(tradingData.count).toLocaleString("en-IN")} trading
          entries. Older ones are in Reports.
        </p>
      )}

      {isFetching && !hasData ? (
        <div className="rounded-lg border border-border p-8 text-center text-xs text-muted-foreground">Loading…</div>
      ) : pagedRows.length === 0 ? (
        failed ? null : (
          <div className="rounded-lg border border-border p-8 text-center text-xs text-muted-foreground">
            {source === "games" ? "No games activity yet." : "No transactions yet."}
          </div>
        )
      ) : (
        <>
          {/* Mobile (< md): stacked cards. */}
          <div className="space-y-2 md:hidden">
            {pagedRows.map((r) => (
              <LedgerCardMobile key={r.id} row={r} showSource={source === "all"} />
            ))}
          </div>

          {/* Desktop (md+): full table. */}
          <div className="hidden overflow-x-auto rounded-lg border border-border md:block">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-semibold">Date</th>
                  {source === "all" && <th className="px-3 py-2 text-left font-semibold">Wallet</th>}
                  <th className="px-3 py-2 text-left font-semibold">Category</th>
                  <th className="px-3 py-2 text-left font-semibold">Detail</th>
                  <th className="px-3 py-2 text-right font-semibold">Debit</th>
                  <th className="px-3 py-2 text-right font-semibold">Credit</th>
                  <th className="px-3 py-2 text-right font-semibold">Balance</th>
                </tr>
              </thead>
              <tbody>
                {pagedRows.map((r) => (
                  <LedgerRowView key={r.id} row={r} showSource={source === "all"} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <Pagination
        page={page}
        pageSize={pageSize}
        total={rows.length}
        onPageChange={setPage}
        onPageSizeChange={setPageSize}
        pageSizeOptions={[25, 50, 100, 200]}
      />
    </div>
  );
}

function SummaryCard({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className={cn("font-tabular text-xl", valueClass)}>{value}</CardTitle>
      </CardHeader>
    </Card>
  );
}

function SourceBadge({ source }: { source: "trading" | "games" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide",
        source === "games"
          ? "bg-violet-500/15 text-violet-600 dark:text-violet-300"
          : "bg-sky-500/15 text-sky-600 dark:text-sky-300"
      )}
    >
      {source === "games" ? <Gamepad2 className="size-2.5" /> : <WalletIcon className="size-2.5" />}
      {source === "games" ? "Games" : "Trading"}
    </span>
  );
}

function LedgerRowView({ row, showSource }: { row: UnifiedRow; showSource: boolean }) {
  const isSettlement = row.is_settlement;
  const isPnl = row.type === "PNL";
  const isWin = row.type === "GAMES_WIN";
  const isBet = row.type === "GAMES_BET";
  const pnlSign = isPnl ? (row.credit > 0 ? 1 : -1) : isWin ? 1 : isBet ? -1 : 0;

  return (
    <tr
      className={cn(
        "border-t border-border/60 transition-colors hover:bg-muted/15",
        isSettlement && "bg-amber-500/10 hover:bg-amber-500/15"
      )}
    >
      <td className="whitespace-nowrap px-3 py-2 font-tabular text-xs text-muted-foreground">
        {new Date(row.date).toLocaleString()}
      </td>
      {showSource && (
        <td className="px-3 py-2">
          <SourceBadge source={row.source} />
        </td>
      )}
      <td className="px-3 py-2">
        <CategoryPill label={row.label} isSettlement={isSettlement} pnlSign={pnlSign} />
      </td>
      <td className="px-3 py-2 text-xs">
        <span
          className={cn("block max-w-[420px] truncate", isSettlement && "font-semibold text-amber-700 dark:text-amber-300")}
          title={row.particulars}
        >
          {row.particulars}
        </span>
      </td>
      <td
        className={cn(
          "whitespace-nowrap px-3 py-2 text-right font-tabular tabular-nums",
          row.debit > 0 && "text-destructive",
          isSettlement && row.debit > 0 && "font-bold"
        )}
      >
        {row.debit > 0 ? formatINR(row.debit) : ""}
      </td>
      <td className={cn("whitespace-nowrap px-3 py-2 text-right font-tabular tabular-nums", row.credit > 0 && "text-emerald-600 dark:text-emerald-400")}>
        {row.credit > 0 ? formatINR(row.credit) : ""}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right font-tabular tabular-nums font-semibold">{formatINR(row.balance)}</td>
    </tr>
  );
}

function LedgerCardMobile({ row, showSource }: { row: UnifiedRow; showSource: boolean }) {
  const isSettlement = row.is_settlement;
  const isPnl = row.type === "PNL";
  const isWin = row.type === "GAMES_WIN";
  const isBet = row.type === "GAMES_BET";
  const pnlSign = isPnl ? (row.credit > 0 ? 1 : -1) : isWin ? 1 : isBet ? -1 : 0;

  const isDebit = row.debit > 0;
  const amount = isDebit ? row.debit : row.credit;
  const hasAmount = amount > 0;

  return (
    <div className={cn("rounded-xl border border-border/60 bg-card p-3", isSettlement && "border-amber-500/40 bg-amber-500/10")}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {showSource && <SourceBadge source={row.source} />}
          <CategoryPill label={row.label} isSettlement={isSettlement} pnlSign={pnlSign} />
        </div>
        <span className="shrink-0 font-tabular text-[10px] text-muted-foreground">{new Date(row.date).toLocaleString()}</span>
      </div>

      <p className={cn("mt-2 text-xs leading-snug text-foreground/90", isSettlement && "font-semibold text-amber-700 dark:text-amber-300")}>
        {row.particulars}
      </p>

      <div className="mt-2.5 flex items-end justify-between border-t border-border/50 pt-2">
        <div
          className={cn(
            "font-tabular text-base font-semibold tabular-nums",
            !hasAmount && "text-muted-foreground",
            hasAmount && isDebit && "text-destructive",
            hasAmount && !isDebit && "text-emerald-600 dark:text-emerald-400"
          )}
        >
          {hasAmount ? `${isDebit ? "−" : "+"}${formatINR(amount)}` : "—"}
        </div>
        <div className="text-right">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Balance</div>
          <div className="font-tabular text-sm font-semibold tabular-nums">{formatINR(row.balance)}</div>
        </div>
      </div>
    </div>
  );
}

function CategoryPill({ label, isSettlement, pnlSign }: { label: string; isSettlement: boolean; pnlSign: number }) {
  let cls = "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide";
  if (isSettlement) {
    cls += " bg-amber-500/20 text-amber-700 dark:text-amber-300";
  } else if (pnlSign > 0) {
    cls += " bg-emerald-500/15 text-emerald-700 dark:text-emerald-300";
  } else if (pnlSign < 0) {
    cls += " bg-rose-500/15 text-rose-700 dark:text-rose-300";
  } else {
    cls += " bg-muted text-muted-foreground";
  }
  return <span className={cls}>{label}</span>;
}
