"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatCoins as formatINR } from "@/lib/games/coins";
import { GamesAPI } from "@/lib/api";
import { GAME_META, type GameUiId } from "@/lib/games/ids";
import { isBiddingOpen, secondsUntilIst, formatDurationHuman } from "@/lib/games/window";
import { useGameConfig, useGamesWallet, useGamesPrice } from "@/components/games/useGames";
import { Countdown, GameHowTo, GameStatePill, StatChip, LiveDot, LivePrice, WinningDigitsPrice } from "@/components/games/bits";

export function NumberScreen({ id }: { id: GameUiId }) {
  const meta = GAME_META[id];
  const cfg = useGameConfig(id);
  const { data: wallet } = useGamesWallet();
  const { data: price } = useGamesPrice(250);
  const qc = useQueryClient();
  const [selected, setSelected] = useState<number[]>([]);
  const [qty, setQty] = useState(1);

  const live = meta.asset === "BTC" ? price?.btc : price?.nifty;
  const liveNum = live ? Number(live) : 0;
  // The winning number is derived from the live close — spell it out so the
  // player sees which digits of the current price matter.
  const digitHint = meta.asset === "BTC" ? "last 2 digits" : "closing decimals";

  const allDecimals = !!cfg?.all_decimals;
  const numbers = useMemo(() => {
    const arr: number[] = [];
    const step = allDecimals ? 1 : 5;
    const max = allDecimals ? 99 : 95;
    for (let n = 0; n <= max; n += step) arr.push(n);
    return arr;
  }, [allDecimals]);

  const open = cfg ? isBiddingOpen(cfg.bidding_start_time, cfg.bidding_end_time) : false;
  const balance = Number(wallet?.balance ?? 0);
  const ticketPrice = Number(cfg?.ticket_price ?? 0);
  const cost = selected.length * qty * ticketPrice;

  const { data: today } = useQuery({
    queryKey: ["games", "bets", "number-today", id],
    queryFn: () => GamesAPI.numberToday(id),
    refetchInterval: 5000,
  });
  const { data: result } = useQuery({
    queryKey: ["games", "results", "number", id],
    queryFn: () => GamesAPI.numberResult(id),
    refetchInterval: 30000,
  });
  const { data: last5 } = useQuery({
    queryKey: ["games", "results", "number-last5", id],
    queryFn: () => GamesAPI.numberLast5(id),
    refetchInterval: 60000,
  });

  const place = useMutation({
    mutationFn: async () => {
      if (selected.length === 0) throw new Error("Pick at least one number");
      if (cost > balance) throw new Error("Insufficient games balance");
      return GamesAPI.numberBet({ gameId: id, selectedNumbers: selected, quantity: qty });
    },
    onSuccess: () => {
      toast.success("Bet placed");
      setSelected([]);
      qc.invalidateQueries({ queryKey: ["games", "bets", "number-today", id] });
      qc.invalidateQueries({ queryKey: ["games", "wallet"] });
    },
    onError: (e: any) => toast.error(e?.message || "Could not place bet"),
  });

  const invalidateBets = () => {
    qc.invalidateQueries({ queryKey: ["games", "bets", "number-today", id] });
    qc.invalidateQueries({ queryKey: ["games", "wallet"] });
  };
  const modify = useMutation({
    mutationFn: (v: { id: string; selectedNumber?: number; quantity?: number }) =>
      GamesAPI.numberModify(v.id, { selectedNumber: v.selectedNumber, quantity: v.quantity }),
    onSuccess: () => { toast.success("Bet updated"); invalidateBets(); },
    onError: (e: any) => toast.error(e?.message || "Update failed"),
  });
  const cancel = useMutation({
    mutationFn: (betId: string) => GamesAPI.numberCancel(betId),
    onSuccess: () => { toast.success("Bet cancelled — stake refunded"); invalidateBets(); },
    onError: (e: any) => toast.error(e?.message || "Cancel failed"),
  });
  function editNumberBet(b: any) {
    const nStr = window.prompt(`New number (blank = keep ${fmt(b.number)})`, "");
    if (nStr === null) return; // cancelled the prompt
    const qStr = window.prompt(`New ticket quantity (blank = keep ${b.quantity})`, "");
    if (qStr === null) return;
    const body: { id: string; selectedNumber?: number; quantity?: number } = { id: b.id };
    if (nStr.trim() !== "") body.selectedNumber = Number(nStr);
    if (qStr.trim() !== "") body.quantity = Number(qStr);
    if (body.selectedNumber === undefined && body.quantity === undefined) return;
    modify.mutate(body);
  }

  const fmt = (n: number) => (allDecimals ? String(n).padStart(2, "0") : `.${String(n).padStart(2, "0")}`);

  const resultIn = cfg ? secondsUntilIst(cfg.result_time) : 0;
  const declared = !!result?.declared;

  // Payout per winning ticket: fixed profit when set, else ticket × multiplier.
  const perTicketPayout = Number(cfg?.fixed_profit ?? 0) > 0
    ? Number(cfg?.fixed_profit)
    : ticketPrice * Number(cfg?.win_multiplier ?? 0);

  return (
    <div className="space-y-4">
      <GameHowTo
        costText={`1 ticket = ${formatINR(ticketPrice)}`}
        payoutLabel={`Win pays ${formatINR(perTicketPayout)}/ticket`}
        steps={[
          "Pick one or more numbers",
          `Each number = 1 ticket (${formatINR(ticketPrice)})`,
          meta.asset === "BTC"
            ? "You win if the price's last 2 digits at result time match your number"
            : "You win if NIFTY's closing decimals at result time match your number",
        ]}
      />
    <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_300px] lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0 space-y-4">
        {/* Result countdown */}
        <Card className="overflow-hidden border-primary/30">
          <CardContent className="relative p-4">
            <span aria-hidden className="pointer-events-none absolute -right-10 -top-10 size-40 rounded-full bg-primary/10 blur-3xl" />
            <div className="flex items-center justify-between">
              <div className="text-xs uppercase tracking-wider text-muted-foreground">{meta.title} · Result</div>
              {declared ? (
                <GameStatePill state="win" label="Declared" />
              ) : open ? (
                <GameStatePill state="open" label="Bidding open" />
              ) : (
                <GameStatePill state="pending" label="Bidding closed" />
              )}
            </div>

            {declared ? (
              <div className="mt-2">
                <div className="text-xs text-muted-foreground">Winning number</div>
                <div className="text-4xl font-extrabold text-buy">{fmt(result.result_number)}</div>
              </div>
            ) : (
              <div className="mt-2">
                <div className="text-xs text-muted-foreground">
                  {resultIn > 0 ? "Result declares in" : "Declaring result…"}
                </div>
                <Countdown seconds={resultIn} className="text-4xl font-extrabold text-foreground" />
                {resultIn > 0 && (
                  <div className="mt-0.5 text-xs font-medium text-primary">≈ {formatDurationHuman(resultIn)}</div>
                )}
              </div>
            )}

            <div className="mt-3 grid grid-cols-2 gap-2 border-t border-border pt-2 text-xs">
              <div className="text-muted-foreground">
                Bidding closes <span className="font-semibold text-foreground">{cfg?.bidding_end_time?.slice(0, 5)}</span>
              </div>
              <div className="text-right text-muted-foreground">
                Result @ <span className="font-semibold text-foreground">{cfg?.result_time?.slice(0, 5)}</span> IST
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="overflow-hidden">
          <CardContent className="relative p-4 sm:p-5">
            <span
              aria-hidden
              className={cn(
                "pointer-events-none absolute -right-10 -top-10 size-40 rounded-full blur-3xl",
                meta.asset === "BTC" ? "bg-atm/10" : "bg-primary/10",
              )}
            />
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                      meta.asset === "BTC" ? "bg-atm/15 text-atm" : "bg-primary/10 text-primary",
                    )}
                  >
                    {meta.asset}
                  </span>
                  <span className="truncate text-xs uppercase tracking-wider text-muted-foreground">Reference spot · winning digits</span>
                </div>
                <WinningDigitsPrice
                  value={
                    // Once the result is DECLARED, freeze this card on the exact
                    // close price the winning number was derived from (the
                    // server's frozen `closing_price`). Otherwise it keeps
                    // drifting with the live feed and its highlighted decimals
                    // (e.g. .80) no longer match the declared number (.90).
                    declared && result?.closing_price ? Number(result.closing_price) : liveNum
                  }
                  mode={meta.asset === "BTC" ? "btc" : "nifty"}
                  className="mt-1 text-3xl font-bold sm:text-4xl"
                />
                <div className="mt-1">
                  <LiveDot
                    live={declared ? false : !!live}
                    label={
                      declared
                        ? `Result price · winning ${digitHint}`
                        : live
                          ? `Winning number = ${digitHint}`
                          : "Waiting for feed"
                    }
                  />
                </div>
              </div>
              {result?.declared ? (
                <GameStatePill state="win" label={`Result: ${fmt(result.result_number)}`} />
              ) : open ? (
                <GameStatePill state="open" label="Bidding open" />
              ) : (
                <GameStatePill state="closed" label="Closed" />
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle>Pick your numbers</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
              <span>Tap the numbers you want</span>
              {selected.length > 0 && (
                <button type="button" onClick={() => setSelected([])} className="font-medium hover:text-foreground">
                  Clear ({selected.length})
                </button>
              )}
            </div>
            <div className="grid grid-cols-5 gap-1.5 xs:grid-cols-6 sm:grid-cols-10">
              {numbers.map((n) => {
                const on = selected.includes(n);
                return (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setSelected((s) => (on ? s.filter((x) => x !== n) : [...s, n]))}
                    className={cn(
                      "min-h-9 rounded-md border py-2 text-sm font-semibold tabular-nums transition-all",
                      on ? "border-primary bg-primary/10 text-primary" : "border-border hover:border-primary/40",
                    )}
                  >
                    {fmt(n)}
                  </button>
                );
              })}
            </div>
          </CardContent>
        </Card>

        {/* Last 5 days winning numbers */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle>Last 5 days results</CardTitle>
          </CardHeader>
          <CardContent>
            {(last5 || []).length === 0 ? (
              <div className="py-2 text-sm text-muted-foreground">No past results yet.</div>
            ) : (
              <div className="grid grid-cols-2 gap-2 xs:grid-cols-3 sm:grid-cols-5">
                {(last5 || []).map((r: any) => (
                  <div
                    key={r.day}
                    className="rounded-xl border border-border bg-muted/20 p-3 text-center transition-colors hover:border-primary/40"
                  >
                    <div className="text-[11px] font-medium text-muted-foreground">
                      {new Date(r.day).toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}
                    </div>
                    <div className="my-0.5 text-2xl font-extrabold tabular-nums text-primary">{fmt(r.result_number)}</div>
                    <div className="truncate text-[10px] tabular-nums text-muted-foreground">
                      {Number(r.closing_price).toLocaleString("en-IN", { maximumFractionDigits: 2 })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3"><CardTitle>Today's bets</CardTitle></CardHeader>
          <CardContent className="space-y-1">
            {(today?.bets || []).length === 0 && <div className="py-2 text-sm text-muted-foreground">No bets today.</div>}
            {(today?.bets || []).map((b: any) => (
              <div key={b.id} className="flex items-center justify-between border-b border-border/60 py-2 text-sm last:border-0">
                <span className="font-semibold tabular-nums">{fmt(b.number)} × {b.quantity}</span>
                <span className="flex items-center gap-3">
                  <span className="tabular-nums">{formatINR(b.amount)}</span>
                  {b.status === "PENDING" ? (
                    <span className="flex items-center gap-2">
                      <button className="text-xs font-semibold text-primary hover:underline disabled:opacity-50"
                        disabled={modify.isPending} onClick={() => editNumberBet(b)}>Edit</button>
                      <button className="text-xs font-semibold text-sell hover:underline disabled:opacity-50"
                        disabled={cancel.isPending}
                        onClick={() => { if (window.confirm("Cancel this bet? Your stake will be refunded.")) cancel.mutate(b.id); }}>Cancel</button>
                      <GameStatePill state="pending" label="Pending" />
                    </span>
                  ) : b.status === "WON" ? <GameStatePill state="win" label={`+${formatINR(b.payout)}`} />
                    : b.status === "CANCELLED" ? <GameStatePill state="pending" label="Cancelled" />
                    : <GameStatePill state="loss" label="Lost" />}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card className="h-fit md:sticky md:top-4">
        <CardHeader className="pb-3"><CardTitle>Place bet</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Tickets / number</span>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="icon" onClick={() => setQty((q) => Math.max(1, q - 1))}>−</Button>
              <span className="w-6 text-center font-bold tabular-nums">{qty}</span>
              <Button variant="outline" size="icon" onClick={() => setQty((q) => Math.min(cfg?.max_tickets_per_number ?? 2, q + 1))}>+</Button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <StatChip label="Selected" value={String(selected.length)} />
            <StatChip label="Cost" value={formatINR(cost)} />
          </div>
          <Button className="w-full" size="lg" loading={place.isPending} disabled={place.isPending || !open} onClick={() => place.mutate()}>
            {open ? "Place bet" : "Bidding closed"}
          </Button>
          <p className="text-center text-[11px] text-muted-foreground">
            Win pays {cfg?.fixed_profit ? formatINR(cfg.fixed_profit) : `${cfg?.win_multiplier}×`} per ticket
          </p>
        </CardContent>
      </Card>
    </div>
    </div>
  );
}
