"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Trophy, Zap, Medal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatCoins as formatINR } from "@/lib/games/coins";
import { GamesAPI } from "@/lib/api";
import { GAME_META, type GameUiId } from "@/lib/games/ids";
import { isBiddingOpen, secondsUntilIst, formatDurationHuman } from "@/lib/games/window";
import { useGameConfig, useGamesWallet, useGamesPrice } from "@/components/games/useGames";
import { Countdown, GameHowTo, GameStatePill, StatChip, LiveDot, LivePrice, fmtPrice } from "@/components/games/bits";

/** "2026-07-21" → "21 Jul" for the results strip. */
function fmtJpDay(day: string): string {
  const m = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const p = (day || "").split("-");
  if (p.length !== 3) return day;
  return `${Number(p[2])} ${m[Number(p[1]) - 1] ?? ""}`;
}

export function JackpotScreen({ id }: { id: GameUiId }) {
  const meta = GAME_META[id];
  const cfg = useGameConfig(id);
  const { data: wallet } = useGamesWallet();
  const { data: price } = useGamesPrice(250);
  const qc = useQueryClient();
  const [predicted, setPredicted] = useState("");

  const open = cfg ? isBiddingOpen(cfg.bidding_start_time, cfg.bidding_end_time) : false;
  const balance = Number(wallet?.balance ?? 0);
  const ticket = Number(cfg?.ticket_price ?? 0);

  const live = meta.asset === "BTC" ? price?.btc : price?.nifty;
  const liveNum = live ? Number(live) : 0;
  const resultIn = cfg ? secondsUntilIst(cfg.result_time) : 0;

  const { data: board } = useQuery({
    queryKey: ["games", "leaderboard", id],
    queryFn: () => GamesAPI.jackpotLeaderboard(id, 20),
    refetchInterval: 6000,
    // Keep the last leaderboard on screen while refetching so a transient empty
    // response never flashes "No bids yet" over a populated board.
    placeholderData: (prev) => prev,
  });
  const { data: today } = useQuery({
    queryKey: ["games", "bets", "jackpot-today", id],
    queryFn: () => GamesAPI.jackpotToday(id),
    refetchInterval: 6000,
  });
  // Last 5 declared daily results (settlement close + that day's winner).
  const { data: last5 } = useQuery({
    queryKey: ["games", "jackpot-last5", id],
    queryFn: () => GamesAPI.jackpotLast5(id),
    refetchInterval: 60000,
  });

  const locked = !!board?.official;
  // Locked reference (once official) else the live spot that will be locked.
  const refPrice = board?.referenceSpot ? Number(board.referenceSpot) : liveNum;
  const allRows: any[] = board?.leaderboard || [];
  // Show only the TOP 5 ranks (the winning zone) + always the viewer's own row
  // if it's outside the top 5, so a player still sees where they stand.
  const rows: any[] = (() => {
    const top = allRows.filter((r) => r.rank <= 5);
    const me = allRows.find((r) => r.isMe);
    if (me && me.rank > 5) top.push(me);
    return top;
  })();

  const place = useMutation({
    mutationFn: async () => {
      const p = Number(predicted);
      if (!(p > 0)) throw new Error("Enter your predicted price");
      if (ticket > balance) throw new Error("Insufficient games balance");
      return GamesAPI.jackpotBid({ gameId: id, predictedPrice: p });
    },
    onSuccess: () => {
      toast.success("Bid placed");
      setPredicted("");
      qc.invalidateQueries({ queryKey: ["games", "leaderboard", id] });
      qc.invalidateQueries({ queryKey: ["games", "bets", "jackpot-today", id] });
      qc.invalidateQueries({ queryKey: ["games", "wallet"] });
    },
    onError: (e: any) => toast.error(e?.message || "Could not bid"),
  });

  // Jackpot = MODIFY ONLY (change predicted price); no cancellation.
  const modify = useMutation({
    mutationFn: (v: { id: string; predictedPrice: number }) =>
      GamesAPI.jackpotModify(v.id, { predictedPrice: v.predictedPrice }),
    onSuccess: () => {
      toast.success("Prediction updated");
      qc.invalidateQueries({ queryKey: ["games", "leaderboard", id] });
      qc.invalidateQueries({ queryKey: ["games", "bets", "jackpot-today", id] });
    },
    onError: (e: any) => toast.error(e?.message || "Update failed"),
  });

  const useLive = () => {
    if (liveNum > 0) setPredicted(meta.asset === "BTC" ? String(Math.round(liveNum)) : liveNum.toFixed(2));
  };

  return (
    <div className="space-y-4">
      <GameHowTo
        costText={`1 bid = ${formatINR(ticket)}`}
        payoutLabel={`Closest ${cfg?.top_winners ?? 20} share the pool`}
        steps={[
          `Enter your predicted ${meta.asset} price`,
          `Each bid costs ${formatINR(ticket)}`,
          "Bids closest to the locked result-time price win a share of the prize pool",
        ]}
      />
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="grid size-11 place-items-center rounded-xl bg-atm/15 text-atm">
          <Trophy className="size-6" />
        </span>
        <div className="min-w-0">
          <h1 className="text-xl font-bold tracking-tight">{meta.title}</h1>
          <div className="text-xs text-muted-foreground">
            Predict the {meta.asset} price · closest {cfg?.top_winners ?? 20} share the pool
          </div>
        </div>
        <div className="ml-auto">
          {locked ? (
            <GameStatePill state="closed" label="Locked" />
          ) : open ? (
            <GameStatePill state="open" label="Bidding open" />
          ) : (
            <GameStatePill state="closed" label="Closed" />
          )}
        </div>
      </div>

      {/* Hero: live/locked price + result countdown — 1 col on phone, 2 on tablet+ */}
      <Card className="overflow-hidden border-atm/30">
        <CardContent className="relative grid gap-4 p-4 sm:grid-cols-2 sm:p-5">
          <span aria-hidden className="pointer-events-none absolute -right-10 -top-10 size-40 rounded-full bg-atm/10 blur-3xl" />
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">
              {locked ? "Locked reference" : `Live ${meta.asset} price`}
            </div>
            <LivePrice value={refPrice} className="mt-1 text-3xl font-bold sm:text-4xl" />
            <div className="mt-1">
              <LiveDot live={!!live} label={locked ? "Reference locked" : live ? "Live price" : "Waiting for feed"} />
            </div>
          </div>
          <div className="min-w-0 border-t border-border pt-3 sm:border-l sm:border-t-0 sm:pl-5 sm:pt-0">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">
              {resultIn > 0 ? "Result locks in" : "Declaring result…"}
            </div>
            <Countdown seconds={resultIn} className="mt-1 text-3xl font-bold text-foreground sm:text-4xl" />
            <div className="mt-1 text-xs text-muted-foreground">
              {resultIn > 0 ? <>≈ {formatDurationHuman(resultIn)} · </> : null}
              @ {cfg?.result_time?.slice(0, 5) ?? "—"} IST
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Pool stats — 2 up on phone, 4 across on tablet+ */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatChip label="Total pool" value={formatINR(board?.totalPool ?? 0)} tone="text-atm" />
        <StatChip label="Your rank" value={board?.myRank ? `#${board.myRank}` : "—"} />
        <StatChip label="Ticket price" value={formatINR(ticket)} />
        <StatChip label="Winners share" value={String(cfg?.top_winners ?? 20)} />
      </div>

      {/* Last 5 days results — the daily settlement close + that day's winner */}
      {last5 && last5.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2">
              <Trophy className="size-4 text-atm" /> Last 5 days results
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-5">
              {last5.slice(0, 5).map((r: any, i: number) => (
                <div key={i} className="rounded-xl border border-border/60 bg-muted/20 p-3 text-center">
                  <div className="text-[11px] font-medium text-muted-foreground">{fmtJpDay(r.day)}</div>
                  <div className="mt-1 text-xl font-bold tabular-nums text-atm">
                    {r.close_price ? fmtPrice(Number(r.close_price)) : "—"}
                  </div>
                  <div className="mt-0.5 text-[10px] text-muted-foreground">
                    {r.winner_predicted
                      ? `Winner ${fmtPrice(Number(r.winner_predicted))}`
                      : `${r.bids_count ?? 0} bids`}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Leaderboard + bid — stacked (bid first) on phone, side-by-side on tablet+ */}
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_300px] lg:grid-cols-[minmax(0,1fr)_360px]">
        {/* Leaderboard */}
        <Card className="order-2 min-w-0 md:order-1">
          <CardHeader className="flex-row items-center justify-between pb-3">
            <CardTitle>Top 5 {locked ? "(official)" : "(live)"}</CardTitle>
            <span className="text-xs text-muted-foreground">{allRows.length} bid{allRows.length === 1 ? "" : "s"}</span>
          </CardHeader>
          <CardContent className="space-y-1">
            {rows.length === 0 && (
              <div className="py-6 text-center text-sm text-muted-foreground">
                No bids yet — be the first to predict.
              </div>
            )}
            {rows.map((row: any) => {
              const top3 = row.rank <= 3;
              return (
                <div
                  key={row.rank}
                  className={cn(
                    "flex items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors",
                    row.isMe ? "bg-primary/10 ring-1 ring-inset ring-primary/30" : top3 ? "bg-atm/5" : "hover:bg-muted/40",
                  )}
                >
                  <span className="flex min-w-0 items-center gap-2.5">
                    <span
                      className={cn(
                        "grid size-6 shrink-0 place-items-center rounded-md text-xs font-bold tabular-nums",
                        top3 ? "bg-atm/20 text-atm" : "text-muted-foreground",
                      )}
                    >
                      {top3 ? <Medal className="size-3.5" /> : row.rank}
                    </span>
                    <span className="flex min-w-0 flex-col leading-tight">
                      <span className="flex items-center gap-1.5">
                        <span className="truncate font-semibold tabular-nums">
                          {Number(row.predicted).toLocaleString("en-IN")}
                        </span>
                        {row.isMe && (
                          <span className="shrink-0 rounded bg-primary/20 px-1.5 text-[10px] font-bold text-primary">YOU</span>
                        )}
                      </span>
                      {row.placed_at && (
                        // Placement time (ms-precise) — the tie-breaker.
                        <span className="tabular-nums text-[10px] text-muted-foreground">⏱ {fmtBidTime(row.placed_at)}</span>
                      )}
                    </span>
                  </span>
                  <span className="shrink-0 font-semibold tabular-nums text-buy">{formatINR(row.projectedPrize)}</span>
                </div>
              );
            })}
          </CardContent>
        </Card>

        {/* Bid panel — sticky on tablet+ */}
        <Card className="order-1 h-fit md:order-2 md:sticky md:top-4">
          <CardHeader className="pb-3"><CardTitle>Place your prediction</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Predicted {meta.asset} price</span>
                <span>Bal {formatINR(balance)}</span>
              </div>
              <Input
                type="number"
                inputMode="decimal"
                placeholder={meta.asset === "BTC" ? "e.g. 68000" : "e.g. 23500"}
                value={predicted}
                onChange={(e) => setPredicted(e.target.value)}
              />
              {liveNum > 0 && !locked && (
                <button
                  type="button"
                  onClick={useLive}
                  className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/30 px-2.5 py-1 text-xs font-semibold text-muted-foreground transition-colors hover:border-atm/40 hover:text-atm"
                >
                  <Zap className="size-3" /> Use live {liveNum.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                </button>
              )}
            </div>
            <StatChip label="Ticket price" value={formatINR(ticket)} />
            <Button className="w-full" size="lg" loading={place.isPending} disabled={place.isPending || !open} onClick={() => place.mutate()}>
              {open ? "Place bid" : "Bidding closed"}
            </Button>
            <p className="text-center text-[11px] text-muted-foreground">
              Closest {cfg?.top_winners ?? 20} predictions to the locked price share the pool.
            </p>
            {(today?.bids || []).length > 0 && (
              <div className="border-t border-border pt-3">
                <div className="mb-2 text-xs font-bold text-foreground">
                  Your bids today ({today.bids.length})
                </div>
                <div className="space-y-1.5">
                  {today.bids.map((b: any) => (
                    <div key={b.id} className="rounded-lg border border-border/60 bg-card p-2">
                      <div className="flex items-center justify-between text-sm">
                        <span className="font-bold tabular-nums">
                          {Number(b.predicted).toLocaleString("en-IN")}
                        </span>
                        <span className="font-bold tabular-nums text-atm">{formatINR(b.amount)}</span>
                      </div>
                      <div className="mt-1 flex items-center justify-between text-[11px] text-muted-foreground">
                        {/* millisecond-precise placement time (ties break by this) */}
                        <span className="tabular-nums">⏱ {fmtBidTime(b.created_at)}</span>
                        {b.rank ? (
                          <span className="font-semibold text-foreground">
                            Rank #{b.rank}{Number(b.prize) > 0 ? ` · +${formatINR(b.prize)}` : ""}
                          </span>
                        ) : b.status === "PENDING" && open ? (
                          <button
                            className="font-semibold text-primary hover:underline disabled:opacity-50"
                            disabled={modify.isPending}
                            onClick={() => {
                              const cur = Number(b.predicted).toLocaleString("en-IN");
                              const v = window.prompt(`New predicted price (current ${cur})`, String(b.predicted));
                              if (v === null || v.trim() === "") return;
                              const p = Number(v);
                              if (!(p > 0)) { toast.error("Enter a valid price"); return; }
                              modify.mutate({ id: b.id, predictedPrice: p });
                            }}
                          >
                            ✎ Edit prediction
                          </button>
                        ) : (
                          <span>Pending result</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// Millisecond-precise placement time in IST, e.g. "13:46:18.053" — the exact
// instant the bid landed (jackpot ties break by this, so ms matters).
function fmtBidTime(iso?: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const hms = d.toLocaleTimeString("en-GB", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: false, timeZone: "Asia/Kolkata",
  });
  const ms = String(d.getMilliseconds()).padStart(3, "0");
  return `${hms}.${ms}`;
}
