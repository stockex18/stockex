"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { TrendingUp, TrendingDown, Trophy, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatCoins as formatINR } from "@/lib/games/coins";
import { GamesAPI } from "@/lib/api";
import { GAME_META, type GameUiId } from "@/lib/games/ids";
import { getTradingWindowInfo } from "@/lib/games/window";
import { validateBet } from "@/lib/games/validate";
import { useGameConfig, useGamesKlines, useGamesPrice, useGamesWallet } from "@/components/games/useGames";
import { Countdown, GameStatePill, LiveDot, LivePrice } from "@/components/games/bits";
import { type Candle } from "@/components/trading/LiveCandleChart";

const TICKET_QUICK = [1, 2, 5, 10];

function fmtIST(d: Date): string {
  return d.toLocaleTimeString("en-GB", { timeZone: "Asia/Kolkata", hour12: false });
}
function num(v: any): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}
/** Clean "result time" for an up/down window — the exact IST boundary at which
 *  the result was decided, i.e. the CLOSE of the outcome window (W+1). A bet on
 *  window W settles on close(W+1); windows run back-to-back from `start_time`,
 *  so that close = start_time + (W+1)·round. Shows HH:MM:SS on the grid
 *  (e.g. 13:15:00) instead of the raw settlement timestamp with its grace
 *  seconds (13:16:36). */
function resultWindowTime(startTime: string | undefined, roundSec: number, windowNumber: number): string {
  if (!startTime || !Number.isFinite(windowNumber)) return "—";
  const [h, m, s] = startTime.split(":").map((x) => Number(x) || 0);
  const total = h * 3600 + m * 60 + s + (windowNumber + 1) * roundSec;
  const hh = Math.floor(total / 3600) % 24;
  const mm = Math.floor((total % 3600) / 60);
  const ss = total % 60;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(hh)}:${p(mm)}:${p(ss)}`;
}
/** Always render exactly 2 decimals so a whole number (61804) shows as
 *  "61,804.00" instead of "61,804" — keeps the OHLC columns aligned. */
function fmt2(v: number | undefined | null): string {
  if (v == null) return "—";
  return Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function GameScreen({ id }: { id: GameUiId }) {
  const meta = GAME_META[id];
  const asset: "btc" | "nifty" = meta.asset === "BTC" ? "btc" : "nifty";
  const cfg = useGameConfig(id);
  const { data: wallet } = useGamesWallet();
  const { data: price } = useGamesPrice(250);
  const qc = useQueryClient();

  const [prediction, setPrediction] = useState<"UP" | "DOWN" | null>(null);
  const [tickets, setTickets] = useState(1);

  // Candle timeframe MATCHES the game window. A 15-min game reads a 15-min
  // candle — a 5-min candle is meaningless here (three of them per window,
  // none of which is the candle whose close decides the result). Derived from
  // round_duration so any window length lines up.
  const roundSec = cfg?.round_duration || 900;
  const { ivStr, ivSec, ivLabel } = useMemo(() => {
    if (roundSec >= 3600) return { ivStr: "1h", ivSec: 3600, ivLabel: "1-hour" };
    if (roundSec >= 1800) return { ivStr: "30m", ivSec: 1800, ivLabel: "30-min" };
    if (roundSec >= 900) return { ivStr: "15m", ivSec: 900, ivLabel: "15-min" };
    return { ivStr: "5m", ivSec: 300, ivLabel: "5-min" };
  }, [roundSec]);
  const { data: kdata } = useGamesKlines(asset, ivStr, asset === "btc" ? 5000 : 8000);
  const candles: Candle[] = kdata?.candles || [];

  const live = meta.asset === "BTC" ? price?.btc : price?.nifty;
  const liveNum = live ? Number(live) : 0;

  const win = useMemo(() => {
    if (!cfg) return null;
    return getTradingWindowInfo(cfg.start_time, cfg.end_time, cfg.round_duration || 900);
  }, [cfg, live]);

  const { data: bets } = useQuery({
    queryKey: ["games", "bets", id],
    queryFn: () => GamesAPI.bets(id, 25),
    refetchInterval: 4000,
  });
  const { data: results } = useQuery({
    queryKey: ["games", "results", id],
    queryFn: () => GamesAPI.results(id, { limit: 12 }),
    refetchInterval: meta.asset === "BTC" ? 4000 : 8000,
  });

  const ticketPrice = num(cfg?.ticket_price) || 300;
  const maxTickets = cfg?.max_tickets ?? 500;
  const minTickets = cfg?.min_tickets ?? 1;
  const balance = num(wallet?.balance);
  const balanceTkt = ticketPrice > 0 ? balance / ticketPrice : 0;
  const amount = tickets * ticketPrice;
  const potential = amount * num(cfg?.win_multiplier);
  const mult = num(cfg?.win_multiplier) || 1.95;

  // OHLC panels — selected by WALL-CLOCK bucket, not array position.
  //
  // The old `candles[len-1]` / `candles[len-2]` picked the forming and closed
  // candles by index. Right at a candle boundary the feed appends/withholds
  // the new forming candle between polls, so the index of "last closed"
  // shifted every few seconds and the panel's O/H/L/C jumped around — the
  // "12:00:XX ke baad baar-baar fluctuate" the user saw.
  //
  // Anchoring to the current interval bucket (Math.floor(now/iv)*iv) makes
  // "last closed" the newest candle strictly BEFORE this bucket — a candle
  // fully in the past, so it can't change within the window. `forming` is the
  // candle for the current bucket (or synthesised from the live price if the
  // feed hasn't emitted it yet). Nothing "closed" ever carries the live price.
  const nowSec = Math.floor(Date.now() / 1000);
  const curBucket = Math.floor(nowSec / ivSec) * ivSec;
  const formingBase = candles.find((c) => c.time === curBucket);
  const formingLive: Candle | undefined = formingBase
    ? {
        ...formingBase,
        close: liveNum || formingBase.close,
        high: Math.max(formingBase.high, liveNum || 0),
        low: liveNum ? Math.min(formingBase.low, liveNum) : formingBase.low,
      }
    : liveNum
      ? { time: curBucket, open: liveNum, high: liveNum, low: liveNum, close: liveNum }
      : undefined;
  // Latest candle whose bucket has fully elapsed. Frozen for the whole window.
  const lastClosed = useMemo(() => {
    for (let i = candles.length - 1; i >= 0; i--) {
      if (candles[i].time < curBucket) return candles[i];
    }
    return undefined;
  }, [candles, curBucket]);

  // Window display times
  const closeAt = win?.canTrade ? new Date(Date.now() + win.secondsToClose * 1000) : null;
  const openAt = closeAt ? new Date(closeAt.getTime() - (cfg?.round_duration || 900) * 1000) : null;

  const place = useMutation({
    mutationFn: async () => {
      const check = validateBet({
        amount, balance, ticketPrice, minTickets, maxTickets,
        enabled: cfg?.enabled !== false, windowOpen: !!win?.canTrade,
        hasSelection: prediction !== null,
      });
      if (!check.ok) throw new Error(check.reason);
      return GamesAPI.placeBet({
        gameId: id, prediction: prediction!, amount, entryPrice: liveNum,
        windowNumber: win!.windowNumber,
      });
    },
    onSuccess: () => {
      toast.success(`${tickets} T on ${prediction} placed`);
      setPrediction(null);
      qc.invalidateQueries({ queryKey: ["games", "bets", id] });
      qc.invalidateQueries({ queryKey: ["games", "wallet"] });
    },
    onError: (e: any) => toast.error(e?.message || "Could not place bet"),
  });

  const invalidateBets = () => {
    qc.invalidateQueries({ queryKey: ["games", "bets", id] });
    qc.invalidateQueries({ queryKey: ["games", "wallet"] });
  };
  const modifyBet = useMutation({
    mutationFn: (v: { id: string; prediction?: "UP" | "DOWN"; amount?: number }) =>
      GamesAPI.modifyBet(v.id, { prediction: v.prediction, amount: v.amount }),
    onSuccess: () => { toast.success("Bet updated"); invalidateBets(); },
    onError: (e: any) => toast.error(e?.message || "Update failed"),
  });
  const cancelBet = useMutation({
    mutationFn: (betId: string) => GamesAPI.cancelBet(betId),
    onSuccess: () => { toast.success("Bet cancelled — stake refunded"); invalidateBets(); },
    onError: (e: any) => toast.error(e?.message || "Cancel failed"),
  });
  function editUpDownBet(b: any) {
    const dStr = window.prompt(`New direction UP or DOWN (blank = keep ${b.prediction})`, "");
    if (dStr === null) return;
    const aStr = window.prompt(`New amount (blank = keep ${num(b.amount)})`, "");
    if (aStr === null) return;
    const body: { id: string; prediction?: "UP" | "DOWN"; amount?: number } = { id: b.id };
    const d = dStr.trim().toUpperCase();
    if (d === "UP" || d === "DOWN") body.prediction = d;
    else if (d !== "") { toast.error("Direction must be UP or DOWN"); return; }
    if (aStr.trim() !== "") body.amount = Number(aStr);
    if (body.prediction === undefined && body.amount === undefined) return;
    modifyBet.mutate(body);
  }

  return (
    <div className="space-y-3">
      {/* Game header — compact */}
      <div className="flex items-center gap-2.5">
        <span className={cn("grid size-9 place-items-center rounded-lg", asset === "btc" ? "bg-atm/15 text-atm" : "bg-primary/10 text-primary")}>
          <TrendingUp className="size-5" />
        </span>
        <div>
          <h1 className="text-lg font-bold tracking-tight">{meta.title}</h1>
          <div className="text-[11px] font-semibold text-primary">{mult}x Returns</div>
        </div>
      </div>

      {/* ── How-to-play banner (fills the top strip; clear + bold) ── */}
      <Card className="overflow-hidden border-primary/30 bg-primary/5">
        <CardContent className="p-3">
          <div className="flex flex-col gap-2.5 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-2.5">
              <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/15 text-primary">
                <Clock className="size-5" />
              </span>
              <div>
                <div className="text-sm font-bold">How to play · 15-min game</div>
                <div className="text-[11px] leading-snug text-muted-foreground">
                  You predict the <b className="text-foreground">NEXT</b> 15-min window. Result comes when the next window closes (~15 min later).
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-[11px] font-bold">
              <span className="inline-flex items-center gap-1 rounded-md bg-buy/15 px-2 py-1 text-buy">
                <TrendingUp className="size-3.5" /> UP = next close HIGHER
              </span>
              <span className="inline-flex items-center gap-1 rounded-md bg-sell/15 px-2 py-1 text-sell">
                <TrendingDown className="size-3.5" /> DOWN = next close LOWER
              </span>
              <span className="inline-flex items-center gap-1 rounded-md bg-atm/15 px-2 py-1 text-atm">
                <Trophy className="size-3.5" /> Win = {mult}× stake
              </span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Mobile order: Window → Price → Live OHLC → Bet → Last-5 → History.
          Desktop (lg): 3 cols — [Window/OHLC/Last-5] · [History] · [Price/Bet]. */}
      <div className="grid items-start gap-3 lg:grid-cols-[230px_minmax(0,1fr)_300px]">
        {/* Window — mobile 1 · desktop col1 row1 */}
        <div className="order-1 lg:order-none lg:col-start-1 lg:row-start-1">
          <Card className="overflow-hidden border-buy/30">
            <CardContent className="relative space-y-2 p-3">
              <span aria-hidden className="pointer-events-none absolute -right-8 -top-8 size-20 rounded-full bg-buy/10 blur-2xl" />
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-xs font-bold">
                  <span className="size-1.5 rounded-full bg-buy animate-pulse" /> WINDOW #{win?.windowNumber ?? "—"}
                </div>
                {openAt && closeAt && (
                  <div className="text-[10px] tabular-nums text-muted-foreground">
                    {fmtIST(openAt)} → {fmtIST(closeAt)}
                  </div>
                )}
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">Window closes in</div>
                {win?.canTrade ? (
                  <Countdown seconds={win.secondsToClose} className="text-3xl font-bold text-foreground" />
                ) : (
                  <div className="text-xl font-bold text-muted-foreground">{win?.status === "pre_market" ? "Opens soon" : "Closed"}</div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Price — mobile 2 · desktop col3 row1 */}
        <div className="order-2 lg:order-none lg:col-start-3 lg:row-start-1">
          <Card className="overflow-hidden">
            <CardContent className="relative p-3 text-center">
              <span aria-hidden className={cn("pointer-events-none absolute -right-8 -top-8 size-20 rounded-full blur-2xl", asset === "btc" ? "bg-atm/10" : "bg-primary/10")} />
              <div className="flex items-center justify-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                {asset === "btc" ? "BTC/USDT" : "NIFTY"} price <LiveDot live={!!live} label="LIVE" />
              </div>
              <LivePrice value={liveNum} className="justify-center text-2xl font-bold" />
            </CardContent>
          </Card>
        </div>

        {/* Live OHLC + Last-5 — mobile 3 · desktop col1 row2.
            Both live in ONE grid cell so the tall bet panel in col3 can't
            open an empty gap between them (was the "bich me khali" issue). */}
        <div className="order-3 space-y-3 lg:order-none lg:col-start-1 lg:row-start-2">
          <Card className="overflow-hidden">
            <CardContent className="space-y-2 p-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-bold">{asset === "btc" ? "BTC/USDT" : "NIFTY 50"}</span>
                  <LiveDot live={!!live} label="LIVE" />
                </div>
                <span className="text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">{ivLabel} O/H/L/C</span>
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                <OhlcPanel title="Forming" c={formingLive} accent />
                <OhlcPanel title="Last closed" c={lastClosed} />
              </div>
            </CardContent>
          </Card>

          {/* Last 5 results */}
          <Card className="overflow-hidden border-atm/25">
            <CardContent className="space-y-2 p-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-[11px] font-bold">
                  <Trophy className="size-3.5 text-atm" /> Last 5 results
                </div>
                <span className="text-[9px] uppercase tracking-wide text-muted-foreground">who won</span>
              </div>
              {(results || []).length > 0 ? (
                <>
                  <div className="flex items-center gap-1">
                    {(results || []).slice(0, 5).map((r: any, i: number) => {
                      const up = r.result === "UP";
                      const down = r.result === "DOWN";
                      return (
                        <span
                          key={i}
                          title={`W#${r.window_number} · ${r.result}`}
                          className={cn(
                            "grid h-7 flex-1 place-items-center rounded-md text-[11px] font-bold ring-1 ring-inset",
                            up ? "bg-buy/15 text-buy ring-buy/30" : down ? "bg-sell/15 text-sell ring-sell/30" : "bg-muted text-muted-foreground ring-border",
                          )}
                        >
                          {up ? <TrendingUp className="size-3.5" /> : down ? <TrendingDown className="size-3.5" /> : "="}
                        </span>
                      );
                    })}
                  </div>
                  <div className="space-y-1">
                    {(results || []).slice(0, 5).map((r: any, i: number) => {
                      const up = r.result === "UP";
                      const down = r.result === "DOWN";
                      return (
                        <div
                          key={i}
                          className={cn(
                            "flex items-center justify-between rounded-md border px-2 py-1",
                            up ? "border-buy/20 bg-buy/5" : down ? "border-sell/20 bg-sell/5" : "border-border bg-muted/20",
                          )}
                        >
                          <div className="flex items-center gap-1.5">
                            <span className="text-[10px] tabular-nums text-muted-foreground">#{r.window_number}</span>
                            <span className={cn("inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-bold",
                              up ? "bg-buy/15 text-buy" : down ? "bg-sell/15 text-sell" : "bg-muted text-muted-foreground")}>
                              {up ? <TrendingUp className="size-3" /> : down ? <TrendingDown className="size-3" /> : null}
                              {r.result}
                            </span>
                          </div>
                          <div className="flex flex-col items-end leading-tight">
                            <span className="text-xs font-bold tabular-nums">{fmt2(num(r.close_price))}</span>
                            <span className="text-[9px] tabular-nums text-muted-foreground">
                              {resultWindowTime(cfg?.start_time, roundSec, r.window_number)}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </>
              ) : (
                <div className="py-1.5 text-[11px] text-muted-foreground">No results yet.</div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Bet — mobile 4 · desktop col3 row2 */}
        <div className="order-4 lg:order-none lg:col-start-3 lg:row-start-2">
          <Card>
            <CardContent className="space-y-2.5 p-3">
              <div className="flex items-center justify-between text-[11px]">
                <span className="font-semibold text-muted-foreground">Enter tickets</span>
                <span className="tabular-nums text-muted-foreground">Bal {balanceTkt.toFixed(1)} Tkt</span>
              </div>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="icon" className="size-8" onClick={() => setTickets((t) => Math.max(minTickets, t - 1))}>−</Button>
                <div className="flex-1 rounded-lg border border-border bg-muted/30 py-1.5 text-center">
                  <span className="text-lg font-bold tabular-nums">{tickets}</span>
                  <span className="ml-1 text-[11px] text-muted-foreground">Tkt</span>
                </div>
                <Button variant="outline" size="icon" className="size-8" onClick={() => setTickets((t) => Math.min(maxTickets, t + 1))}>+</Button>
              </div>
              <div className="grid grid-cols-4 gap-1.5">
                {TICKET_QUICK.map((t) => (
                  <button
                    key={t}
                    onClick={() => setTickets(Math.min(maxTickets, t))}
                    className={cn(
                      "rounded-md border py-1 text-[11px] font-bold transition-colors",
                      tickets === t ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:border-primary/40",
                    )}
                  >
                    {t} T
                  </button>
                ))}
              </div>
              <div className="flex items-center justify-between rounded-lg bg-muted/30 px-2.5 py-1.5 text-[11px]">
                <span className="text-muted-foreground">Stake {formatINR(amount)}</span>
                <span className="font-bold text-buy">Win {formatINR(potential)}</span>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => { setPrediction("UP"); }}
                  className={cn("flex flex-col items-center gap-0.5 rounded-lg border-2 py-2 text-sm font-bold transition-all",
                    prediction === "UP" ? "border-buy bg-buy/15 text-buy" : "border-border hover:border-buy/40")}
                >
                  <TrendingUp className="size-5" /> UP
                </button>
                <button
                  type="button"
                  onClick={() => { setPrediction("DOWN"); }}
                  className={cn("flex flex-col items-center gap-0.5 rounded-lg border-2 py-2 text-sm font-bold transition-all",
                    prediction === "DOWN" ? "border-sell bg-sell/15 text-sell" : "border-border hover:border-sell/40")}
                >
                  <TrendingDown className="size-5" /> DOWN
                </button>
              </div>
              <Button className="w-full" loading={place.isPending} disabled={place.isPending || !win?.canTrade || !prediction} onClick={() => place.mutate()}>
                {!win?.canTrade ? "Window closed" : prediction ? `Place ${tickets} T · ${prediction}` : "Pick UP or DOWN"}
              </Button>
              <p className="rounded-md bg-muted/40 px-2 py-1.5 text-center text-[10px] leading-snug text-muted-foreground">
                Predicting the <b className="text-foreground">next</b> 15-min move · result at next window&apos;s close vs this window&apos;s close.
              </p>
              <p className="text-center text-[10px] text-muted-foreground">Min {minTickets} · Max {maxTickets} · 1 Tkt = 🪙{ticketPrice}</p>
            </CardContent>
          </Card>
        </div>

        {/* My bet history — mobile last · desktop col2 span all rows */}
        <Card className="order-6 min-w-0 lg:order-none lg:col-start-2 lg:row-start-1 lg:row-span-2 lg:h-full">
          <CardContent className="p-3">
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-semibold"><Trophy className="size-4 text-primary" /> My bet history</div>
              <span className="text-[11px] text-muted-foreground">Last {(bets || []).length}</span>
            </div>
            {(bets || []).length === 0 ? (
              <div className="py-10 text-center text-sm text-muted-foreground">No bets yet — place your first UP/DOWN.</div>
            ) : (
              <div className="max-h-[62vh] overflow-y-auto scrollbar-thin">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-card">
                    <tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted-foreground">
                      <th className="py-1.5 pr-2 font-medium">Win#</th>
                      <th className="py-1.5 pr-2 font-medium">Side</th>
                      <th className="py-1.5 pr-2 font-medium">Tkt</th>
                      <th className="py-1.5 pr-2 font-medium">Stake</th>
                      <th className="py-1.5 pr-2 font-medium">Result</th>
                      <th className="py-1.5 pr-2 text-right font-medium">P&amp;L</th>
                      <th className="py-1.5 text-right font-medium">Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(bets || []).map((b: any) => {
                      const won = b.status === "WON";
                      const lost = b.status === "LOST" || b.status === "TIE";
                      const tks = ticketPrice > 0 ? Math.round(num(b.amount) / ticketPrice) : 0;
                      return (
                        <tr key={b.id} className="border-b border-border/50 last:border-0">
                          <td className="py-1.5 pr-2 text-[11px] text-muted-foreground">#{b.window_number}</td>
                          <td className={cn("py-1.5 pr-2 text-xs font-semibold", b.prediction === "UP" ? "text-buy" : "text-sell")}>{b.prediction}</td>
                          <td className="py-1.5 pr-2 text-xs tabular-nums">{tks}</td>
                          <td className="py-1.5 pr-2 text-xs tabular-nums">{formatINR(b.amount)}</td>
                          <td className="py-1.5 pr-2">
                            {b.status === "PENDING" ? (
                              <span className="flex items-center gap-1.5">
                                <button className="text-[11px] font-semibold text-primary hover:underline disabled:opacity-50"
                                  disabled={modifyBet.isPending} onClick={() => editUpDownBet(b)}>Edit</button>
                                <button className="text-[11px] font-semibold text-sell hover:underline disabled:opacity-50"
                                  disabled={cancelBet.isPending}
                                  onClick={() => { if (window.confirm("Cancel this bet? Your stake will be refunded.")) cancelBet.mutate(b.id); }}>Cancel</button>
                              </span>
                            ) : won ? (
                              <GameStatePill state="win" label="Won" />
                            ) : b.status === "CANCELLED" ? (
                              <GameStatePill state="pending" label="Cancelled" />
                            ) : (
                              <GameStatePill state="loss" label={b.status === "TIE" ? "Tie" : "Lost"} />
                            )}
                          </td>
                          <td className={cn("py-1.5 pr-2 text-right text-xs font-bold tabular-nums", won ? "text-buy" : lost ? "text-sell" : "text-muted-foreground")}>
                            {won ? `+${formatINR(b.payout)}` : lost ? `−${formatINR(b.amount)}` : "—"}
                          </td>
                          <td className="py-1.5 text-right text-[10px] tabular-nums text-muted-foreground">
                            {b.created_at ? new Date(b.created_at).toLocaleTimeString("en-GB", { timeZone: "Asia/Kolkata", hour12: false }) : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function OhlcPanel({ title, c, accent }: { title: string; c?: Candle; accent?: boolean }) {
  const up = c ? c.close >= c.open : true;
  const row = (k: string, v: number | undefined) => (
    <div className="flex items-center justify-between text-[11px]">
      <span className="text-muted-foreground">{k}</span>
      <span className="font-semibold tabular-nums">{fmt2(v)}</span>
    </div>
  );
  return (
    <div className={cn("rounded-lg border p-2.5", accent ? "border-primary/30 bg-primary/5" : "border-border bg-muted/20")}>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{title}</span>
        {c && <span className={cn("size-1.5 rounded-full", up ? "bg-buy" : "bg-sell")} />}
      </div>
      {row("O", c?.open)}
      {row("H", c?.high)}
      {row("L", c?.low)}
      {row("C", c?.close)}
    </div>
  );
}
